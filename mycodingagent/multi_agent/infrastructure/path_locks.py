from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from mycodingagent.multi_agent.infrastructure.permissions import normalize_workspace_path


class PathLockManager:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, paths: tuple[str, ...]) -> AsyncIterator[None]:
        keys = sorted({str(normalize_workspace_path(path, self.workspace_root)) for path in paths})
        locks = await self._get_locks(keys)
        for lock in locks:
            await lock.acquire()
        try:
            yield
        finally:
            for lock in reversed(locks):
                lock.release()

    async def _get_locks(self, keys: list[str]) -> list[asyncio.Lock]:
        async with self._guard:
            return [self._locks.setdefault(key, asyncio.Lock()) for key in keys]
