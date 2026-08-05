from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from mycodingagent.mcp_integration.config import MCPServerConfig
from mycodingagent.mcp_integration.manager import MCPClientManager
from mycodingagent.workspace_runtime import DockerResult, WorkspaceRuntime


def _runtime(tmp_path: Path, suffix: str = "a") -> WorkspaceRuntime:
    network = SimpleNamespace(
        network_name=f"managed-network-{suffix}",
        proxy_environment={
            "HTTP_PROXY": "http://172.30.0.1:3128",
            "HTTPS_PROXY": "http://172.30.0.1:3128",
        },
        bind_local_target=lambda _resolver: None,
    )
    return WorkspaceRuntime(tmp_path, network)


def test_workspace_container_uses_private_network_without_host_port(tmp_path):
    runtime = _runtime(tmp_path)

    args = runtime._container_args()

    assert "-p" not in args
    assert ["--network", runtime.network_name] == args[args.index("--network"):args.index("--network") + 2]
    assert ["--network-alias", "mycodingagent-devserver"] == args[
        args.index("--network-alias"):args.index("--network-alias") + 2
    ]
    assert f"{tmp_path.resolve()}:/workspace:rw" in args
    assert any(value.endswith("=workspace-runtime") for value in args)
    assert "HTTP_PROXY=http://172.30.0.1:3128" in args


def test_bash_exec_reuses_workspace_container(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    calls = 0

    async def ensure_container():
        nonlocal calls
        calls += 1
        return ""

    monkeypatch.setattr(runtime, "ensure_container", ensure_container)

    first, first_error = asyncio.run(runtime.bash_exec_args("npm test", 30))
    second, second_error = asyncio.run(runtime.bash_exec_args("git status", 10))

    assert first_error == second_error == ""
    assert calls == 2
    assert first is not None and first[:3] == ["docker", "exec", runtime.container_name]
    assert first[-1] == "npm test"
    assert second is not None and second[-1] == "git status"


def test_workspace_container_stays_alive_between_bash_calls(tmp_path):
    runtime = _runtime(tmp_path)

    args = runtime._container_args()

    assert args[-3:] == ["bash", "-lc", "exec sleep infinity"]
    assert "--rm" in args


def test_playwright_joins_workspace_network():
    manager = MCPClientManager(playwright_network="mycodingagent-workspace-test")
    args = manager._sandboxed_stdio_args(
        MCPServerConfig(name="playwright", sandbox=True, image="playwright", network=True)
    )

    assert args[args.index("--network") + 1] == "mycodingagent-workspace-test"


def test_each_runtime_has_an_isolated_playwright_output_directory(tmp_path):
    first = _runtime(tmp_path, "a")
    second = _runtime(tmp_path, "b")

    assert first.playwright_output_dir != second.playwright_output_dir
    assert first.container_name != second.container_name
    assert first.network_name != second.network_name
    assert first.playwright_output_dir.is_relative_to(tmp_path)
    assert second.playwright_output_dir.is_relative_to(tmp_path)


def test_each_runtime_has_an_isolated_persistent_service_directory(tmp_path):
    first = _runtime(tmp_path, "a")
    second = _runtime(tmp_path, "b")

    assert first.persistent_output_dir != second.persistent_output_dir
    assert first.persistent_output_dir.is_relative_to(tmp_path)
    assert second.persistent_output_dir.is_relative_to(tmp_path)


def test_start_persistent_command_returns_workspace_log_and_tracks_pid(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    docker_calls: list[tuple[str, ...]] = []

    async def ensure_container():
        return ""

    async def docker(*args: str):
        docker_calls.append(args)
        return DockerResult(0, "4321", "")

    monkeypatch.setattr(runtime, "ensure_container", ensure_container)
    monkeypatch.setattr(runtime, "_docker", docker)

    started, error = asyncio.run(runtime.start_persistent_command("npm run dev"))

    assert error == ""
    assert started is not None
    assert started.pid == 4321
    assert started.log_path.is_relative_to(Path(".mycodingagent/artifacts/services"))
    assert started.log_path.name == f"{started.service_id}.log"
    assert runtime._persistent_services == {started.service_id: 4321}
    assert docker_calls[0][:3] == ("exec", runtime.container_name, "bash")
    assert docker_calls[0][-1] == "npm run dev"


def test_persistent_command_start_failure_returns_log_tail(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)

    async def ensure_container():
        return ""

    async def docker(*_args: str):
        return DockerResult(1, "", "持久命令在启动确认期间退出。\nmissing script: dev")

    monkeypatch.setattr(runtime, "ensure_container", ensure_container)
    monkeypatch.setattr(runtime, "_docker", docker)

    started, error = asyncio.run(runtime.start_persistent_command("npm run dev"))

    assert started is None
    assert "missing script: dev" in error
    assert runtime._persistent_services == {}


def test_close_stops_persistent_services_before_removing_container(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    runtime._persistent_services = {"server": 4321}
    events: list[str] = []

    async def running():
        return True

    async def docker(*args: str):
        events.append("docker:" + " ".join(args[:2]))
        return DockerResult(0, "", "")

    async def remove_containers():
        events.append("remove-containers")

    monkeypatch.setattr(runtime, "_is_running", running)
    monkeypatch.setattr(runtime, "_docker", docker)
    monkeypatch.setattr(runtime, "_remove_labeled_containers", remove_containers)

    asyncio.run(runtime.close())

    assert events[0] == f"docker:exec {runtime.container_name}"
    assert events[1] == "remove-containers"
    assert runtime._persistent_services == {}
