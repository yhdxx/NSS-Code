from __future__ import annotations

import asyncio
import contextlib
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4
from contextlib import AsyncExitStack

from mycodingagent.mcp_integration.cache import MCPMetadataCache
from mycodingagent.mcp_integration.config import MCPConfigLoader, MCPServerConfig
from mycodingagent.mcp_integration.discovery_gate import MCPDiscoveryGate
from mycodingagent.mcp_integration.execution import normalize_mcp_result
from mycodingagent.mcp_integration.models import MCPExecutionResult, MCPItemSummary, MCPServerSummary
from mycodingagent.mcp_integration.hooks import MCPServerLaunchHook, MCPServerLaunchRequest
from mycodingagent.configuration import CONFIG
from mycodingagent.network_access import (
    NetworkAccessRuntime,
    is_local_http_url,
    requires_external_network,
)
from mycodingagent.managed_network import ManagedNetworkRuntime


DIRECT_TOOL_ONLY_SERVERS = frozenset({"playwright"})
SESSION_CLOSE_TIMEOUT_SECONDS = 5.0


class MCPClientManager:
    """Own real MCP protocol connections, discovery metadata, and protocol calls."""

    def __init__(
        self,
        *,
        config_loader: MCPConfigLoader | None = None,
        metadata_cache: MCPMetadataCache | None = None,
        launch_hook: MCPServerLaunchHook | None = None,
        network_access: NetworkAccessRuntime | None = None,
        network_runtime: ManagedNetworkRuntime | None = None,
        playwright_network: str = "",
        playwright_output_dir: Path | None = None,
        playwright_output_container_path: str = "/mycodingagent-output",
        workspace_root: Path | None = None,
    ) -> None:
        self.config_loader = config_loader or MCPConfigLoader()
        self.metadata_cache = metadata_cache or MCPMetadataCache()
        self.launch_hook = launch_hook
        self.network_access = network_access or NetworkAccessRuntime()
        self.network_runtime = network_runtime
        self.playwright_network = playwright_network
        self.playwright_output_dir = (
            playwright_output_dir.resolve(strict=False) if playwright_output_dir is not None else None
        )
        self.playwright_output_container_path = playwright_output_container_path
        self.workspace_root = (workspace_root or CONFIG.sandbox.root).expanduser().resolve(strict=False)
        self.discovery_gate = MCPDiscoveryGate()
        self.server_configs: dict[str, MCPServerConfig] = {}
        self._sessions: dict[str, Any] = {}
        self._session_contexts: dict[str, Any] = {}
        self._reconnect_task: asyncio.Task | None = None
        self._states: dict[str, str] = {}
        self._failures: dict[str, int] = {}
        self._next_retry_at: dict[str, float] = {}
        self._closing = False
        self._close_lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._closing = False
        self.reload_config()

    def reload_config(self) -> None:
        self.server_configs = self.config_loader.load()
        self.metadata_cache.sync_configs(self.server_configs)
        self.discovery_gate.clear()
        self._states = {name: self._states.get(name, "configured") for name in self.server_configs}

    async def close(self) -> None:
        if self._closing and not self._sessions and (
            self._reconnect_task is None or self._reconnect_task.done()
        ):
            return
        self._closing = True
        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
        # MCP stdio sessions use AnyIO cancel scopes whose exits must remain
        # ordered within the task that entered them.
        for server in list(self._sessions):
            await self._close_session(server)

    async def apply_network_policy(self) -> None:
        for server in list(self._sessions):
            config = self.server_configs.get(server)
            if config is not None and not self.network_access.allows_mcp(config):
                await self._close_session(server)

    def server_count(self) -> int:
        return len(self.list_servers())

    def connected_count(self) -> int:
        return self.available_count()

    def available_count(self) -> int:
        return sum(1 for server in self.list_servers() if server.available)

    def list_servers(self) -> list[MCPServerSummary]:
        return [
            summary
            for summary in self.metadata_cache.servers()
            if not self.is_direct_tool_server(summary.name)
        ]

    def network_servers(self) -> list[str]:
        return sorted(
            name
            for name, config in self.server_configs.items()
            if requires_external_network(config)
        )

    def network_permission(self, server: str) -> bool:
        config = self.server_configs.get(server)
        return bool(config is not None and self.network_access.allows_mcp(config))

    def set_network_permission(self, server: str, enabled: bool) -> bool:
        config = self.server_configs.get(server)
        if config is None or not requires_external_network(config):
            return False
        self.network_access.set_mcp_enabled(server, enabled)
        return True

    @staticmethod
    def is_direct_tool_server(server: str) -> bool:
        return server in DIRECT_TOOL_ONLY_SERVERS

    async def refresh_server(self, server: str) -> MCPServerSummary | None:
        if server not in self.server_configs:
            return None
        self.discovery_gate.invalidate_server(server)
        try:
            self._states[server] = "connecting"
            await self._ensure_session(server)
            tools = await self._list_tools_from_session(server)
            resources = await self._list_resources_from_session(server)
            prompts = await self._list_prompts_from_session(server)
            self.metadata_cache.update_discovery(
                server,
                tools=tools,
                resources=resources,
                prompts=prompts,
                connected=True,
                error="",
            )
            self._states[server] = "ready"
            self._failures[server] = 0
            self._next_retry_at.pop(server, None)
        except Exception as exc:
            await self._mark_server_unavailable(server, self._error_message(server, exc))
        entry = self.metadata_cache.get(server)
        return entry.summary() if entry is not None else None

    async def list_tools(self, server: str) -> dict[str, Any]:
        if self.is_direct_tool_server(server):
            return {"error": "Playwright 工具已直接注册为本地 Tool，不支持 MCP discovery。", "tools": []}
        summary = await self._ensure_discovered(server)
        entry = self.metadata_cache.get(server)
        if summary is None or entry is None:
            return {"error": f"未找到 MCP Server：{server}", "tools": []}
        if not summary.available and summary.error:
            return {"error": f"MCP Server 不可用：{summary.error}", "server": summary.to_payload(), "tools": []}
        return {"server": summary.to_payload(), "tools": [item.to_payload() for item in entry.tools]}

    async def list_resources(self, server: str) -> dict[str, Any]:
        summary = await self._ensure_discovered(server)
        entry = self.metadata_cache.get(server)
        if summary is None or entry is None:
            return {"error": f"未找到 MCP Server：{server}", "resources": []}
        if not summary.available and summary.error:
            return {"error": f"MCP Server 不可用：{summary.error}", "server": summary.to_payload(), "resources": []}
        return {"server": summary.to_payload(), "resources": [item.to_payload() for item in entry.resources]}

    async def list_prompts(self, server: str) -> dict[str, Any]:
        summary = await self._ensure_discovered(server)
        entry = self.metadata_cache.get(server)
        if summary is None or entry is None:
            return {"error": f"未找到 MCP Server：{server}", "prompts": []}
        if not summary.available and summary.error:
            return {"error": f"MCP Server 不可用：{summary.error}", "server": summary.to_payload(), "prompts": []}
        return {"server": summary.to_payload(), "prompts": [item.to_payload() for item in entry.prompts]}

    async def call_tool(self, server: str, tool: str, arguments: dict[str, Any] | None = None) -> MCPExecutionResult:
        if server not in self.server_configs:
            return MCPExecutionResult(server=server, operation="tool", name=tool, is_error=True, content_text=f"未找到 MCP Server：{server}", content_type="error")
        unavailable = self._unavailable_result(server, operation="tool", name=tool)
        if unavailable is not None:
            return unavailable
        call_arguments = dict(arguments or {})
        if server == "playwright":
            if tool == "browser_take_screenshot" and not str(call_arguments.get("filename") or "").strip():
                extension = "jpg" if call_arguments.get("type") == "jpeg" else "png"
                call_arguments["filename"] = f"screens/screenshot-{uuid4().hex}.{extension}"
            output_error = _validate_playwright_output_arguments(call_arguments)
            if output_error:
                return MCPExecutionResult(
                    server=server,
                    operation="tool",
                    name=tool,
                    is_error=True,
                    content_text=output_error,
                    content_type="error",
                )
            self._prepare_playwright_output_parents(call_arguments)
        before_outputs = self._playwright_output_snapshot() if server == "playwright" else {}
        try:
            session = await self._ensure_session(server)
            result = await asyncio.wait_for(
                session.call_tool(tool, call_arguments),
                timeout=self.server_configs[server].call_timeout,
            )
        except Exception as exc:
            message = self._error_message(server, exc)
            if not _is_mcp_operation_error(exc):
                await self._mark_server_unavailable(server, message)
            return MCPExecutionResult(server=server, operation="tool", name=tool, is_error=True, content_text=f"MCP 工具调用失败：{message}", content_type="error")
        normalized = self._normalize_result(
            server=server,
            operation="tool",
            name=tool,
            result=result,
        )
        if server == "playwright":
            normalized = self._attach_playwright_outputs(normalized, before_outputs)
        return normalized

    async def read_resource(self, server: str, uri: str) -> MCPExecutionResult:
        if server not in self.server_configs:
            return MCPExecutionResult(server=server, operation="resource", name=uri, is_error=True, content_text=f"未找到 MCP Server：{server}", content_type="error")
        unavailable = self._unavailable_result(server, operation="resource", name=uri)
        if unavailable is not None:
            return unavailable
        try:
            session = await self._ensure_session(server)
            result = await asyncio.wait_for(
                session.read_resource(uri), timeout=self.server_configs[server].call_timeout
            )
        except Exception as exc:
            message = self._error_message(server, exc)
            if not _is_mcp_operation_error(exc):
                await self._mark_server_unavailable(server, message)
            return MCPExecutionResult(server=server, operation="resource", name=uri, is_error=True, content_text=f"MCP 资源读取失败：{message}", content_type="error")
        return self._normalize_result(server=server, operation="resource", name=uri, result=result)

    async def get_prompt(self, server: str, prompt: str, arguments: dict[str, Any] | None = None) -> MCPExecutionResult:
        if server not in self.server_configs:
            return MCPExecutionResult(server=server, operation="prompt", name=prompt, is_error=True, content_text=f"未找到 MCP Server：{server}", content_type="error")
        unavailable = self._unavailable_result(server, operation="prompt", name=prompt)
        if unavailable is not None:
            return unavailable
        try:
            session = await self._ensure_session(server)
            result = await asyncio.wait_for(
                session.get_prompt(prompt, arguments or {}),
                timeout=self.server_configs[server].call_timeout,
            )
        except Exception as exc:
            message = self._error_message(server, exc)
            if not _is_mcp_operation_error(exc):
                await self._mark_server_unavailable(server, message)
            return MCPExecutionResult(server=server, operation="prompt", name=prompt, is_error=True, content_text=f"获取 MCP Prompt 失败：{message}", content_type="error")
        return self._normalize_result(server=server, operation="prompt", name=prompt, result=result)

    def _normalize_result(self, *, server: str, operation: str, name: str, result: Any) -> MCPExecutionResult:
        artifact_root = self.workspace_root / ".mycodingagent" / "artifacts" / "mcp"
        if server == "playwright" and self.playwright_output_dir is not None:
            artifact_root = self.playwright_output_dir
        return normalize_mcp_result(
            server=server,
            operation=operation,
            name=name,
            result=result,
            artifact_root=artifact_root,
            workspace_root=self.workspace_root,
        )

    def unavailable_servers(self) -> list[str]:
        return self.metadata_cache.unavailable_servers()

    def _error_message(self, server: str, exc: Exception) -> str:
        message = str(exc)
        config = self.server_configs.get(server)
        if config is None:
            return message
        for secret in self.config_loader.secret_values(config):
            message = message.replace(secret, "[REDACTED]")
        return message

    def schedule_reconnect_unavailable_servers(self) -> asyncio.Task | None:
        if self._closing:
            return None
        if not self.unavailable_servers():
            return None
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return self._reconnect_task
        self._reconnect_task = asyncio.create_task(self.reconnect_unavailable_servers())
        return self._reconnect_task

    async def reconnect_unavailable_servers(self) -> list[MCPServerSummary]:
        restored: list[MCPServerSummary] = []
        for server in self.unavailable_servers():
            if self._closing:
                break
            if time.monotonic() < self._next_retry_at.get(server, 0.0):
                continue
            summary = await self.refresh_server(server)
            if summary is not None and summary.available:
                restored.append(summary)
        return restored

    async def _ensure_discovered(self, server: str) -> MCPServerSummary | None:
        entry = self.metadata_cache.get(server)
        if entry is None:
            return None
        if entry.updated_at > 0 and not entry.error:
            return entry.summary()
        return await self.refresh_server(server)

    async def _ensure_session(self, server: str) -> Any:
        if self._closing:
            raise RuntimeError("MCP Manager 正在关闭，拒绝新的 MCP 调用")
        existing = self._sessions.get(server)
        if existing is not None:
            return existing
        config = self.server_configs[server]
        sandboxed_network_stdio = (
            config.transport == "stdio" and config.sandbox and config.network
        )
        if not self.network_access.allows_mcp(config) and not sandboxed_network_stdio:
            raise PermissionError(f"网络访问已关闭，禁止连接外网 MCP Server：{server}")
        if config.transport == "stdio" and config.network and not config.sandbox:
            raise PermissionError(
                f"联网 stdio MCP Server 必须启用 sandbox，避免绕过 Runtime 网络策略：{server}"
            )
        if config.network and self.network_runtime is None:
            raise RuntimeError(f"联网 MCP Server 缺少 Runtime 托管网络：{server}")
        if self.launch_hook is not None and not config.auto_start:
            target = config.url if config.transport == "streamable_http" else (config.image or config.command)
            decision = await self.launch_hook.approve(
                MCPServerLaunchRequest(
                    server=server,
                    transport=config.transport,
                    target=target,
                    sandboxed=config.sandbox,
                    workspace_access=config.workspace_access,
                    network=config.network,
                )
            )
            if not decision.allowed:
                raise PermissionError(f"MCP Server 启动被拒绝：{server}")
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamable_http_client
            import httpx
        except Exception as exc:
            raise RuntimeError("执行真实 MCP discovery 需要安装 Python 包 'mcp'") from exc

        stack = AsyncExitStack()
        try:
            if config.transport == "streamable_http":
                if self.network_runtime is None and not is_local_http_url(config.url):
                    raise RuntimeError("远程 MCP 缺少 Runtime 托管网络")
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers=self.config_loader.resolve_headers(config),
                        timeout=config.call_timeout,
                        trust_env=False,
                        proxy=(
                            self.network_runtime.proxy_url_for_mcp(server)
                            if self.network_runtime and not is_local_http_url(config.url)
                            else None
                        ),
                    )
                )
                read_stream, write_stream, _ = await stack.enter_async_context(
                    streamable_http_client(config.url, http_client=http_client)
                )
            else:
                env = os.environ.copy()
                for key, value in self.config_loader.resolve_env(config).items():
                    if value:
                        env[key] = value
                env.setdefault("npm_config_cache", "/tmp/mycodingagent-npm-cache")
                if config.network and self.network_runtime is not None:
                    env.update(self.network_runtime.proxy_environment_for_mcp(server))
                if config.sandbox:
                    docker_args = self._sandboxed_stdio_args(config)
                    params = StdioServerParameters(command="docker", args=docker_args, env=env)
                else:
                    params = StdioServerParameters(command=config.command, args=list(config.args), env=env)
                read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await asyncio.wait_for(session.initialize(), timeout=config.startup_timeout)
            self._session_contexts[server] = stack
            self._sessions[server] = session
            return session
        except Exception:
            with contextlib.suppress(Exception):
                await stack.aclose()
            raise

    async def _close_session(self, server: str) -> None:
        async with self._close_lock:
            self._sessions.pop(server, None)
            contexts = self._session_contexts.pop(server, None)
            if contexts is None:
                return
            try:
                # AsyncExitStack owns AnyIO cancel scopes created while the
                # session was opened. Keep its exit in this task rather than
                # moving it into a detached asyncio.Task.
                async with asyncio.timeout(SESSION_CLOSE_TIMEOUT_SECONDS):
                    await contexts.aclose()
            except asyncio.TimeoutError:
                return
            except asyncio.CancelledError:
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelling():
                    raise
                # A stdio MCP may cancel its AnyIO task group as it exits. It
                # is expected during shutdown and must not escape to Python's
                # interpreter-finalization path.
                return
            except BaseException:
                return

    def _sandboxed_stdio_args(self, config: MCPServerConfig) -> list[str]:
        network_name = (
            self.network_runtime.network_name
            if config.network and self.network_runtime is not None
            else self.playwright_network
            if config.name == "playwright" and self.playwright_network
            else "none"
        )
        args = [
            "run", "--rm", "-i",
            "--network", network_name,
            "--cpus", config.cpus or CONFIG.docker.cpus,
            "--memory", config.memory or CONFIG.docker.memory,
            "--pids-limit", config.pids_limit or CONFIG.docker.pids_limit,
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
        ]
        if self.network_runtime is not None:
            args.extend(
                [
                    "--label", "com.mycodingagent.managed=true",
                    "--label", f"com.mycodingagent.runtime={self.network_runtime.runtime_id}",
                    "--label", "com.mycodingagent.kind=mcp-runtime",
                ]
            )
        if config.init:
            args.append("--init")
        if config.shm_size:
            args.extend(["--shm-size", config.shm_size])
        if config.container_user == "host":
            args.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
        elif config.container_user != "image":
            args.extend(["--user", config.container_user])
        for host in config.extra_hosts:
            args.extend(["--add-host", host])
        if config.name == "playwright" and self.playwright_output_dir is not None:
            self.playwright_output_dir.mkdir(parents=True, exist_ok=True)
            args.extend(
                [
                    "--volume",
                    f"{self.playwright_output_dir}:{self.playwright_output_container_path}:rw",
                    "--workdir",
                    self.playwright_output_container_path,
                ]
            )
        if config.workspace_access != "none":
            mode = "rw" if config.workspace_access == "write" else "ro"
            args.extend(
                [
                    "--volume",
                    f"{CONFIG.sandbox.root.resolve(strict=False)}:{CONFIG.sandbox.docker_workspace_alias}:{mode}",
                    "--workdir",
                    str(CONFIG.sandbox.docker_workspace_alias),
                ]
            )
        for key in config.env:
            args.extend(["--env", key])
        if config.network and self.network_runtime is not None:
            for key, value in self.network_runtime.proxy_environment_for_mcp(config.name).items():
                args.extend(["--env", f"{key}={value}"])
        args.append(config.image or CONFIG.docker.image)
        if not config.image_entrypoint:
            args.append(config.command)
        args.extend(config.args)
        if config.name == "playwright" and self.playwright_output_dir is not None:
            args.extend(["--output-dir", self.playwright_output_container_path])
        if config.name == "playwright" and self.network_runtime is not None:
            args.extend(
                [
                    "--proxy-server",
                    self.network_runtime.proxy_url_for_mcp(config.name),
                    "--proxy-bypass",
                    "<-loopback>,mycodingagent-devserver",
                ]
            )
        return args

    def _playwright_output_snapshot(self) -> dict[Path, tuple[int, int]]:
        root = self.playwright_output_dir
        if root is None:
            return {}
        snapshot: dict[Path, tuple[int, int]] = {}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
                snapshot[path] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
        return snapshot

    def _prepare_playwright_output_parents(self, arguments: dict[str, Any]) -> None:
        root = self.playwright_output_dir
        if root is None:
            return
        for key in ("filename", "outputPath", "output_path"):
            raw = arguments.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            target = root / Path(raw)
            target.parent.mkdir(parents=True, exist_ok=True)

    def _attach_playwright_outputs(
        self,
        result: MCPExecutionResult,
        before: dict[Path, tuple[int, int]],
    ) -> MCPExecutionResult:
        root = self.playwright_output_dir
        if root is None:
            return result
        outputs: list[dict[str, Any]] = []
        for path, fingerprint in self._playwright_output_snapshot().items():
            if before.get(path) == fingerprint:
                continue
            try:
                relative_to_output = path.resolve(strict=True).relative_to(root)
                workspace_path = path.resolve(strict=True).relative_to(self.workspace_root)
            except (OSError, ValueError):
                continue
            outputs.append(
                {
                    "path": workspace_path.as_posix(),
                    "output_path": relative_to_output.as_posix(),
                    "size": fingerprint[1],
                }
            )
        if not outputs:
            return result
        outputs.sort(key=lambda item: item["path"])
        metadata = dict(result.metadata)
        metadata["runtime_outputs"] = outputs
        lines = ["Runtime 已将本次输出保存到工作区："]
        lines.extend(f"[workspace output] {item['path']}" for item in outputs)
        if result.content_text:
            lines.extend(["", result.content_text])
        return MCPExecutionResult(
            server=result.server,
            operation=result.operation,
            name=result.name,
            is_error=result.is_error,
            content_text="\n".join(lines),
            content_type="mixed" if result.content_text else "metadata",
            metadata=metadata,
        )

    async def _mark_server_unavailable(self, server: str, error: str) -> None:
        await self._close_session(server)
        self.metadata_cache.mark_error(server, error)
        failures = self._failures.get(server, 0) + 1
        self._failures[server] = failures
        self._next_retry_at[server] = time.monotonic() + min(60.0, float(2 ** min(failures, 6)))
        self._states[server] = "backoff"

    async def live_tool_metadata(self, server: str, tool: str) -> dict[str, Any]:
        if server not in self.server_configs:
            return {}
        tools = await self._list_tools_from_session(server)
        entry = self.metadata_cache.get(server)
        self.metadata_cache.update_discovery(server, tools=tools, connected=True, error="")
        item = next((candidate for candidate in tools if candidate.name == tool), None)
        return dict(item.metadata) if item is not None else {}

    def cached_tool_payload(self, server: str, tool: str) -> dict[str, Any] | None:
        entry = self.metadata_cache.get(server)
        if entry is None:
            return None
        item = next((candidate for candidate in entry.tools if candidate.name == tool), None)
        return item.to_payload() if item is not None else None

    def cached_tools(self, server: str) -> list[MCPItemSummary]:
        """Return the last discovered tool metadata for a configured server."""
        entry = self.metadata_cache.get(server)
        return list(entry.tools) if entry is not None else []

    def _unavailable_result(self, server: str, *, operation: str, name: str) -> MCPExecutionResult | None:
        entry = self.metadata_cache.get(server)
        if entry is None or entry.available:
            return None
        error = entry.error or "Server 已标记为不可用"
        return MCPExecutionResult(
            server=server,
            operation=operation,
            name=name,
            is_error=True,
            content_text=f"MCP Server 不可用：{error}",
            content_type="error",
        )

    async def _list_tools_from_session(self, server: str) -> list[MCPItemSummary]:
        session = await self._ensure_session(server)
        result = await asyncio.wait_for(
            session.list_tools(), timeout=self.server_configs[server].call_timeout
        )
        return [_item_summary(item) for item in getattr(result, "tools", [])]

    async def _list_resources_from_session(self, server: str) -> list[MCPItemSummary]:
        session = await self._ensure_session(server)
        with contextlib.suppress(Exception):
            result = await asyncio.wait_for(
                session.list_resources(), timeout=self.server_configs[server].call_timeout
            )
            return [_item_summary(item) for item in getattr(result, "resources", [])]
        return []

    async def _list_prompts_from_session(self, server: str) -> list[MCPItemSummary]:
        session = await self._ensure_session(server)
        with contextlib.suppress(Exception):
            result = await asyncio.wait_for(
                session.list_prompts(), timeout=self.server_configs[server].call_timeout
            )
            return [_item_summary(item) for item in getattr(result, "prompts", [])]
        return []


def _item_summary(item: Any) -> MCPItemSummary:
    uri = str(getattr(item, "uri", "") or "")
    raw_name = str(getattr(item, "name", "") or "")
    name = uri or raw_name
    description = str(getattr(item, "description", "") or "")
    metadata: dict[str, Any] = {}
    if raw_name and raw_name != name:
        metadata["name"] = raw_name
    for key in ("uri", "mimeType", "title", "inputSchema", "outputSchema", "annotations"):
        value = getattr(item, key, None)
        if value:
            if hasattr(value, "model_dump"):
                value = value.model_dump(by_alias=True, exclude_none=True)
            metadata[key] = value if isinstance(value, (dict, list, bool, int, float)) else str(value)
    return MCPItemSummary(name=name, description=description, metadata=metadata)


def _is_mcp_operation_error(exc: Exception) -> bool:
    """Return True for server-side operation errors that should not poison the connection."""
    exc_type = type(exc)
    return exc_type.__name__ == "McpError" and exc_type.__module__ == "mcp.shared.exceptions"


def _validate_playwright_output_arguments(arguments: dict[str, Any]) -> str:
    """Keep every user-selected Playwright output inside its mounted output root."""
    for key in ("filename", "path", "outputPath", "output_path"):
        raw = arguments.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        candidate = Path(raw)
        if candidate.is_absolute() or ".." in candidate.parts:
            return f"Playwright 输出路径必须是工作区 Runtime 输出目录内的相对路径：{raw}"
    return ""
