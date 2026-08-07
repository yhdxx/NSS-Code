from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Awaitable


LOCAL_CLOSE_TIMEOUT_SECONDS = 2.0


def spawn_runtime_cleanup(
    *,
    runtime_id: str,
    network_name: str,
    workspace_root: Path,
) -> bool:
    worker = Path(__file__).with_name("cleanup_worker.py")
    try:
        subprocess.Popen(
            [
                sys.executable,
                str(worker),
                "--runtime-id",
                runtime_id,
                "--network-name",
                network_name,
                "--docker-config",
                str(workspace_root / ".docker-cli"),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        return False
    return True


def spawn_stale_runtime_cleanup(
    *,
    workspace_root: Path,
    excluded_runtime_ids: tuple[str, ...],
) -> bool:
    worker = Path(__file__).with_name("cleanup_worker.py")
    docker_config = workspace_root / ".docker-cli"
    try:
        command = [
            sys.executable,
            str(worker),
            "--stale-workspace",
            str(workspace_root),
            "--docker-config",
            str(docker_config),
        ]
        for runtime_id in excluded_runtime_ids:
            command.extend(["--exclude-runtime", runtime_id])
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        return False
    return True


async def close_local_resources(
    resources: list[tuple[str, Awaitable[Any]]],
    *,
    timeout: float = LOCAL_CLOSE_TIMEOUT_SECONDS,
) -> list[str]:
    tasks = {asyncio.ensure_future(awaitable): name for name, awaitable in resources}
    if not tasks:
        return []
    done, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout))
    errors: list[str] = []
    for task in done:
        with contextlib.suppress(asyncio.CancelledError):
            error = task.exception()
            if error is not None:
                errors.append(f"{tasks[task]}: {type(error).__name__}: {error}")
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
        errors.extend(f"{tasks[task]}: close timeout" for task in pending)
    return errors


async def close_with_network_dependency(
    *,
    mcp_close: Awaitable[Any] | None,
    independent_resources: list[tuple[str, Awaitable[Any]]],
    network_resources: list[tuple[str, Awaitable[Any]]],
    timeout: float = LOCAL_CLOSE_TIMEOUT_SECONDS,
) -> list[str]:
    """Close only the MCP -> network dependency serially.

    Other local resources do not depend on the proxy and remain concurrent
    throughout shutdown, so they do not add directly to exit latency.
    """
    independent_task = asyncio.create_task(
        close_local_resources(independent_resources, timeout=timeout)
    )
    errors: list[str] = []
    if mcp_close is not None:
        try:
            # MCP's AnyIO stdio contexts must be exited in the same task that
            # entered them. Do not wrap this awaitable in create_task().
            async with asyncio.timeout(timeout):
                await mcp_close
        except asyncio.TimeoutError:
            errors.append("mcp_manager: close timeout")
        except Exception as exc:
            errors.append(f"mcp_manager: {type(exc).__name__}: {exc}")
    network_task = asyncio.create_task(close_local_resources(network_resources, timeout=timeout))
    independent_errors, network_errors = await asyncio.gather(independent_task, network_task)
    errors.extend(independent_errors)
    errors.extend(network_errors)
    return errors
