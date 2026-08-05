from __future__ import annotations

import asyncio
import base64
import contextlib
import fnmatch
import ipaddress
import json
import os
import socket
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlsplit
from uuid import uuid4

from mycodingagent.configuration.settings import NetworkConfig
from mycodingagent.network_access import NetworkAccessRuntime


MANAGED_LABEL = "com.mycodingagent.managed"
RUNTIME_ID_LABEL = "com.mycodingagent.runtime"
RUNTIME_KIND_LABEL = "com.mycodingagent.kind"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
METADATA_HOSTS = frozenset({"169.254.169.254", "metadata.google.internal"})


@dataclass(frozen=True)
class NetworkRuntimeStatus:
    ready: bool
    reason: str = ""


class NetworkPolicyError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "network_policy_denied",
        status: int = 403,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.status = status
        self.retryable = retryable


class ManagedNetworkRuntime:
    """Own one session-private Docker network and its only public egress path."""

    def __init__(
        self,
        config: NetworkConfig,
        access: NetworkAccessRuntime,
        *,
        workspace_root: Path,
        runtime_id: str | None = None,
    ) -> None:
        self.config = config
        self.access = access
        self.workspace_root = workspace_root.resolve(strict=False)
        self.runtime_id = runtime_id or uuid4().hex
        self.network_name = f"mycodingagent-network-{self.runtime_id[:12]}"
        self.gateway = ""
        self.proxy_port = 0
        self._server: asyncio.AbstractServer | None = None
        self._connections: set[asyncio.Task[None]] = set()
        self._local_target: Callable[[int], Awaitable[tuple[str, int] | None]] | None = None
        self._network_ready = False
        self.access.bind_change_hook(self.apply_access_policy)

    @property
    def proxy_url(self) -> str:
        return f"http://{self.gateway}:{self.proxy_port}" if self.gateway and self.proxy_port else ""

    @property
    def proxy_environment(self) -> dict[str, str]:
        if not self.proxy_url:
            return {}
        no_proxy = "mycodingagent-devserver"
        return {
            "HTTP_PROXY": self.proxy_url,
            "HTTPS_PROXY": self.proxy_url,
            "ALL_PROXY": self.proxy_url,
            "http_proxy": self.proxy_url,
            "https_proxy": self.proxy_url,
            "all_proxy": self.proxy_url,
            "NO_PROXY": no_proxy,
            "no_proxy": no_proxy,
        }

    def bind_local_target(
        self,
        resolver: Callable[[int], Awaitable[tuple[str, int] | None]] | None,
    ) -> None:
        self._local_target = resolver

    async def initialize(self) -> NetworkRuntimeStatus:
        if not _docker_available():
            return NetworkRuntimeStatus(False, "未找到 docker")
        created = await _docker(
            "network", "create", "--internal", "--driver", "bridge",
            "--label", f"{MANAGED_LABEL}=true",
            "--label", f"{RUNTIME_KIND_LABEL}=managed-network",
            "--label", f"{RUNTIME_ID_LABEL}={self.runtime_id}",
            self.network_name,
        )
        if created.returncode != 0:
            return NetworkRuntimeStatus(False, _process_error("创建托管网络失败", created))
        self._network_ready = True
        inspected = await _docker(
            "network", "inspect", "--format", "{{(index .IPAM.Config 0).Gateway}}", self.network_name
        )
        if inspected.returncode != 0 or not inspected.stdout.strip():
            await self.close()
            return NetworkRuntimeStatus(False, _process_error("读取托管网络网关失败", inspected))
        self.gateway = inspected.stdout.strip()
        try:
            self._server = await asyncio.start_server(self._accept, self.gateway, 0)
        except OSError as exc:
            await self.close()
            return NetworkRuntimeStatus(False, f"启动托管网络代理失败：{exc}")
        sockets = self._server.sockets or ()
        if not sockets:
            await self.close()
            return NetworkRuntimeStatus(False, "启动托管网络代理失败：没有监听 socket")
        self.proxy_port = int(sockets[0].getsockname()[1])
        return NetworkRuntimeStatus(True)

    async def apply_access_policy(self, enabled: bool) -> None:
        if enabled:
            return
        current = asyncio.current_task()
        tasks = [task for task in self._connections if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        await self.close_local()
        if self._network_ready:
            await _docker("network", "rm", self.network_name)
        self._network_ready = False

    async def close_local(self) -> None:
        """Stop proxy activity without waiting for Docker network removal."""
        self.access.bind_change_hook(None)
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        tasks = list(self._connections)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.proxy_port = 0

    def display_upstream(self) -> str:
        value = self._selected_upstream("https") or "direct"
        if value == "direct":
            return value
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{host}{port}"

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)
        try:
            await self._serve_connection(reader, writer)
        except asyncio.CancelledError:
            raise
        except NetworkPolicyError as exc:
            with contextlib.suppress(Exception):
                await self._respond_error(writer, exc)
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                await self._respond_error(
                    writer,
                    NetworkPolicyError(
                        "网络连接超时",
                        error_code="network_timeout",
                        status=504,
                        retryable=True,
                    ),
                )
        except (ConnectionError, OSError) as exc:
            with contextlib.suppress(Exception):
                await self._respond_error(
                    writer,
                    NetworkPolicyError(
                        f"网络连接失败：{exc}",
                        error_code="network_connection_failed",
                        status=502,
                        retryable=True,
                    ),
                )
        finally:
            if task is not None:
                self._connections.discard(task)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _serve_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), self.config.connect_timeout)
        if len(header) > 64 * 1024:
            raise NetworkPolicyError("代理请求头过大", error_code="invalid_proxy_request", status=400)
        first_line = header.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
        parts = first_line.split(" ", 2)
        if len(parts) != 3:
            raise NetworkPolicyError("代理请求行无效", error_code="invalid_proxy_request", status=400)
        method, target, _version = parts
        if method.upper() == "CONNECT":
            host, port = _split_authority(target, 443)
            remote_reader, remote_writer = await self._open_target(host, port, "https")
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await self._relay(reader, writer, remote_reader, remote_writer)
            return
        parsed = urlsplit(target)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            await self._respond(writer, 400, "absolute HTTP URL required")
            return
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        remote_reader, remote_writer = await self._open_target(parsed.hostname, port, parsed.scheme)
        upstream = self._selected_upstream(parsed.scheme)
        request_header = header
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        request_header = header.replace(
            first_line.encode("latin-1"), f"{method} {path} {_version}".encode("latin-1"), 1
        )
        remote_writer.write(request_header)
        await remote_writer.drain()
        await self._relay(reader, writer, remote_reader, remote_writer)

    async def _open_target(
        self, host: str, port: int, target_scheme: str
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        local = host.rstrip(".").lower() in LOCAL_HOSTS
        if local:
            if self._local_target is None:
                raise NetworkPolicyError(
                    "本地开发服务尚未就绪",
                    error_code="local_service_unavailable",
                    status=503,
                    retryable=True,
                )
            resolved = await self._local_target(port)
            if resolved is None:
                raise NetworkPolicyError(
                    "本地开发服务尚未就绪",
                    error_code="local_service_unavailable",
                    status=503,
                    retryable=True,
                )
            return await asyncio.wait_for(
                asyncio.open_connection(resolved[0], resolved[1]), self.config.connect_timeout
            )
        if not self.access.enabled:
            raise NetworkPolicyError("Agent 工具公网权限已关闭", error_code="network_disabled")
        upstream = self._selected_upstream(target_scheme)
        use_direct = not upstream or upstream == "direct" or _matches_no_proxy(host, port)
        await self._validate_target(host, port, resolve_dns=use_direct)
        if use_direct:
            return await asyncio.wait_for(
                asyncio.open_connection(host, port), self.config.connect_timeout
            )
        parsed = urlsplit(upstream)
        if parsed.scheme in {"socks5", "socks5h", "socks4"}:
            return await self._open_socks(upstream, host, port)
        return await self._open_http_proxy(upstream, host, port)

    async def _open_socks(
        self, proxy_url: str, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        try:
            from python_socks.async_.asyncio import Proxy
        except ImportError as exc:
            raise NetworkPolicyError(
                "缺少 SOCKS 上游支持依赖 python-socks",
                error_code="proxy_dependency_missing",
                status=502,
            ) from exc
        try:
            sock = await asyncio.wait_for(
                Proxy.from_url(proxy_url).connect(dest_host=host, dest_port=port),
                self.config.connect_timeout,
            )
        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            raise NetworkPolicyError(
                f"SOCKS 上游代理连接失败：{exc}",
                error_code="upstream_proxy_failed",
                status=502,
                retryable=True,
            ) from exc
        reader, writer = await asyncio.open_connection(sock=sock)
        return reader, writer

    async def _open_http_proxy(
        self, proxy_url: str, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        parsed = urlsplit(proxy_url)
        proxy_host = parsed.hostname or ""
        proxy_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        ssl_context = self._ssl_context() if parsed.scheme == "https" else None
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(proxy_host, proxy_port, ssl=ssl_context, server_hostname=proxy_host if ssl_context else None),
            self.config.connect_timeout,
        )
        headers = [f"CONNECT {host}:{port} HTTP/1.1", f"Host: {host}:{port}"]
        if parsed.username is not None:
            password = parsed.password or ""
            token = base64.b64encode(f"{parsed.username}:{password}".encode()).decode()
            headers.append(f"Proxy-Authorization: Basic {token}")
        writer.write(("\r\n".join(headers) + "\r\n\r\n").encode("latin-1"))
        await writer.drain()
        response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), self.config.connect_timeout)
        status = response.split(b"\r\n", 1)[0].split()
        if len(status) < 2 or status[1] != b"200":
            writer.close()
            raise NetworkPolicyError(
                "上游 HTTP 代理拒绝 CONNECT",
                error_code="upstream_proxy_rejected",
                status=502,
                retryable=False,
            )
        return reader, writer

    async def _validate_target(self, host: str, port: int, *, resolve_dns: bool) -> None:
        normalized = host.rstrip(".").lower()
        if normalized in METADATA_HOSTS or not _domain_allowed(
            normalized, self.config.allow_domains, self.config.deny_domains
        ):
            raise NetworkPolicyError(
                f"目标域名被网络策略拒绝：{normalized}",
                error_code="domain_denied",
            )
        try:
            address = ipaddress.ip_address(normalized)
        except ValueError:
            address = None
        if address is not None:
            if not _is_public_address(str(address)):
                raise NetworkPolicyError(
                    f"目标 IP 不是公网地址：{normalized}",
                    error_code="private_target_denied",
                )
            return
        if not resolve_dns:
            return
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                normalized, port, type=socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            raise NetworkPolicyError(
                f"目标域名解析失败：{normalized}",
                error_code="dns_resolution_failed",
                status=502,
                retryable=True,
            ) from exc
        addresses = {item[4][0] for item in infos}
        if not addresses or any(not _is_public_address(value) for value in addresses):
            raise NetworkPolicyError(
                f"目标解析到非公网地址：{normalized}",
                error_code="private_target_denied",
            )

    def _selected_upstream(self, target_scheme: str) -> str:
        configured = self.config.upstream_proxy.strip()
        if configured and configured.lower() not in {"auto", "direct"}:
            return configured
        if configured.lower() == "direct":
            return "direct"
        env = os.environ
        candidates = (
            ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
            if target_scheme == "https"
            else ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
        )
        return next((env[key].strip() for key in candidates if env.get(key, "").strip()), "direct")

    def _ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context(cafile=self.config.ca_bundle or None)
        return context

    async def _relay(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        remote_reader: asyncio.StreamReader,
        remote_writer: asyncio.StreamWriter,
    ) -> None:
        async def copy(source: asyncio.StreamReader, target: asyncio.StreamWriter) -> None:
            while True:
                data = await asyncio.wait_for(source.read(64 * 1024), self.config.idle_timeout)
                if not data:
                    break
                target.write(data)
                await target.drain()

        try:
            await asyncio.gather(copy(client_reader, remote_writer), copy(remote_reader, client_writer))
        finally:
            remote_writer.close()
            with contextlib.suppress(Exception):
                await remote_writer.wait_closed()

    @staticmethod
    async def _respond(writer: asyncio.StreamWriter, status: int, message: str) -> None:
        body = message.encode("utf-8")
        writer.write(
            (
                f"HTTP/1.1 {status} Error\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode()
            + body
        )
        await writer.drain()

    @staticmethod
    async def _respond_error(writer: asyncio.StreamWriter, error: NetworkPolicyError) -> None:
        body = json.dumps(
            {
                "error_code": error.error_code,
                "message": str(error),
                "retryable": error.retryable,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        writer.write(
            (
                f"HTTP/1.1 {error.status} Error\r\n"
                "Content-Type: application/json; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode()
            + body
        )
        await writer.drain()


@dataclass(frozen=True)
class _ProcessResult:
    returncode: int
    stdout: str
    stderr: str


async def _docker(*args: str) -> _ProcessResult:
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError:
        return _ProcessResult(127, "", "未找到 docker")
    stdout, stderr = await process.communicate()
    return _ProcessResult(
        process.returncode or 0,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


def _docker_available() -> bool:
    from shutil import which

    return which("docker") is not None


def _process_error(prefix: str, result: _ProcessResult) -> str:
    detail = (result.stderr or result.stdout).strip()
    return f"{prefix}：{detail or f'docker exit {result.returncode}'}"


def _split_authority(value: str, default_port: int) -> tuple[str, int]:
    parsed = urlsplit(f"//{value}")
    if not parsed.hostname:
        raise NetworkPolicyError("CONNECT 目标无效", error_code="invalid_proxy_request", status=400)
    return parsed.hostname, parsed.port or default_port


def _proxy_scheme(value: str) -> str:
    return urlsplit(value).scheme.lower()


def _domain_allowed(host: str, allow: tuple[str, ...], deny: tuple[str, ...]) -> bool:
    if any(_domain_matches(host, pattern) for pattern in deny):
        return False
    return any(_domain_matches(host, pattern) for pattern in allow)


def _domain_matches(host: str, pattern: str) -> bool:
    value = pattern.strip().lower().rstrip(".")
    if value == "*":
        return True
    if value.startswith("**."):
        suffix = value[3:]
        return host == suffix or host.endswith(f".{suffix}")
    if value.startswith("*."):
        suffix = value[2:]
        return host != suffix and host.endswith(f".{suffix}")
    return fnmatch.fnmatchcase(host, value)


def _is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return address.is_global and not address.is_multicast


def _matches_no_proxy(host: str, port: int) -> bool:
    raw = os.getenv("NO_PROXY") or os.getenv("no_proxy") or ""
    normalized = host.lower().rstrip(".")
    for item in raw.split(","):
        value = item.strip().lower()
        if not value:
            continue
        if value == "*":
            return True
        candidate, _, port_text = value.rpartition(":")
        if candidate and port_text.isdigit():
            if int(port_text) != port:
                continue
            value = candidate
        value = value.lstrip(".")
        if normalized == value or normalized.endswith(f".{value}"):
            return True
    return False
