from __future__ import annotations

import asyncio
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

import httpx

from mycodingagent.configuration.settings import SearchConfig
from mycodingagent.managed_network import ManagedNetworkRuntime


@dataclass(frozen=True)
class SearXNGServiceResult:
    managed: bool
    ready: bool
    started: bool = False
    reason: str = ""
    endpoint: str = ""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class SearXNGServiceRuntime:
    """Own one private SearXNG container for one Agent session."""

    def __init__(
        self,
        config: SearchConfig,
        network_runtime: ManagedNetworkRuntime,
        *,
        workspace_root: Path,
        repo_root: Path | None = None,
        http_client: httpx.AsyncClient | None = None,
        startup_timeout: float = 60.0,
        docker_timeout: float = 120.0,
    ) -> None:
        self.config = config
        self.network_runtime = network_runtime
        self.workspace_root = workspace_root.resolve(strict=False)
        self.repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve(strict=False)
        self.runtime_id = network_runtime.runtime_id
        self.container_name = f"mycodingagent-searxng-{self.runtime_id[:12]}"
        self.state_dir = (
            self.workspace_root / ".mycodingagent" / "state" / "network" / self.runtime_id
        )
        self.settings_path = self.state_dir / "searxng-settings.yml"
        self.settings_template = self.repo_root / "infra" / "searxng" / "settings.yml"
        self.endpoint = config.endpoint.strip()
        self._client = http_client
        self._owns_client = http_client is None
        self.startup_timeout = max(1.0, startup_timeout)
        self.docker_timeout = max(1.0, docker_timeout)
        self._managed = not bool(self.endpoint)

    async def ensure_started(self) -> SearXNGServiceResult:
        if not self.config.enabled:
            return SearXNGServiceResult(False, False, reason="search.enabled=false")
        if not self._managed:
            return SearXNGServiceResult(False, True, endpoint=self.endpoint)
        if not self.settings_template.is_file():
            return SearXNGServiceResult(True, False, reason="安装目录缺少 SearXNG 配置模板")
        try:
            self._write_settings()
        except OSError as exc:
            return SearXNGServiceResult(True, False, reason=f"准备 SearXNG 配置失败：{exc}")
        started = await self._docker(*self._container_args())
        if started.returncode != 0:
            return SearXNGServiceResult(
                True, False, reason=_process_error("启动会话 SearXNG 失败", started)
            )
        address = await self._container_address()
        if not address:
            await self._remove_container()
            return SearXNGServiceResult(True, False, reason="Docker 未返回 SearXNG 会话网络地址")
        self.endpoint = f"http://{address}:8080/search"
        if not await self._wait_until_healthy():
            logs = await self._docker("logs", "--tail", "80", self.container_name)
            await self._remove_container()
            return SearXNGServiceResult(
                True,
                False,
                started=True,
                reason=(
                    f"SearXNG 在 {self.startup_timeout:g} 秒内未就绪"
                    + (f"；最近日志：{_compact(logs.stdout + logs.stderr, 2000)}" if logs else "")
                ),
            )
        return SearXNGServiceResult(True, True, started=True, endpoint=self.endpoint)

    async def close(self) -> None:
        if self._managed:
            await self._remove_container()
        await self.close_client()

    async def close_client(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
        self._client = None

    def _container_args(self) -> list[str]:
        args = [
            "run", "-d", "--init",
            "--name", self.container_name,
            "--label", "com.mycodingagent.managed=true",
            "--label", "com.mycodingagent.kind=searxng",
            "--label", f"com.mycodingagent.runtime={self.runtime_id}",
            "--network", self.network_runtime.network_name,
            "--network-alias", "mycodingagent-searxng",
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--volume", f"{self.settings_path}:/etc/searxng/settings.yml:ro",
        ]
        for key, value in self.network_runtime.proxy_environment.items():
            args.extend(["--env", f"{key}={value}"])
        args.append(self.config.image)
        return args

    def _write_settings(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        content = (
            self.settings_template.read_text(encoding="utf-8")
            .replace("__SEARXNG_SECRET__", secrets.token_hex(32))
            .replace("__RUNTIME_PROXY__", self.network_runtime.proxy_url)
        )
        temporary = self.settings_path.with_suffix(".tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.chmod(0o644)
            temporary.replace(self.settings_path)
        finally:
            temporary.unlink(missing_ok=True)

    async def _container_address(self) -> str:
        result = await self._docker(
            "inspect",
            "--format",
            f"{{{{(index .NetworkSettings.Networks \"{self.network_runtime.network_name}\").IPAddress}}}}",
            self.container_name,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    async def _healthy(self) -> bool:
        if not self.endpoint:
            return False
        try:
            response = await self._http_client().get(self.endpoint.rsplit("/search", 1)[0] + "/", timeout=2.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def _wait_until_healthy(self) -> bool:
        deadline = asyncio.get_running_loop().time() + self.startup_timeout
        while asyncio.get_running_loop().time() < deadline:
            if await self._healthy():
                return True
            await asyncio.sleep(0.5)
        return False

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(trust_env=False)
        return self._client

    async def _remove_container(self) -> None:
        await self._docker("rm", "-f", self.container_name)

    async def _docker(self, *args: str) -> ProcessResult:
        env = os.environ.copy()
        env["DOCKER_CONFIG"] = str(self.workspace_root / ".docker-cli")
        Path(env["DOCKER_CONFIG"]).mkdir(parents=True, exist_ok=True)
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError:
            return ProcessResult(127, "", "未找到 docker")
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), self.docker_timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return ProcessResult(124, "", f"docker 在 {self.docker_timeout:g} 秒内未完成")
        return ProcessResult(
            process.returncode or 0,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )


def _process_error(prefix: str, result: ProcessResult) -> str:
    detail = _compact((result.stderr or result.stdout).strip(), 2000)
    return f"{prefix}：{detail or f'exit {result.returncode}'}"


def _compact(value: str, limit: int) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else text[-limit:]
