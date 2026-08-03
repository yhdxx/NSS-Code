from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from mycodingagent.code_intelligence.index import LANGUAGE_BY_SUFFIX, SKIP_DIRS, WorkspaceCodeIndex
from mycodingagent.code_intelligence.project_graph import ProjectGraphService
from mycodingagent.work_mode import WorkMode, WorkModeManager


GRAPH_REFRESH_DEBOUNCE_SECONDS = 1.0


@dataclass(frozen=True)
class BootstrapUpdate:
    messages: tuple[dict[str, Any], dict[str, Any]]
    payload: dict[str, Any]
    navigation_hash: str


class ProjectGraphRuntime:
    """Mode-aware async lifecycle for the otherwise synchronous graph service."""

    def __init__(
        self,
        service: ProjectGraphService,
        code_index: WorkspaceCodeIndex,
        work_mode: WorkModeManager,
        *,
        debounce_seconds: float = GRAPH_REFRESH_DEBOUNCE_SECONDS,
    ) -> None:
        self.service = service
        self.code_index = code_index
        self.work_mode = work_mode
        self.workspace_root = service.workspace_root
        self.debounce_seconds = max(0.0, debounce_seconds)
        self._state_lock = RLock()
        self._refresh_lock = asyncio.Lock()
        self._dirty_revision = 1
        self._refreshed_revision = 0
        self._background_task: asyncio.Task[None] | None = None
        self._refreshing = False
        self._loop = asyncio.get_running_loop()
        self._activating = False
        self._deactivating = False
        self._last_error = ""
        self._mode_epoch = 0
        self._bootstrap_event = 0
        self._closed = False

    @property
    def current_mode(self) -> WorkMode:
        return self.work_mode.current

    @property
    def dirty(self) -> bool:
        with self._state_lock:
            return self._dirty_revision > self._refreshed_revision

    @property
    def last_error(self) -> str:
        with self._state_lock:
            return self._last_error

    def mark_dirty(self, path: Path | str, is_delete: bool = False) -> None:
        if self._closed:
            return
        if not self._is_graph_relevant(path):
            return
        self.code_index.mark_dirty(path, is_delete)
        with self._state_lock:
            self._dirty_revision += 1
            should_schedule = (
                self.current_mode is WorkMode.CODE
                and not self._activating
                and not self._deactivating
            )
        if should_schedule:
            self._loop.call_soon_threadsafe(self._schedule_background_refresh)

    async def activate(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        if self.current_mode is WorkMode.CODE and not self.dirty:
            return self.service.status()
        self._activating = True
        self._cancel_background_refresh()
        try:
            status = await self._refresh_until_clean(progress)
        except Exception as exc:
            with self._state_lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
            raise
        else:
            self.work_mode.commit(WorkMode.CODE)
            self._mode_epoch += 1
            return status
        finally:
            self._activating = False

    async def deactivate(self) -> None:
        self._deactivating = True
        try:
            task = self._cancel_background_refresh()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            async with self._refresh_lock:
                self.work_mode.commit(WorkMode.GENERAL)
        finally:
            self._deactivating = False

    async def ensure_fresh(self) -> dict[str, Any]:
        self._require_code_mode()
        task = self._background_task
        if task is not None and not task.done():
            await asyncio.gather(task, return_exceptions=True)
            self._background_task = None
        if self.dirty or not self.service.status().get("available"):
            return await self._refresh_until_clean(None)
        return self.service.status()

    async def architecture(self, module: str = "", *, depth: int = 3, bootstrap: bool = False) -> dict[str, Any]:
        await self.ensure_fresh()
        return await asyncio.to_thread(
            self.service.architecture,
            module,
            depth=depth,
            bootstrap=bootstrap,
        )

    async def dependency_graph(self, module: str) -> dict[str, Any]:
        await self.ensure_fresh()
        return await asyncio.to_thread(self.service.dependency_graph, module)

    async def update_description(self, target: str, description: str, content_hash: str) -> dict[str, Any]:
        await self.ensure_fresh()
        return await asyncio.to_thread(self.service.update_description, target, description, content_hash)

    async def update_descriptions(self, updates: list[dict[str, str]]) -> dict[str, Any]:
        await self.ensure_fresh()
        return await asyncio.to_thread(self.service.update_descriptions, updates)

    def runtime_payload(self) -> dict[str, Any] | None:
        if self.current_mode is not WorkMode.CODE:
            return None
        payload = self.service.status()
        return payload if payload.get("available") else None

    async def prepare_bootstrap(
        self,
        messages: list[dict[str, Any]],
        *,
        force: bool = False,
    ) -> BootstrapUpdate | None:
        await self.ensure_fresh()
        pair = await asyncio.to_thread(self.service.bootstrap_messages)
        if len(pair) != 2:
            return None
        navigation_hash = _bootstrap_hash(pair[-1])
        if not navigation_hash:
            return None
        if not force and navigation_hash == _latest_bootstrap_hash(messages):
            return None

        self._bootstrap_event += 1
        event_id = f"{self._mode_epoch}_{self._bootstrap_event}"
        prepared = copy.deepcopy(pair)
        old_call_id = str(prepared[0]["tool_calls"][0]["id"])
        call_id = f"{old_call_id}_{event_id}"
        prepared[0]["tool_calls"][0]["id"] = call_id
        prepared[1]["tool_call_id"] = call_id
        for message in prepared:
            metadata = message.setdefault("metadata", {})
            metadata["mode_epoch"] = self._mode_epoch
            metadata["bootstrap_event"] = self._bootstrap_event
        payload = _bootstrap_payload(prepared[-1])
        return BootstrapUpdate(
            messages=(prepared[0], prepared[1]),
            payload=payload,
            navigation_hash=navigation_hash,
        )

    async def close(self) -> None:
        self._closed = True
        task = self._cancel_background_refresh()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        async with self._refresh_lock:
            return None

    async def _refresh_until_clean(
        self,
        progress: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        status: dict[str, Any] = self.service.status()
        async with self._refresh_lock:
            while True:
                with self._state_lock:
                    revision = self._dirty_revision
                    self._refreshing = True
                try:
                    status = await asyncio.to_thread(self.service.refresh, progress)
                finally:
                    with self._state_lock:
                        self._refreshing = False
                with self._state_lock:
                    self._refreshed_revision = max(self._refreshed_revision, revision)
                    self._last_error = ""
                    clean = self._dirty_revision <= self._refreshed_revision
                if clean or self._deactivating:
                    return status

    def _schedule_background_refresh(self) -> None:
        if self._closed or self.current_mode is not WorkMode.CODE or self._activating or self._deactivating:
            return
        if self._background_task is not None and not self._background_task.done():
            if self._refreshing:
                return
            self._background_task.cancel()
        self._background_task = asyncio.create_task(self._debounced_refresh())

    async def _debounced_refresh(self) -> None:
        try:
            await asyncio.sleep(self.debounce_seconds)
            if self.current_mode is WorkMode.CODE and not self._deactivating:
                await self._refresh_until_clean(None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            with self._state_lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
        finally:
            if self._background_task is asyncio.current_task():
                self._background_task = None

    def _cancel_background_refresh(self) -> asyncio.Task[None] | None:
        task = self._background_task
        self._background_task = None
        if task is not None and not task.done() and not self._refreshing:
            task.cancel()
        return task

    def _require_code_mode(self) -> None:
        if self.current_mode is not WorkMode.CODE and not self._activating:
            raise RuntimeError("当前 work_mode=general；请先使用 /mode 进入 Code 模式")

    def _is_graph_relevant(self, path: Path | str) -> bool:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        try:
            relative = candidate.resolve(strict=False).relative_to(self.workspace_root)
        except ValueError:
            return False
        if any(part in SKIP_DIRS for part in relative.parts):
            return False
        return relative.as_posix() == ".agentignore" or relative.suffix.lower() in LANGUAGE_BY_SUFFIX


def _bootstrap_payload(message: dict[str, Any]) -> dict[str, Any]:
    if message.get("role") != "tool":
        return {}
    try:
        payload = json.loads(str(message.get("content") or ""))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _bootstrap_hash(message: dict[str, Any]) -> str:
    metadata = message.get("metadata")
    if isinstance(metadata, dict) and metadata.get("project_graph_bootstrap"):
        return str(metadata.get("navigation_hash") or "")
    payload = _bootstrap_payload(message)
    return str(payload.get("navigation_hash") or "") if payload.get("bootstrap") else ""


def _latest_bootstrap_hash(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        value = _bootstrap_hash(message)
        if value:
            return value
    return ""
