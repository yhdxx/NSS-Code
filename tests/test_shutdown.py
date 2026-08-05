from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event

from mycodingagent.app import cleanup_worker
from mycodingagent.app.shutdown import close_local_resources, spawn_runtime_cleanup
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
