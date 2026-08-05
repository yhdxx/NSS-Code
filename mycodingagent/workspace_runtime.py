from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from mycodingagent.configuration import CONFIG
from mycodingagent.managed_network import ManagedNetworkRuntime


MANAGED_LABEL = "com.mycodingagent.managed"
WORKSPACE_LABEL = "com.mycodingagent.workspace"
RUNTIME_KIND_LABEL = "com.mycodingagent.kind"
RUNTIME_ID_LABEL = "com.mycodingagent.runtime"
WORKSPACE_CONTAINER_ALIAS = "mycodingagent-devserver"
ACTIVE_COMMAND_PID_PATH = "/tmp/mycodingagent-active-command.pid"
PLAYWRIGHT_OUTPUT_CONTAINER_PATH = Path("/mycodingagent-output")
PERSISTENT_STARTUP_GRACE_SECONDS = 1


@dataclass(frozen=True)
class DockerResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class PersistentCommandResult:
    service_id: str
    pid: int
    log_path: Path


class WorkspaceRuntime:
    """Own the one Docker container shared by Bash and Playwright for a session."""

    def __init__(self, workspace_root: Path, network_runtime: ManagedNetworkRuntime) -> None:
        self.workspace_root = workspace_root.resolve(strict=False)
        digest = hashlib.sha256(str(self.workspace_root).encode("utf-8")).hexdigest()[:16]
        self.runtime_id = uuid4().hex
        self.workspace_key = digest
        runtime_suffix = self.runtime_id[:12]
        self.network_runtime = network_runtime
        self.network_name = network_runtime.network_name
        self.container_name = f"mycodingagent-workspace-{digest}-{runtime_suffix}"
        self.playwright_output_dir = (
            self.workspace_root
            / ".mycodingagent"
            / "artifacts"
            / "playwright"
            / self.runtime_id
        )
        self.playwright_output_container_path = PLAYWRIGHT_OUTPUT_CONTAINER_PATH
        self.persistent_output_dir = (
            self.workspace_root
            / ".mycodingagent"
            / "artifacts"
            / "services"
            / self.runtime_id
        )
        self._persistent_services: dict[str, int] = {}

    async def initialize(self) -> str:
        """Prepare session artifacts; ManagedNetworkRuntime owns the network."""
        if shutil.which("docker") is None:
            return "未找到 docker，工作区运行容器不可用。"
        self._prepare_playwright_output_dir()
        self.persistent_output_dir.mkdir(parents=True, exist_ok=True)
        await self._remove_labeled_containers()
        result = await self._docker("network", "inspect", self.network_name)
        if result.returncode != 0:
            return _docker_error("托管网络尚未就绪", result)
        self.network_runtime.bind_local_target(self.resolve_local_service)
        return ""

    async def ensure_container(self) -> str:
        """Start the shared container once and reuse it for every Bash call."""
        if await self._is_running():
            return ""
        result = await self._docker(*self._container_args())
        return "" if result.returncode == 0 else _docker_error("启动工作区运行容器失败", result)

    async def bash_exec_args(self, command: str, timeout: int) -> tuple[list[str] | None, str]:
        del timeout
        error = await self.ensure_container()
        if error:
            return None, error
        return (
            [
                "docker",
                "exec",
                self.container_name,
                "bash",
                "-lc",
                (
                    f'active={ACTIVE_COMMAND_PID_PATH}; setsid bash -lc "$1" & pid=$!; '
                    'printf "%s" "$pid" > "$active"; '
                    'wait "$pid"; status=$?; rm -f "$active"; exit "$status"'
                ),
                "mycodingagent-bash",
                command,
            ],
            "",
        )

    async def cancel_active_command(self) -> None:
        if not await self._is_running():
            return
        await self._docker(
            "exec",
            self.container_name,
            "bash",
            "-lc",
            (
                f'active={ACTIVE_COMMAND_PID_PATH}; '
                'if test -s "$active"; then pid=$(cat "$active"); '
                'kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; fi; '
                'rm -f "$active"'
            ),
        )

    async def start_persistent_command(
        self,
        command: str,
    ) -> tuple[PersistentCommandResult | None, str]:
        """Start one session-owned background process and confirm it stays alive briefly."""
        error = await self.ensure_container()
        if error:
            return None, error
        service_id = uuid4().hex[:12]
        relative_log_path = (
            Path(".mycodingagent")
            / "artifacts"
            / "services"
            / self.runtime_id
            / f"{service_id}.log"
        )
        host_log_path = self.workspace_root / relative_log_path
        host_log_path.parent.mkdir(parents=True, exist_ok=True)
        container_log_path = Path(CONFIG.sandbox.docker_workspace_alias) / relative_log_path
        result = await self._docker(
            "exec",
            self.container_name,
            "bash",
            "-lc",
            (
                'log="$1"; command="$2"; '
                'setsid bash -lc "$command" </dev/null >>"$log" 2>&1 & pid=$!; '
                f'sleep {PERSISTENT_STARTUP_GRACE_SECONDS}; '
                'if kill -0 "$pid" 2>/dev/null; then printf "%s" "$pid"; exit 0; fi; '
                'printf "持久命令在启动确认期间退出。\\n" >&2; '
                'tail -n 40 "$log" >&2 2>/dev/null || true; exit 1'
            ),
            "mycodingagent-persistent",
            str(container_log_path),
            command,
        )
        if result.returncode != 0:
            return None, _docker_error("启动持久命令失败", result)
        try:
            pid = int(result.stdout.strip())
        except ValueError:
            return None, "启动持久命令失败：容器未返回有效 PID"
        self._persistent_services[service_id] = pid
        return PersistentCommandResult(service_id, pid, relative_log_path), ""

    async def stop_persistent_commands(self) -> None:
        if not self._persistent_services or not await self._is_running():
            self._persistent_services.clear()
            return
        pids = " ".join(str(pid) for pid in self._persistent_services.values())
        await self._docker(
            "exec",
            self.container_name,
            "bash",
            "-lc",
            (
                'for pid in $1; do '
                'kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; '
                'done; sleep 1; '
                'for pid in $1; do '
                'kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true; '
                'done'
            ),
            "mycodingagent-stop-persistent",
            pids,
        )
        self._persistent_services.clear()

    async def close(self) -> None:
        await self.stop_persistent_commands()
        await self._remove_labeled_containers()
        self.detach()

    def detach(self) -> None:
        self._persistent_services.clear()
        self.network_runtime.bind_local_target(None)

    async def resolve_local_service(self, port: int) -> tuple[str, int] | None:
        """Resolve localhost:<port> to this session's workspace container."""
        if not await self._is_running():
            return None
        result = await self._docker(
            "inspect",
            "--format",
            f"{{{{(index .NetworkSettings.Networks \"{self.network_name}\").IPAddress}}}}",
            self.container_name,
        )
        address = result.stdout.strip()
        return (address, port) if result.returncode == 0 and address else None

    def _container_args(self) -> list[str]:
        docker = CONFIG.docker
        args = [
            "run",
            "-d",
            "--rm",
            "--init",
            "--name",
            self.container_name,
            "--label",
            f"{MANAGED_LABEL}=true",
            "--label",
            f"{WORKSPACE_LABEL}={self.workspace_key}",
            "--label",
            f"{RUNTIME_KIND_LABEL}=workspace-runtime",
            "--label",
            f"{RUNTIME_ID_LABEL}={self.runtime_id}",
            "--network",
            self.network_name,
            "--network-alias",
            WORKSPACE_CONTAINER_ALIAS,
            "--cpus",
            docker.cpus,
            "--memory",
            docker.memory,
            "--pids-limit",
            docker.pids_limit,
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--volume",
            f"{self.workspace_root}:{CONFIG.sandbox.docker_workspace_alias}:rw",
            "--workdir",
            str(CONFIG.sandbox.docker_workspace_alias),
        ]
        for key, value in self.network_runtime.proxy_environment.items():
            args.extend(["--env", f"{key}={value}"])
        args.extend([
            docker.image,
            "bash",
            "-lc",
            "exec sleep infinity",
        ])
        return args

    async def _is_running(self) -> bool:
        result = await self._docker("inspect", "--format", "{{.State.Running}}", self.container_name)
        return result.returncode == 0 and result.stdout.strip() == "true"

    async def _remove_labeled_containers(self) -> None:
        result = await self._docker(
            "ps",
            "-aq",
            "--filter",
            f"label={MANAGED_LABEL}=true",
            "--filter",
            f"label={WORKSPACE_LABEL}={self.workspace_key}",
            "--filter",
            f"label={RUNTIME_KIND_LABEL}=workspace-runtime",
            "--filter",
            f"label={RUNTIME_ID_LABEL}={self.runtime_id}",
        )
        for container_id in result.stdout.split():
            await self._docker("rm", "-f", container_id)

    async def _docker(self, *args: str) -> DockerResult:
        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._docker_env(),
            )
        except FileNotFoundError:
            return DockerResult(127, "", "未找到 docker")
        stdout, stderr = await process.communicate()
        return DockerResult(process.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace"))

    def _docker_env(self) -> dict[str, str]:
        env = os.environ.copy()
        docker_config = self.workspace_root / ".docker-cli"
        docker_config.mkdir(parents=True, exist_ok=True)
        env["DOCKER_CONFIG"] = str(docker_config)
        return env

    def _prepare_playwright_output_dir(self) -> None:
        self.playwright_output_dir.mkdir(parents=True, exist_ok=True)
        # The official Playwright image runs as its image user. Only this
        # runtime-specific directory is writable from that container.
        self.playwright_output_dir.chmod(0o777)


def _docker_error(prefix: str, result: DockerResult) -> str:
    detail = (result.stderr or result.stdout).strip()
    return f"{prefix}：{detail or f'docker exit {result.returncode}'}"
