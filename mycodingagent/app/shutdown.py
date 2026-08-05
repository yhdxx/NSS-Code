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
