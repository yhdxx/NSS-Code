from __future__ import annotations

import asyncio
from threading import Thread
from typing import Any, Callable


async def run_daemon_thread(function: Callable[..., Any], *args: Any) -> Any:
    """Run blocking cleanup/background work without joining it at asyncio shutdown."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()

    def run() -> None:
        try:
            result = function(*args)
        except BaseException as exc:
            _notify(loop, future, None, exc)
        else:
            _notify(loop, future, result, None)

    Thread(target=run, name="mycodingagent-background", daemon=True).start()
    return await future


def _notify(
    loop: asyncio.AbstractEventLoop,
    future: asyncio.Future[Any],
    result: Any,
    error: BaseException | None,
) -> None:
    if loop.is_closed():
        return
    try:
        loop.call_soon_threadsafe(_complete, future, result, error)
    except RuntimeError:
        return


def _complete(
    future: asyncio.Future[Any],
    result: Any,
    error: BaseException | None,
) -> None:
    if future.done():
        return
    if error is not None:
        future.set_exception(error)
    else:
        future.set_result(result)
