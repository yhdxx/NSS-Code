from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event

from mycodingagent.app import cleanup_worker
from mycodingagent.app.shutdown import (
    close_local_resources,
    close_with_network_dependency,
    spawn_runtime_cleanup,
    spawn_stale_runtime_cleanup,
)
from mycodingagent.async_utils import run_daemon_thread


def test_local_resources_close_concurrently():
    async def scenario():
        started = 0
        both_started = asyncio.Event()
        release = asyncio.Event()

        async def close_one():
            nonlocal started
            started += 1
            if started == 2:
                both_started.set()
            await release.wait()

        async def release_when_ready():
            await asyncio.wait_for(both_started.wait(), timeout=0.2)
            release.set()

        controller = asyncio.create_task(release_when_ready())
        errors = await close_local_resources(
            [("one", close_one()), ("two", close_one())],
            timeout=0.5,
        )
        await controller
        return started, errors

    started, errors = asyncio.run(scenario())

    assert started == 2
    assert errors == []


def test_local_resource_timeout_cancels_waiter():
    async def scenario():
        cancelled = asyncio.Event()

        async def never_closes():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        errors = await close_local_resources([("stuck", never_closes())], timeout=0.01)
        return cancelled.is_set(), errors

    cancelled, errors = asyncio.run(scenario())

    assert cancelled is True
    assert errors == ["stuck: close timeout"]


def test_network_waits_for_mcp_but_not_independent_resources():
    async def scenario():
        events: list[str] = []
        caller_task = asyncio.current_task()
        mcp_task = None
        mcp_started = asyncio.Event()
        model_started = asyncio.Event()
        release_mcp = asyncio.Event()
        release_model = asyncio.Event()
        network_started = asyncio.Event()

        async def close_mcp():
            nonlocal mcp_task
            mcp_task = asyncio.current_task()
            events.append("mcp:start")
            mcp_started.set()
            await release_mcp.wait()
            events.append("mcp:end")

        async def close_model():
            events.append("model:start")
            model_started.set()
            await release_model.wait()
            events.append("model:end")

        async def close_network():
            events.append("network:start")
            network_started.set()
            await asyncio.sleep(0)
            events.append("network:end")

        async def release_dependencies():
            await asyncio.wait_for(mcp_started.wait(), timeout=0.2)
            await asyncio.wait_for(model_started.wait(), timeout=0.2)
            release_mcp.set()
            await asyncio.wait_for(network_started.wait(), timeout=0.2)
            assert "model:end" not in events
            release_model.set()

        releaser = asyncio.create_task(release_dependencies())
        errors = await close_with_network_dependency(
            mcp_close=close_mcp(),
            independent_resources=[("model", close_model())],
            network_resources=[("network", close_network())],
        )
        await releaser
        return events, errors, caller_task, mcp_task

    events, errors, caller_task, mcp_task = asyncio.run(scenario())

    assert mcp_task is caller_task
    assert set(events[:2]) == {"mcp:start", "model:start"}
    assert events.index("network:start") > events.index("mcp:end")
    assert events.index("network:start") < events.index("model:end")
    assert errors == []


def test_runtime_cleanup_is_detached_and_scoped(monkeypatch, tmp_path):
    captured = {}

    def popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("mycodingagent.app.shutdown.subprocess.Popen", popen)

    started = spawn_runtime_cleanup(
        runtime_id="runtime-123",
        network_name="network-123",
        workspace_root=tmp_path,
    )

    assert started is True
    assert "runtime-123" in captured["command"]
    assert "network-123" in captured["command"]
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["stdin"] is not None


def test_cleanup_worker_filters_current_runtime_only(monkeypatch, tmp_path):
    commands: list[list[str]] = []

    def run(command, _env):
        commands.append(command)
        if command[1:3] == ["ps", "-aq"]:
            return cleanup_worker.subprocess.CompletedProcess(command, 0, "container-a\n", "")
        return cleanup_worker.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cleanup_worker, "_run", run)

    cleanup_worker.cleanup_runtime("runtime-a", "network-a", tmp_path / "docker")

    assert "label=com.mycodingagent.runtime=runtime-a" in commands[0]
    assert commands[1] == ["docker", "rm", "-f", "container-a"]
    assert commands[2] == ["docker", "network", "rm", "network-a"]


def test_cleanup_worker_removes_only_stale_runtimes_for_current_workspace(monkeypatch, tmp_path):
    commands: list[list[str]] = []

    def run(command, _env):
        commands.append(command)
        if command[1:3] == ["network", "ls"]:
            return cleanup_worker.subprocess.CompletedProcess(command, 0, "network-a\n", "")
        if command[1:3] == ["network", "inspect"]:
            return cleanup_worker.subprocess.CompletedProcess(command, 0, "runtime-old\n", "")
        if command[1:3] == ["ps", "-aq"]:
            return cleanup_worker.subprocess.CompletedProcess(command, 0, "container-a\n", "")
        return cleanup_worker.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cleanup_worker, "_run", run)

    cleanup_worker.cleanup_stale_workspace_runtimes(tmp_path, tmp_path / "docker")

    assert "label=com.mycodingagent.kind=managed-network" in commands[0]
    assert "label=com.mycodingagent.workspace=" in " ".join(commands[0])
    assert "label=com.mycodingagent.runtime=runtime-old" in commands[2]
    assert commands[3] == ["docker", "rm", "-f", "container-a"]
    assert commands[4] == ["docker", "network", "rm", "network-a"]
    assert "label=com.mycodingagent.kind=workspace-runtime" in commands[5]
    assert commands[-1] == ["docker", "rm", "-f", "container-a"]


def test_stale_cleanup_excludes_current_runtime_ids(monkeypatch, tmp_path):
    commands: list[list[str]] = []

    def run(command, _env):
        commands.append(command)
        if command[1:3] == ["network", "ls"]:
            return cleanup_worker.subprocess.CompletedProcess(command, 0, "network-current\n", "")
        if command[1:3] == ["network", "inspect"]:
            return cleanup_worker.subprocess.CompletedProcess(command, 0, "runtime-current\n", "")
        if command[1:3] == ["ps", "-aq"]:
            return cleanup_worker.subprocess.CompletedProcess(command, 0, "container-current\n", "")
        if command[1] == "inspect":
            return cleanup_worker.subprocess.CompletedProcess(command, 0, "runtime-current\n", "")
        return cleanup_worker.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cleanup_worker, "_run", run)

    cleanup_worker.cleanup_stale_workspace_runtimes(
        tmp_path,
        tmp_path / "docker",
        excluded_runtime_ids={"runtime-current"},
    )

    assert not any(command[1:3] == ["rm", "-f"] for command in commands)


def test_stale_runtime_cleanup_is_detached(monkeypatch, tmp_path):
    captured = {}

    def popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("mycodingagent.app.shutdown.subprocess.Popen", popen)

    started = spawn_stale_runtime_cleanup(
        workspace_root=tmp_path,
        excluded_runtime_ids=("network-current", "workspace-current"),
    )

    assert started is True
    assert "--stale-workspace" in captured["command"]
    assert str(tmp_path) in captured["command"]
    assert captured["command"].count("--exclude-runtime") == 2
    assert captured["kwargs"]["start_new_session"] is True


def test_cancelled_daemon_work_does_not_hold_asyncio_shutdown():
    started = Event()
    release = Event()

    def blocking_work():
        started.set()
        release.wait(timeout=1)

    async def scenario():
        task = asyncio.create_task(run_daemon_thread(blocking_work))
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
    release.set()
