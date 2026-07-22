from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import json
import re
import sys
import threading
from dataclasses import asdict, dataclass
from enum import Enum
from time import time
from typing import Any, Callable
from uuid import uuid4

from mycodingagent.configuration import CONFIG
from mycodingagent.memory.budget import PromptBudgetManager, PromptBudgetSnapshot, estimate_tokens
from mycodingagent.memory.checkpoint import CheckpointManager, RolloverResult, TurnState
from mycodingagent.memory.compressor import ContextCompressor, ToolOutputRef, is_reproducible_tool
from mycodingagent.memory.context_objects import RecoverableContextObject, build_recoverable_context
from mycodingagent.memory.context_epoch import (
    ContextEpochManager,
    automatic_context_epoch_summary,
    collect_context_epoch_files,
    format_context_epoch_commit_report,
    format_hot_context_notice,
    last_user_message_index,
    retained_hot_start_index,
)
from mycodingagent.memory.models import (
    CompressionResult,
    ContextEpochState,
    ContextEpochStatus,
    ConversationSnapshot,
    HistoricalTurn,
    HotContextBudgetSnapshot,
    MemoryEntry,
    MemoryQuery,
    MemoryScope,
    SessionListItem,
    SessionState,
    TokenUsageRecord,
    TokenUsageSummary,
    ToolInvocationMetadata,
    ToolOutputRecord,
)
from mycodingagent.memory.stores import SQLiteMemoryStore
from mycodingagent.memory.working_context import WorkingContext
from mycodingagent.workspace.identity import workspace_fingerprint, workspace_label, workspace_root_text


@dataclass
class MemoryWriteTask:
    description: str
    callback: Callable[[], None]


class ContextMode(str, Enum):
    RAW = "raw"
    VIRTUALIZED = "virtualized"


@dataclass(frozen=True)
class ContextRenderDecision:
    mode: ContextMode
    raw_tokens: int
    raw_uncached_tokens: int
    virtualized_tokens: int
    usage_ratio: float
    switched: bool = False


class MemoryRuntime:
    def __init__(
        self,
        *,
        store: SQLiteMemoryStore | None = None,
        compressor: ContextCompressor | None = None,
        model: str | None = None,
        workspace_root: str | None = None,
    ) -> None:
        self.model = model or CONFIG.api.model
        context_window = (
            compressor.context_window
            if compressor is not None
            else CONFIG.memory.context_window_for(self.model)
        )
        self.store = store or SQLiteMemoryStore(CONFIG.memory.db_path)
        self.compressor = compressor or ContextCompressor(context_window=context_window)
        self.budget_manager = PromptBudgetManager(
            context_window=context_window,
            soft_ratio=CONFIG.memory.budget_soft_ratio,
            working_ratio=CONFIG.memory.budget_working_ratio,
            emergency_ratio=CONFIG.memory.budget_emergency_ratio,
            reserved_reasoning_tokens=CONFIG.memory.reserved_reasoning_tokens,
            reserved_output_tokens=CONFIG.memory.reserved_output_tokens,
            reserved_tool_tokens=CONFIG.memory.reserved_tool_tokens,
        )
        self.working_context = WorkingContext()
        self.workspace_root = workspace_root_text(workspace_root or CONFIG.sandbox.root)
        self.workspace_label = workspace_label(self.workspace_root)
        self.workspace_fingerprint = workspace_fingerprint(self.workspace_root)
        self.checkpoint_manager = CheckpointManager(
            memory_runtime=self,
            prompt_budget_manager=self.budget_manager,
        )
        self.current_session_id: str | None = None
        self.latest_snapshot_id: str = ""
        self._tool_output_refs: dict[str, ToolOutputRef] = {}
        self._context_metadata_refs: dict[str, RecoverableContextObject] = {}
        self._context_modes: dict[str, ContextMode] = {}
        self.context_epoch_manager = ContextEpochManager(
            store=self.store,
            context_window=context_window,
            warning_ratio=CONFIG.memory.hot_context_warning_ratio,
            force_ratio=CONFIG.memory.hot_context_force_ratio,
        )
        self._last_raw_rendered_messages: dict[str, list[dict[str, Any]]] = {}
        self._message_versions: dict[str, int] = {}
        self._message_write_lock = threading.Lock()
        self._write_queue: asyncio.Queue | None = None
        self._worker_task: asyncio.Task | None = None
        self._writer_errors: list[str] = []
        self._pending_rollover_task: asyncio.Task | None = None
        self._current_turn_summaries: dict[str, dict[str, Any]] = {}
        self._current_turn_summary_calls: int = 0
        self._closed = False
        self.start_async_writer()

    def start_async_writer(self) -> None:
        if self._worker_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._write_queue = asyncio.Queue()
        self._worker_task = loop.create_task(self._run_writer())

    async def _run_writer(self) -> None:
        if self._write_queue is None:
            return
        loop = asyncio.get_running_loop()
        while True:
            task = await self._write_queue.get()
            try:
                await loop.run_in_executor(None, task.callback)
            except Exception as exc:  # pragma: no cover - defensive logging path
                self._record_writer_error(task.description, exc)
            finally:
                self._write_queue.task_done()

    async def drain(self) -> None:
        if self._write_queue is not None:
            await self._write_queue.join()

    async def close(self) -> None:
        self._closed = True
        await self.await_pending_rollover()
        await self.drain()
        if self._worker_task is not None:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
        self._worker_task = None
        self._write_queue = None
        if self._writer_errors:
            print(f"记忆模块后台写入失败 {len(self._writer_errors)} 次。", file=sys.stderr, flush=True)

    def _enqueue_write(self, description: str, callback: Callable[[], None]) -> None:
        task = MemoryWriteTask(description=description, callback=callback)
        if self._write_queue is not None and self._worker_task is not None and not self._closed:
            self._write_queue.put_nowait(task)
            return
        try:
            task.callback()
        except Exception as exc:  # pragma: no cover - defensive logging path
            self._record_writer_error(description, exc)

    def _record_writer_error(self, description: str, exc: Exception) -> None:
        self._writer_errors.append(f"{description}: {exc}")
        print(f"记忆模块后台写入失败：{description}: {exc}", file=sys.stderr, flush=True)

    def start_session(self, model: str | None = None) -> str:
        self._current_turn_summaries.clear()
        self._current_turn_summary_calls = 0
        if self.current_session_id is None:
            self.current_session_id = uuid4().hex
        session_id = self.current_session_id
        model_name = model or self.model
        self._enqueue_write(
            "ensure_session",
            lambda: self.store.ensure_session(
                session_id=session_id,
                model=model_name,
                workspace_root=self.workspace_root,
                workspace_label=self.workspace_label,
                workspace_fingerprint=self.workspace_fingerprint,
            ),
        )
        return self.current_session_id

    def get_current_session_id(self) -> str | None:
        return self.current_session_id

    def clear_current_session_id(self) -> None:
        self.current_session_id = None
        self._current_turn_summaries.clear()
        self._current_turn_summary_calls = 0

    def get_active_context_epoch(self, session_id: str | None = None) -> ContextEpochState | None:
        key = session_id or self.current_session_id or ""
        return self.context_epoch_manager.get(key) if key else None

    def ensure_context_epoch(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        current_turn_start: int | None = None,
    ) -> ContextEpochState:
        return self.context_epoch_manager.ensure(
            session_id=session_id,
            messages=messages,
            current_turn_start=current_turn_start,
        )

    def request_context_epoch_commit(
        self,
        *,
        reason: str,
        summary: str,
        retain_context_ids: list[str] | None = None,
        active_files: list[str] | None = None,
        next_context_hint: str = "",
        trigger: str = "model",
        session_id: str | None = None,
        next_start_message_index: int | None = None,
    ) -> ContextEpochState:
        target_session_id = session_id or self.current_session_id or ""
        if not target_session_id:
            raise ValueError("no active memory session")
        return self.context_epoch_manager.request_commit(
            session_id=target_session_id,
            reason=reason,
            summary=summary,
            retain_context_ids=retain_context_ids,
            active_files=active_files,
            next_context_hint=next_context_hint,
            trigger=trigger,
            next_start_message_index=next_start_message_index,
        )

    def finalize_pending_context_epoch(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> ContextEpochState | None:
        result = self.context_epoch_manager.finalize(
            session_id=session_id,
            end_message_index=len(messages),
            pending_tool_call=has_pending_tool_call(messages),
        )
        if result is None:
            return None
        committed, next_state = result
        self.force_context_virtualized(session_id)
        self._current_turn_summaries.clear()
        self._current_turn_summary_calls = 0
        if CONFIG.memory.output_context_compression:
            print(format_context_epoch_commit_report(committed, next_state), flush=True)
        return next_state

    def hot_context_budget_snapshot(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        current_turn_start: int | None = None,
    ) -> HotContextBudgetSnapshot:
        return self.context_epoch_manager.snapshot(
            session_id=session_id,
            messages=messages,
            current_turn_start=current_turn_start,
        )

    def cold_context_budget_snapshot(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> PromptBudgetSnapshot:
        transition_epoch = self.latest_committed_context_epoch(session_id)
        if transition_epoch is None:
            return self.prompt_budget_snapshot([])
        epoch = self.ensure_context_epoch(
            session_id=session_id,
            messages=messages,
            current_turn_start=len(messages),
        )
        historical_messages, _current_messages = split_historical_and_current(
            messages,
            epoch.start_message_index,
        )
        if not historical_messages:
            return self.prompt_budget_snapshot([])
        historical_turns = self.store.load_historical_turns(session_id) or build_historical_turns(
            session_id,
            historical_messages,
        )
        rendered = render_virtualized_messages(
            system_messages=[message for message in historical_messages if message.get("role") == "system"][:1],
            historical_messages=historical_messages,
            session_id=session_id,
            historical_turns=historical_turns,
            current_messages=[],
            current_summaries={},
            transition_epoch=transition_epoch,
        )
        return self.prompt_budget_snapshot(rendered)

    def latest_committed_context_epoch(self, session_id: str) -> ContextEpochState | None:
        committed = [
            epoch
            for epoch in self.store.load_context_epochs(session_id)
            if epoch.status == ContextEpochStatus.COMMITTED and epoch.end_message_index is not None
        ]
        return committed[-1] if committed else None

    def _maybe_rotate_context_epoch(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        current_turn_start: int | None,
        epoch: ContextEpochState,
    ) -> ContextEpochState:
        can_finalize_now = can_finalize_context_rotation(messages, current_turn_start)
        if epoch.status == ContextEpochStatus.PENDING_COMMIT:
            if can_finalize_now:
                return self.finalize_pending_context_epoch(session_id=session_id, messages=messages) or epoch
            return epoch
        if epoch.status != ContextEpochStatus.ACTIVE:
            return epoch

        hot_snapshot = self.hot_context_budget_snapshot(
            session_id=session_id,
            messages=messages,
            current_turn_start=current_turn_start,
        )
        if not hot_snapshot.force_commit or hot_snapshot.pending_commit:
            return epoch

        retained_turns = max(1, CONFIG.memory.hot_context_retained_turns)
        tail_start = retained_hot_start_index(
            messages,
            start_message_index=epoch.start_message_index,
            retained_turns=retained_turns,
        )
        next_start = tail_start if tail_start > epoch.start_message_index else None
        pending = self.request_context_epoch_commit(
            reason="hot working context reached the forced commit threshold",
            summary=automatic_context_epoch_summary(messages, epoch.start_message_index, next_start),
            active_files=collect_context_epoch_files(messages, epoch.start_message_index, next_start),
            next_context_hint=(
                f"Runtime retained the latest {retained_turns} user turns as hot context."
                if next_start is not None
                else ""
            ),
            trigger="runtime",
            session_id=session_id,
            next_start_message_index=next_start,
        )
        if can_finalize_now:
            return self.finalize_pending_context_epoch(session_id=session_id, messages=messages) or pending
        return pending

    def context_mode(self, session_id: str | None = None) -> ContextMode:
        key = session_id or self.current_session_id or ""
        if not key:
            return ContextMode.RAW
        return self._context_modes.get(key, ContextMode.RAW)

    def is_context_virtualized(self, session_id: str | None = None) -> bool:
        return self.context_mode(session_id) == ContextMode.VIRTUALIZED

    def force_context_virtualized(self, session_id: str | None = None) -> None:
        key = session_id or self.current_session_id or ""
        if key:
            self._context_modes[key] = ContextMode.VIRTUALIZED

    def save_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        snapshot = copy.deepcopy(messages)
        historical_turns = build_historical_turns(session_id, snapshot)
        version = self._next_message_version(session_id)
        self._enqueue_write(
            "save_messages",
            lambda: self._save_messages_if_current(session_id, snapshot, historical_turns, version),
        )

    def save_messages_now(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        snapshot = copy.deepcopy(messages)
        historical_turns = build_historical_turns(session_id, snapshot)
        self._next_message_version(session_id)
        with self._message_write_lock:
            self.store.ensure_session(
                session_id=session_id,
                model=self.model,
                workspace_root=self.workspace_root,
                workspace_label=self.workspace_label,
                workspace_fingerprint=self.workspace_fingerprint,
            )
            self.store.save_messages(session_id=session_id, messages=snapshot)
            self.store.save_historical_turns(session_id=session_id, turns=historical_turns)

    def _next_message_version(self, session_id: str) -> int:
        version = self._message_versions.get(session_id, 0) + 1
        self._message_versions[session_id] = version
        return version

    def _save_messages_if_current(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        historical_turns: list[HistoricalTurn],
        version: int,
    ) -> None:
        with self._message_write_lock:
            if self._message_versions.get(session_id) != version:
                return
            self.store.save_messages(session_id=session_id, messages=messages)
            self.store.save_historical_turns(session_id=session_id, turns=historical_turns)

    def load_session(self, session_id: str) -> SessionState | None:
        state = self.store.load_session(session_id)
        if state is not None:
            self.store.touch_session(session_id)
            self.current_session_id = session_id
            epoch = state.context_epoch or self.ensure_context_epoch(
                session_id=session_id,
                messages=state.messages,
            )
            self.context_epoch_manager.remember(epoch)
            if self.store.has_committed_context_epoch(session_id):
                self.force_context_virtualized(session_id)
            if epoch.status == ContextEpochStatus.PENDING_COMMIT and not has_pending_tool_call(state.messages):
                epoch = self.finalize_pending_context_epoch(session_id=session_id, messages=state.messages) or epoch
            state.context_epoch = epoch
        return state

    def record_token_usage(
        self,
        *,
        session_id: str,
        prompt_tokens: int,
        prompt_cache_hit_tokens: int,
        prompt_cache_miss_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        model: str = "",
        prompt_hash: str = "",
        tools_hash: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TokenUsageSummary:
        model_name = model or self.model
        self.store.ensure_session(
            session_id=session_id,
            model=model_name,
            workspace_root=self.workspace_root,
            workspace_label=self.workspace_label,
            workspace_fingerprint=self.workspace_fingerprint,
        )
        record = TokenUsageRecord(
            usage_id=uuid4().hex,
            session_id=session_id,
            request_index=self.store.next_token_usage_request_index(session_id),
            prompt_tokens=prompt_tokens,
            prompt_cache_hit_tokens=prompt_cache_hit_tokens,
            prompt_cache_miss_tokens=prompt_cache_miss_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model=model_name,
            prompt_hash=prompt_hash,
            tools_hash=tools_hash,
            metadata=metadata or {},
            created_at=time(),
        )
        self.store.save_token_usage(record)
        return self.store.load_token_usage_summary(session_id)

    def load_token_usage_summary(self, session_id: str) -> TokenUsageSummary:
        return self.store.load_token_usage_summary(session_id)

    def fork_session(
        self,
        source_session_id: str,
        *,
        model: str | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> str | None:
        source_state = self.store.load_session(source_session_id)
        if source_state is None:
            return None

        fork_session_id = uuid4().hex
        self.current_session_id = fork_session_id
        model_name = model or self.model
        fork_messages = copy.deepcopy(messages if messages is not None else source_state.messages)
        self.store.ensure_session(
            session_id=fork_session_id,
            model=model_name,
            workspace_root=self.workspace_root,
            workspace_label=self.workspace_label,
            workspace_fingerprint=self.workspace_fingerprint,
        )
        self.save_messages_now(fork_session_id, fork_messages)
        source_epoch = source_state.context_epoch
        self.context_epoch_manager.create(
            session_id=fork_session_id,
            start_message_index=(
                min(source_epoch.start_message_index, len(fork_messages))
                if source_epoch is not None
                else (last_user_message_index(fork_messages) or len(fork_messages))
            ),
        )
        if model_name != self.model:
            self.store.ensure_session(
                session_id=fork_session_id,
                model=model_name,
                workspace_root=self.workspace_root,
                workspace_label=self.workspace_label,
                workspace_fingerprint=self.workspace_fingerprint,
            )
        if source_state.latest_lrfu:
            self.store.save_lrfu_snapshot(session_id=fork_session_id, lrfu=copy.deepcopy(source_state.latest_lrfu))
        if source_state.latest_file_state:
            self.store.save_file_state_snapshot(
                session_id=fork_session_id,
                file_state=copy.deepcopy(source_state.latest_file_state),
            )
        return fork_session_id

    def touch_session(self, session_id: str) -> bool:
        return self.store.touch_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        deleted = self.store.delete_session(session_id)
        if deleted and self.current_session_id == session_id:
            self.current_session_id = None
        if deleted:
            self._context_modes.pop(session_id, None)
            self.context_epoch_manager.delete(session_id)
            self._last_raw_rendered_messages.pop(session_id, None)
        return deleted

    def delete_sessions(self, session_ids: list[str]) -> int:
        deleted_count = 0
        for session_id in session_ids:
            if self.delete_session(session_id):
                deleted_count += 1
        return deleted_count

    def cleanup_expired_sessions(self) -> int:
        ttl_days = max(0, CONFIG.memory.session_ttl_days)
        if ttl_days == 0:
            return 0
        return self.store.delete_expired_sessions(max_age_seconds=ttl_days * 24 * 60 * 60)

    def list_sessions(self, *, limit: int = 20, include_all: bool = False) -> list[SessionListItem]:
        if include_all:
            return self.store.list_sessions(limit=limit)
        return self.store.list_sessions(limit=limit, workspace_root=self.workspace_root)

    def list_migrated_workspace_sessions(self, *, limit: int = 20) -> list[SessionListItem]:
        sessions = self.store.list_sessions(limit=limit, workspace_fingerprint=self.workspace_fingerprint)
        return [session for session in sessions if session.workspace_root != self.workspace_root]

    def save_tool_output(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: str,
        output: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        reproducible = is_reproducible_tool(tool_name, output)
        context = build_recoverable_context(
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments_json=arguments,
            content=output,
            reproducible=reproducible,
            token_count=estimate_tokens(output),
            metadata=metadata,
        )
        output_id = context.id
        record = ToolOutputRecord(
            output_id=output_id,
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments_json=arguments,
            output_text=output,
            output_size=len(output),
            reproducible=reproducible,
            created_at=time(),
        )
        self._enqueue_write(
            "save_tool_output",
            lambda: (
                self.store.save_tool_output(record),
                self.store.save_context(context, output),
            ),
        )
        self._tool_output_refs[output_id] = ToolOutputRef(
            output_id=output_id,
            tool_name=tool_name,
            original_length=len(output),
            preview=output[: CONFIG.memory.context_preview_tokens * 4],
            reproducible=reproducible,
        )
        self._context_metadata_refs[output_id] = context
        return output_id

    def get_tool_output(self, output_id: str) -> ToolOutputRecord | None:
        return self.store.get_tool_output(output_id)

    def get_context_metadata(self, context_id: str) -> RecoverableContextObject | None:
        return self._context_metadata_refs.get(context_id) or self.store.query_metadata(context_id)

    def load_context(self, context_id: str) -> str | None:
        return self.store.load_context(context_id)

    def load_partial_context(self, context_id: str, *, offset: int = 0, limit: int = 12000) -> tuple[str, int | None] | None:
        return self.store.load_partial_context(context_id, offset=offset, limit=limit)

    def search_context_metadata(self, session_id: str, query: str = "", *, limit: int = 20) -> list[RecoverableContextObject]:
        stored = self.store.search_metadata(session_id, query, limit=limit)
        seen = {context.id for context in stored}
        in_memory = [
            context
            for context in self._context_metadata_refs.values()
            if context.session_id == session_id and context.id not in seen
        ]
        if query:
            needle = " ".join(query.split()).lower()
            in_memory = [
                context
                for context in in_memory
                if needle in " ".join(
                    [
                        context.tool_name,
                        context.short_summary,
                        " ".join(context.keywords),
                        " ".join(context.entities),
                        " ".join(context.related_files),
                    ]
                ).lower()
            ]
        return [*in_memory, *stored][:limit]

    def prompt_budget_snapshot(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        current_prompt: str = "",
        extra_tokens: int = 0,
    ) -> PromptBudgetSnapshot:
        return self.budget_manager.snapshot(
            messages,
            tools=tools,
            current_prompt=current_prompt,
            extra_tokens=extra_tokens,
        )

    def tool_output_prompt_content(
        self,
        *,
        output_id: str,
        output: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        current_prompt: str = "",
    ) -> str:
        """Return current-turn tool output using raw-mode preview rules."""
        metadata = self.get_context_metadata(output_id)
        if metadata is not None:
            self.working_context.add(metadata)
        if len(output) <= CONFIG.memory.raw_tool_output_preview_chars:
            return output
        return raw_tool_output_preview_text(output_id, output, metadata=metadata)

    def context_reference_text(
        self,
        context_id: str,
        *,
        preview: str = "",
        snapshot: PromptBudgetSnapshot | None = None,
    ) -> str:
        metadata = self.get_context_metadata(context_id)
        if metadata is None:
            ref = self._tool_output_refs.get(context_id)
            if ref is None:
                return (
                    "[Recoverable context stored]\n"
                    f"context_id: {context_id}\n"
                    "recover: Use RecoverContext with this exact context_id and offset/limit."
                )
            return (
                "[Recoverable context stored]\n"
                f"context_id: {ref.output_id}\n"
                f"tool_name: {ref.tool_name}\n"
                f"original_length: {ref.original_length}\n"
                f"preview:\n{preview or ref.preview}\n"
                "recover: Use RecoverContext with this exact context_id and offset/limit."
            )
        budget_text = ("\n" + snapshot.to_prompt_text()) if snapshot is not None else ""
        return (
            "[Recoverable context stored]\n"
            f"context_id: {metadata.id}\n"
            f"tool_name: {metadata.tool_name}\n"
            f"call_summary: {metadata.short_summary}\n"
            f"keywords: {', '.join(metadata.keywords[:12])}\n"
            f"related_files: {', '.join(metadata.related_files[:12])}\n"
            f"content_length: {metadata.content_length}"
            f"{budget_text}\n"
            f"preview:\n{preview}\n"
            "recover: Use RecoverContext with this exact context_id and offset/limit."
        )
    def prepare_messages_for_model(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        current_prompt: str,
        summary_text: str = "",
        persist_snapshot: bool = True,
        current_turn_start: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.render_messages_for_model(
            session_id=session_id,
            messages=messages,
            tools=tools,
            current_prompt=current_prompt,
            current_turn_start=current_turn_start,
            summary_text=summary_text,
            persist_snapshot=persist_snapshot,
        )

    def render_messages_for_model(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        current_prompt: str,
        current_turn_start: int | None,
        summary_text: str = "",
        persist_snapshot: bool = True,
    ) -> list[dict[str, Any]]:
        raw_rendered = sanitize_messages_for_model(messages)
        epoch = self.ensure_context_epoch(
            session_id=session_id,
            messages=messages,
            current_turn_start=current_turn_start,
        )
        epoch = self._maybe_rotate_context_epoch(
            session_id=session_id,
            messages=messages,
            current_turn_start=current_turn_start,
            epoch=epoch,
        )
        historical_messages, current_messages = split_historical_and_current(
            messages,
            epoch.start_message_index,
        )
        historical_turns = self.store.load_historical_turns(session_id) or build_historical_turns(
            session_id,
            historical_messages,
        )
        transition_epoch = self.latest_committed_context_epoch(session_id)
        virtualized_rendered = render_virtualized_messages(
            system_messages=[message for message in historical_messages if message.get("role") == "system"][:1],
            historical_messages=historical_messages,
            session_id=session_id,
            historical_turns=historical_turns,
            transition_epoch=transition_epoch,
            current_messages=current_messages,
            current_summaries=self._current_turn_summaries,
        )
        decision = self._select_context_render(
            session_id=session_id,
            raw_messages=raw_rendered,
            virtualized_messages=virtualized_rendered,
            tools=tools,
            current_prompt=current_prompt,
        )
        rendered = virtualized_rendered if decision.mode == ContextMode.VIRTUALIZED else raw_rendered
        hot_snapshot = self.hot_context_budget_snapshot(
            session_id=session_id,
            messages=messages,
            current_turn_start=current_turn_start,
        )
        if hot_snapshot.warning:
            rendered = insert_budget_notice(rendered, format_hot_context_notice(hot_snapshot))
        snapshot = self.prompt_budget_snapshot(rendered, tools=tools, current_prompt=current_prompt)
        if (
            CONFIG.memory.output_context_compression
            and decision.mode == ContextMode.VIRTUALIZED
            and (decision.switched or snapshot.usage_ratio >= CONFIG.memory.budget_soft_ratio)
        ):
            print(format_virtualization_report(snapshot, decision=decision), flush=True)
        self._last_raw_rendered_messages[session_id] = copy.deepcopy(raw_rendered)
        if not persist_snapshot:
            return sanitize_messages_for_model(rendered)
        snapshot_id = uuid4().hex
        rendered_snapshot = copy.deepcopy(rendered)
        self._enqueue_write(
            "save_context_snapshot",
            lambda: self.store.save_context_snapshot(
                snapshot_id=snapshot_id,
                session_id=session_id,
                compressed_messages=rendered_snapshot,
                summary_text=summary_text,
                pressure_ratio=snapshot.usage_ratio,
            ),
        )
        return sanitize_messages_for_model(rendered)

    def _select_context_render(
        self,
        *,
        session_id: str,
        raw_messages: list[dict[str, Any]],
        virtualized_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        current_prompt: str,
    ) -> ContextRenderDecision:
        raw_snapshot = self.prompt_budget_snapshot(raw_messages, tools=tools, current_prompt=current_prompt)
        virtualized_snapshot = self.prompt_budget_snapshot(
            virtualized_messages,
            tools=tools,
            current_prompt=current_prompt,
        )
        raw_uncached_tokens = estimate_raw_uncached_tokens(
            self._last_raw_rendered_messages.get(session_id),
            raw_messages,
        )
        mode = self.context_mode(session_id)
        switched = False
        if mode == ContextMode.RAW and self._should_switch_to_virtualized(
            raw_snapshot=raw_snapshot,
        ):
            mode = ContextMode.VIRTUALIZED
            switched = True
            self._context_modes[session_id] = mode
        return ContextRenderDecision(
            mode=mode,
            raw_tokens=raw_snapshot.current_tokens,
            raw_uncached_tokens=raw_uncached_tokens,
            virtualized_tokens=virtualized_snapshot.current_tokens,
            usage_ratio=raw_snapshot.usage_ratio,
            switched=switched,
        )

    def _should_switch_to_virtualized(
        self,
        *,
        raw_snapshot: PromptBudgetSnapshot,
    ) -> bool:
        if raw_snapshot.current_tokens >= raw_snapshot.context_window:
            return True
        return raw_snapshot.usage_ratio >= CONFIG.memory.raw_to_virtualized_ratio

    def summarize_current_turn_message(
        self,
        *,
        message_id: str,
        summary: str,
        reason: str,
        focus: str = "",
        context_id: str = "",
    ) -> ToolInvocationMetadata:
        key = context_id or message_id
        if not key:
            raise ValueError("message_id or context_id is required")
        previous = self._current_turn_summaries.get(key)
        if previous is not None and previous.get("summary") == summary and previous.get("focus", "") == focus:
            raise ValueError("duplicate current-turn summary revision")
        if previous is not None and previous.get("revision_count", 1) >= CONFIG.memory.current_turn_summary_max_per_message:
            raise ValueError("current-turn summary revision limit reached for this message")
        if self._current_turn_summary_calls >= CONFIG.memory.current_turn_summary_max_per_turn:
            raise ValueError("current-turn summary call limit reached")
        if previous is not None and not reason.strip():
            raise ValueError("summary revision requires a non-empty reason")

        revision = int(previous.get("revision_count", 0)) + 1 if previous else 1
        payload = {
            "message_id": message_id,
            "context_id": context_id,
            "summary": summary,
            "focus": focus,
            "reason": reason,
            "summary_version": revision,
            "supersedes_version": previous.get("summary_version") if previous else None,
            "revision_count": revision,
        }
        self._current_turn_summaries[key] = payload
        self._current_turn_summary_calls += 1
        return ToolInvocationMetadata(
            metadata_id=stable_id("summary", key, str(revision)),
            session_id=self.current_session_id or "",
            turn_id="current",
            turn_index=-1,
            call_index=self._current_turn_summary_calls - 1,
            tool_call_id=message_id,
            tool_name="SummarizeCurrentTurnMessage",
            kind="current_summary",
            context_id=context_id,
            invocation_kind="revision" if previous else "initial",
            intent=truncate_one_line(summary, 160),
            args_preview=truncate_one_line(json.dumps({"focus": focus, "reason": reason}, ensure_ascii=False), 500),
            args_hash=stable_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            short_summary=truncate_one_line(summary, 500),
            keywords=extract_keywords_from_text(summary)[:12],
            content_type="summary",
            content_length=len(summary),
            token_count=estimate_tokens(summary),
            reproducible=False,
            is_error=False,
        )

    def save_lrfu_snapshot(self, session_id: str, skill_runtime: Any | None) -> None:
        if skill_runtime is None:
            return
        cache = getattr(skill_runtime, "session_skill_cache", None)
        to_dict = getattr(cache, "to_dict", None)
        if callable(to_dict):
            lrfu_snapshot = copy.deepcopy(to_dict())
            self._enqueue_write(
                "save_lrfu_snapshot",
                lambda: self.store.save_lrfu_snapshot(session_id=session_id, lrfu=lrfu_snapshot),
            )

    def save_file_state_snapshot(self, session_id: str, file_state_cache: Any | None) -> None:
        if file_state_cache is None:
            return
        to_dict = getattr(file_state_cache, "to_dict", None)
        if not callable(to_dict):
            return
        file_state_snapshot = copy.deepcopy(to_dict())
        self._enqueue_write(
            "save_file_state_snapshot",
            lambda: self.store.save_file_state_snapshot(session_id=session_id, file_state=file_state_snapshot),
        )

    async def on_turn_completed(
        self,
        *,
        messages: list[dict[str, Any]],
        skill_runtime: Any | None = None,
        file_state_cache: Any | None = None,
        workspace_tracker: Any | None = None,
        system_prompt_source: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        current_prompt: str = "",
    ) -> RolloverResult:
        session_id = self.get_current_session_id()
        if not session_id or not messages:
            return RolloverResult()
        await self.drain()
        try:
            self.save_messages_now(session_id, messages)
            self.save_lrfu_snapshot(session_id, skill_runtime)
            self.save_file_state_snapshot(session_id, file_state_cache)
            await self.drain()
            self.finalize_pending_context_epoch(session_id=session_id, messages=messages)
            self.render_messages_for_model(
                session_id=session_id,
                messages=messages,
                tools=tools or [],
                current_prompt=current_prompt,
                current_turn_start=len(messages),
                persist_snapshot=False,
            )
            cold_snapshot = self.cold_context_budget_snapshot(session_id=session_id, messages=messages)
            turn_state = TurnState(
                completed=True,
                pending_tool_call=has_pending_tool_call(messages),
                active_recovery=False,
                retrying_error=False,
                turn_end_index=len(messages),
            )
            if (
                not CONFIG.memory.checkpoint_enabled
                or not turn_state.completed
                or turn_state.pending_tool_call
                or turn_state.active_recovery
                or turn_state.retrying_error
                or self.context_mode(session_id) != ContextMode.VIRTUALIZED
                or cold_snapshot.usage_ratio < CONFIG.memory.archive_cold_context_ratio
            ):
                return RolloverResult()
            if self._pending_rollover_task is not None and not self._pending_rollover_task.done():
                return RolloverResult()
            runtime_state = copy.deepcopy(
                self._checkpoint_runtime_state(
                    skill_runtime=skill_runtime,
                    file_state_cache=file_state_cache,
                    workspace_tracker=workspace_tracker,
                )
            )
            rollover_messages = copy.deepcopy(messages)
            rollover_system_prompt = copy.deepcopy(system_prompt_source)
            self._pending_rollover_task = asyncio.create_task(
                self._perform_rollover(
                    session_id=session_id,
                    messages=rollover_messages,
                    runtime_state=runtime_state,
                    trigger_reason="cold_context_threshold",
                    usage_ratio=cold_snapshot.usage_ratio,
                    system_prompt_source=rollover_system_prompt,
                )
            )
            return RolloverResult()
        except Exception as exc:  # pragma: no cover - lifecycle must not break user turns
            self._record_writer_error("checkpoint_lifecycle", exc)
            return RolloverResult()

    async def _perform_rollover(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        runtime_state: dict[str, Any],
        trigger_reason: str,
        usage_ratio: float,
        system_prompt_source: dict[str, Any] | None,
    ) -> RolloverResult:
        try:
            loop = asyncio.get_running_loop()
            snapshot = await loop.run_in_executor(
                None,
                lambda: self.create_checkpoint(
                    session_id=session_id,
                    messages=messages,
                    runtime_state=runtime_state,
                    trigger_reason=trigger_reason,
                    usage_ratio=usage_ratio,
                ),
            )
            result = await loop.run_in_executor(
                None,
                lambda: self.rollover_to_new_session(
                    session_id=session_id,
                    snapshot=snapshot,
                    system_prompt_source=system_prompt_source,
                ),
            )
            return result
        except Exception as exc:  # pragma: no cover - lifecycle must not break user turns
            self._record_writer_error("async_rollover", exc)
            return RolloverResult()

    def create_checkpoint(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        runtime_state: dict[str, Any],
        trigger_reason: str,
        usage_ratio: float,
    ) -> ConversationSnapshot:
        return self.checkpoint_manager.checkpoint_session(
            session_id=session_id,
            messages=messages,
            runtime_state=runtime_state,
            trigger_reason=trigger_reason,
            usage_ratio=usage_ratio,
        )

    def rollover_to_new_session(
        self,
        *,
        session_id: str,
        snapshot: ConversationSnapshot,
        system_prompt_source: dict[str, Any] | None,
    ) -> RolloverResult:
        return self.checkpoint_manager.rollover_session(
            session_id=session_id,
            snapshot=snapshot,
            system_prompt_source=system_prompt_source,
        )

    def restore_historical_session_snapshot(self, session_id: str) -> ConversationSnapshot | None:
        return self.checkpoint_manager.restore_session_snapshot(session_id)

    async def await_pending_rollover(self) -> RolloverResult:
        task = self._pending_rollover_task
        if task is None:
            return RolloverResult()
        try:
            result = await task
        finally:
            self._pending_rollover_task = None
        return result if isinstance(result, RolloverResult) else RolloverResult()

    def _checkpoint_runtime_state(
        self,
        *,
        skill_runtime: Any | None,
        file_state_cache: Any | None,
        workspace_tracker: Any | None,
    ) -> dict[str, Any]:
        workspace_state = {
            "workspace_root": self.workspace_root,
            "workspace_label": self.workspace_label,
            "workspace_fingerprint": self.workspace_fingerprint,
        }
        file_state = snapshot_dict(file_state_cache)
        if file_state:
            workspace_state["file_state"] = file_state
        return {
            "workspace_state": workspace_state,
            "memory_state": {
                "current_session_id": self.current_session_id,
                "skill_lrfu": snapshot_dict(getattr(skill_runtime, "session_skill_cache", None)),
                "workspace_tracker": snapshot_dict(workspace_tracker),
            },
            "recoverable_context_refs": list(self._context_metadata_refs.keys()),
        }

    def load_lrfu_snapshot(self, session_id: str, skill_runtime: Any | None) -> None:
        if skill_runtime is None:
            return
        state = self.store.load_session(session_id)
        if state is None:
            return
        cache = getattr(skill_runtime, "session_skill_cache", None)
        load_dict = getattr(cache, "load_dict", None)
        if callable(load_dict):
            load_dict(state.latest_lrfu)

    def load_file_state_snapshot(
        self,
        session_id: str,
        file_state_cache: Any | None,
        workspace_tracker: Any | None = None,
    ) -> dict:
        if file_state_cache is None:
            return {}
        state = self.store.load_session(session_id)
        if state is None:
            return {}
        load_dict = getattr(file_state_cache, "load_dict", None)
        if callable(load_dict):
            load_dict(state.latest_file_state)
        mark_paths_for_recheck = getattr(workspace_tracker, "mark_paths_for_recheck", None)
        if callable(mark_paths_for_recheck):
            mark_paths_for_recheck(file_state_paths(state.latest_file_state))
        return state.latest_file_state

    def save_short_term(self, content: str, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        entry = MemoryEntry(content=content, scope=MemoryScope.SHORT_TERM, metadata=metadata or {})
        session_id = self.start_session()
        memory_message = {"role": "memory", "content": json.dumps(entry.__dict__, ensure_ascii=False, default=str)}

        def write_short_term() -> None:
            messages = self.store.load_messages(session_id)
            messages.append(memory_message)
            self.store.save_messages(session_id=session_id, messages=messages)

        self._enqueue_write("save_short_term", write_short_term)
        return entry

    def save_long_term(self, content: str, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        return MemoryEntry(content=content, scope=MemoryScope.LONG_TERM, metadata=metadata or {})

    def recall_short_term(self, query: MemoryQuery | None = None) -> list[MemoryEntry]:
        return []

    def recall_long_term(self, query: MemoryQuery | None = None) -> list[MemoryEntry]:
        return []

    def compress_context(self, messages: list[dict[str, Any]]) -> CompressionResult:
        return self.compressor.compress_messages(messages)

    def should_compress_context(self, messages: list[dict[str, Any]]) -> bool:
        return self.compressor.should_compress(messages)


def raw_tool_output_preview_text(
    output_id: str,
    output: str,
    *,
    metadata: RecoverableContextObject | None = None,
) -> str:
    preview_chars = max(2, CONFIG.memory.raw_tool_output_preview_chars)
    edge_chars = max(1, preview_chars // 2)
    head = output[:edge_chars]
    tail = output[-edge_chars:] if edge_chars < len(output) else ""
    omitted_chars = max(0, len(output) - len(head) - len(tail))
    tool_name = metadata.tool_name if metadata is not None else ""
    preview = (
        head
        + f"\n[... {omitted_chars} chars omitted; full output stored as recoverable context ...]\n"
        + tail
    )
    return (
        "[Tool output preview]\n"
        f"context_id: {output_id}\n"
        f"tool_name: {tool_name}\n"
        f"content_length: {len(output)}\n"
        f"omitted_chars: {omitted_chars}\n"
        "recover: Use RecoverContext with this exact context_id and offset/limit for non-preview content.\n"
        f"preview:\n{preview}"
    )


def format_compression_report(result: CompressionResult) -> str:
    metadata = result.metadata
    current_size = int(metadata.get("current_size", 0))
    context_window = int(metadata.get("context_window", 0))
    compressed_size = int(metadata.get("compressed_size", 0))
    pressure = float(metadata.get("pressure_ratio", 0.0))
    action = metadata.get("action", "unknown")
    return (
        "[CONTEXT COMPRESSION]\n"
        f"  current_context_size: {current_size}\n"
        f"  context_window: {context_window}\n"
        f"  window_usage: {pressure:.2%}\n"
        f"  action: {action}\n"
        f"  compressed_context_size: {compressed_size}"
    )


def format_virtualization_report(
    snapshot: PromptBudgetSnapshot,
    *,
    decision: ContextRenderDecision | None = None,
) -> str:
    title = "[CONTEXT MODE SWITCH]" if decision is not None and decision.switched else "[CONTEXT VIRTUALIZATION]"
    lines = [
        title,
        f"  current_context_tokens: {snapshot.current_tokens}",
        f"  context_window: {snapshot.context_window}",
        f"  window_usage: {snapshot.usage_ratio:.2%}",
        f"  stage: {snapshot.stage.value}",
        f"  usable_tokens: {snapshot.usable_tokens}",
    ]
    if decision is not None:
        lines.extend(
            [
                f"  mode: {decision.mode.value}",
                *(
                    ["  mode_transition: raw -> virtualized"]
                    if decision.switched and decision.mode == ContextMode.VIRTUALIZED
                    else []
                ),
                f"  raw_context_tokens: {decision.raw_tokens}",
                f"  raw_uncached_tokens: {decision.raw_uncached_tokens}",
                f"  virtualized_context_tokens: {decision.virtualized_tokens}",
                f"  switched: {str(decision.switched).lower()}",
            ]
        )
    return "\n".join(lines)


def estimate_raw_uncached_tokens(
    previous_messages: list[dict[str, Any]] | None,
    current_messages: list[dict[str, Any]],
) -> int:
    if not current_messages:
        return 0
    if not previous_messages:
        return estimate_tokens(current_messages)
    first_changed = min(len(previous_messages), len(current_messages))
    for index, (previous, current) in enumerate(zip(previous_messages, current_messages)):
        if previous != current:
            first_changed = index
            break
    return estimate_tokens(current_messages[first_changed:])


def split_historical_and_current(
    messages: list[dict[str, Any]],
    current_turn_start: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if current_turn_start is None:
        if messages and messages[0].get("role") == "system":
            return messages[:1], messages[1:]
        return [], messages
    start = max(0, min(current_turn_start, len(messages)))
    return messages[:start], messages[start:]


def insert_budget_notice(messages: list[dict[str, Any]], notice: str) -> list[dict[str, Any]]:
    if not notice:
        return messages
    insert_at = 1 if messages and messages[0].get("role") == "system" else 0
    return [*messages[:insert_at], {"role": "system", "content": notice}, *messages[insert_at:]]


def format_budget_notice(snapshot: PromptBudgetSnapshot) -> str:
    lines = [
        "CONTEXT BUDGET NOTICE",
        f"usage_ratio: {snapshot.usage_ratio:.2%}",
        f"stage: {snapshot.stage.value}",
        "Historical tool outputs may be virtualized as metadata. Use RecoverContext only when an exact context_id is visible; otherwise use SearchRecoverableContext first.",
    ]
    if snapshot.usage_ratio >= CONFIG.memory.budget_working_ratio:
        lines.extend(
            [
                "Budget is tight. If a current-turn non-skill tool output is important but low-density, call "
                "SummarizeCurrentTurnMessage with its context_id or tool_call_id.",
                "Revise a current-turn summary only when the prior summary is wrong or important new facts must be added.",
            ]
        )
    if snapshot.usage_ratio >= CONFIG.memory.budget_emergency_ratio:
        lines.append("Emergency budget stage: preserve task state, decisions, pending work, and recoverable references.")
    return "\n".join(lines)


def render_virtualized_messages(
    *,
    system_messages: list[dict[str, Any]],
    historical_messages: list[dict[str, Any]],
    session_id: str,
    historical_turns: list[HistoricalTurn],
    current_messages: list[dict[str, Any]],
    current_summaries: dict[str, dict[str, Any]],
    transition_epoch: ContextEpochState | None = None,
) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    rendered.extend(system_messages[:1])
    rendered.extend(render_historical_topology(session_id, historical_messages, historical_turns))
    if transition_epoch is not None:
        rendered.extend(render_context_transition_marker(transition_epoch))
    rendered.extend(apply_current_summaries(current_messages, current_summaries))
    return rendered


def render_context_transition_marker(epoch: ContextEpochState) -> list[dict[str, Any]]:
    tool_call_id = f"context_epoch_commit_{epoch.epoch_id}"
    transition = {
        "reason": epoch.reason,
        "summary": epoch.summary,
        "trigger": epoch.trigger,
        "cold_message_range": [epoch.start_message_index, epoch.end_message_index],
        "new_hot_start_message_index": epoch.end_message_index,
    }
    if epoch.retain_context_ids:
        transition["retain_context_ids"] = epoch.retain_context_ids
    if epoch.active_files:
        transition["active_files"] = epoch.active_files
    if epoch.next_context_hint:
        transition["next_context_hint"] = epoch.next_context_hint
    result = {
        "status": "committed",
        "epoch_id": epoch.epoch_id,
        **transition,
        "notice": (
            "Previous hot working context is now cold. User and assistant text remain visible; "
            "older tool outputs are represented by recoverable metadata."
        ),
    }
    return [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": "CommitWorkingContext",
                        "arguments": json.dumps(transition, ensure_ascii=False, sort_keys=True),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": "[Working context transition]\n"
            + json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2),
        },
    ]


def render_historical_topology(
    session_id: str,
    messages: list[dict[str, Any]],
    turns: list[HistoricalTurn],
) -> list[dict[str, Any]]:
    if not messages:
        return []
    system_offset = 1 if messages and messages[0].get("role") == "system" else 0
    metadata_by_call_id: dict[str, ToolInvocationMetadata] = {}
    for turn in turns or build_historical_turns(session_id, messages):
        for metadata in turn.tool_metadata:
            metadata_by_call_id[metadata.tool_call_id] = metadata
    rendered: list[dict[str, Any]] = []
    for message in messages[system_offset:]:
        role = message.get("role")
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "")
            metadata = metadata_by_call_id.get(tool_call_id)
            rendered.append(render_historical_tool_message(message, metadata))
            continue
        if role == "assistant" and message.get("tool_calls"):
            rendered.append(render_historical_assistant_message(message))
            continue
        if role in {"user", "assistant"}:
            rendered.append(dict(message))
    return rendered


def render_historical_assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    rendered: dict[str, Any] = {"role": "assistant"}
    if message.get("content"):
        rendered["content"] = message["content"]
    if message.get("tool_calls"):
        rendered["tool_calls"] = copy.deepcopy(message["tool_calls"])
    return rendered


def render_historical_tool_message(
    message: dict[str, Any],
    metadata: ToolInvocationMetadata | None,
) -> dict[str, Any]:
    tool_call_id = str(message.get("tool_call_id") or "")
    rendered = {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": historical_tool_content(metadata, message),
    }
    return rendered


def historical_tool_content(metadata: ToolInvocationMetadata | None, message: dict[str, Any]) -> str:
    raw_metadata = message.get("metadata")
    if isinstance(raw_metadata, dict) and raw_metadata.get("archive_snapshot"):
        return message_content_text(message)
    if metadata is not None and metadata.metadata.get("archive_snapshot"):
        return message_content_text(message)
    if metadata is None:
        return (
            "[Historical tool output virtualized]\n"
            "metadata_unavailable: true\n"
            "recover: Use SearchSessionHistory with query terms from the surrounding user and assistant messages."
        )
    if metadata.kind == "skill":
        payload = {
            "tool_name": metadata.tool_name,
            **tool_summary_prompt_dict(metadata),
            "recover": "Skill output is not recoverable with RecoverContext. Use listed reference_paths when present.",
        }
        if metadata.reference_paths:
            payload["reference_paths"] = metadata.reference_paths[:8]
        return "[Historical skill output omitted]\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return (
        "[Historical tool output virtualized]\n"
        + json.dumps(tool_metadata_prompt_dict(metadata), ensure_ascii=False, sort_keys=True)
    )


def tool_metadata_prompt_dict(metadata: ToolInvocationMetadata) -> dict[str, Any]:
    payload = {
        "tool_name": metadata.tool_name,
        **tool_summary_prompt_dict(metadata),
        "content_length": metadata.content_length,
        "is_error": metadata.is_error,
    }
    if metadata.context_id:
        payload["context_id"] = metadata.context_id
        payload["recover"] = "Use RecoverContext with this exact context_id and offset/limit."
    else:
        payload["recover"] = "Use SearchSessionHistory with query terms from tool_name and call_summary."
    return payload


def tool_summary_prompt_dict(metadata: ToolInvocationMetadata) -> dict[str, Any]:
    summary = metadata.intent or metadata.short_summary
    if metadata.metadata.get("intent_is_explicit"):
        return {"intent": summary}
    return {"call_summary": summary}


def apply_current_summaries(
    messages: list[dict[str, Any]],
    summaries: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not summaries:
        return [dict(message) for message in messages]
    result: list[dict[str, Any]] = []
    for message in messages:
        replacement = None
        metadata = message.get("metadata")
        if isinstance(metadata, dict):
            context_id = str(metadata.get("output_id") or metadata.get("context_id") or "")
            replacement = summaries.get(context_id)
        if replacement is None:
            tool_call_id = str(message.get("tool_call_id") or "")
            replacement = summaries.get(tool_call_id)
        if replacement is None:
            result.append(dict(message))
            continue
        copied = dict(message)
        lines = [
            "[Current turn message summarized]",
            f"summary_version: {replacement.get('summary_version')}",
        ]
        if replacement.get("supersedes_version") is not None:
            lines.append(f"supersedes_version: {replacement.get('supersedes_version')}")
        lines.append(f"reason: {replacement.get('reason')}")
        if replacement.get("context_id"):
            lines.append(f"context_id: {replacement.get('context_id')}")
        elif replacement.get("message_id"):
            lines.append(f"source_message_id: {replacement.get('message_id')}")
        if replacement.get("focus"):
            lines.append(f"focus: {replacement.get('focus')}")
        lines.extend(
            [
                f"summary:\n{replacement.get('summary')}",
                "recover: Use RecoverContext with context_id when present; otherwise use the source_message_id only as a current-turn reference.",
            ]
        )
        copied["content"] = "\n".join(lines)
        result.append(copied)
    return result


def sanitize_messages_for_model(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed_keys = {"role", "content", "name", "tool_call_id", "tool_calls"}
    return [
        {key: value for key, value in message.items() if key in allowed_keys}
        for message in messages
    ]


def build_historical_turns(session_id: str, messages: list[dict[str, Any]]) -> list[HistoricalTurn]:
    turns: list[HistoricalTurn] = []
    system_offset = 1 if messages and messages[0].get("role") == "system" else 0
    index = system_offset
    turn_index = 0
    while index < len(messages):
        message = messages[index]
        if message.get("role") != "user":
            index += 1
            continue
        user_content = message_content_text(message)
        turn_id = stable_id(session_id, str(turn_index), user_content[:200])
        tool_metadata: list[ToolInvocationMetadata] = []
        assistant_final = ""
        index += 1
        pending_calls: dict[str, dict[str, Any]] = {}
        call_index = 0
        while index < len(messages):
            current = messages[index]
            role = current.get("role")
            if role == "user":
                break
            if role == "assistant":
                for tool_call in current.get("tool_calls") or []:
                    tool_call_id = str(tool_call.get("id") or f"tool_call_{call_index}")
                    pending_calls[tool_call_id] = tool_call
                    function = tool_call.get("function") if isinstance(tool_call, dict) else {}
                    tool_name = str((function or {}).get("name") or "")
                    if tool_name:
                        tool_metadata.append(
                            build_tool_invocation_metadata(
                                session_id=session_id,
                                turn_id=turn_id,
                                turn_index=turn_index,
                                call_index=call_index,
                                tool_call_id=tool_call_id,
                                tool_name=tool_name,
                                arguments=str((function or {}).get("arguments") or ""),
                                tool_message=None,
                            )
                        )
                        call_index += 1
                if current.get("content"):
                    assistant_final = message_content_text(current)
            elif role == "tool":
                tool_call_id = str(current.get("tool_call_id") or f"tool_call_{call_index}")
                tool_call = pending_calls.get(tool_call_id, {})
                function = tool_call.get("function") if isinstance(tool_call, dict) else {}
                tool_name = str((function or {}).get("name") or current.get("metadata", {}).get("tool_name") or "")
                arguments = str((function or {}).get("arguments") or "")
                replacement = build_tool_invocation_metadata(
                    session_id=session_id,
                    turn_id=turn_id,
                    turn_index=turn_index,
                    call_index=call_index,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    tool_message=current,
                )
                for existing_index, existing in enumerate(tool_metadata):
                    if existing.tool_call_id == tool_call_id:
                        tool_metadata[existing_index] = replacement
                        break
                else:
                    tool_metadata.append(replacement)
                    call_index += 1
            index += 1
        turns.append(
            HistoricalTurn(
                turn_id=turn_id,
                session_id=session_id,
                turn_index=turn_index,
                user_content=user_content,
                assistant_content=assistant_final,
                tool_metadata=tool_metadata,
            )
        )
        turn_index += 1
    return turns


def build_tool_invocation_metadata(
    *,
    session_id: str,
    turn_id: str,
    turn_index: int,
    call_index: int,
    tool_call_id: str,
    tool_name: str,
    arguments: str,
    tool_message: dict[str, Any] | None,
) -> ToolInvocationMetadata:
    from mycodingagent.memory.message_filters import is_skill_related_tool

    content = message_content_text(tool_message or {})
    metadata = (tool_message or {}).get("metadata")
    metadata_dict = metadata if isinstance(metadata, dict) else {}
    context_id = str(metadata_dict.get("output_id") or metadata_dict.get("context_id") or "")
    kind = "skill" if is_skill_related_tool(tool_name) else "non_skill"
    intent = extract_tool_intent(tool_name, arguments, metadata_dict)
    parsed_args = parse_arguments_object(arguments)
    intent_is_explicit = bool(metadata_dict.get("intent") or parsed_args.get("intent"))
    extra_metadata = {
        key: value
        for key, value in metadata_dict.items()
        if key not in {"output_id", "context_id", "tool_name", "intent", "reproducible"}
    }
    if intent_is_explicit:
        extra_metadata["intent_is_explicit"] = True
    return ToolInvocationMetadata(
        metadata_id=stable_id(session_id, turn_id, tool_call_id, context_id, tool_name),
        session_id=session_id,
        turn_id=turn_id,
        turn_index=turn_index,
        call_index=call_index,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        kind=kind,
        context_id="" if kind == "skill" else context_id,
        invocation_kind=skill_invocation_kind(tool_name) if kind == "skill" else "tool_output",
        intent=intent,
        args_preview=truncate_one_line(arguments, 500),
        args_hash=stable_hash(arguments),
        short_summary=tool_short_summary(tool_name, arguments, content, context_id, intent=intent),
        metadata=extra_metadata,
        keywords=extract_keywords_from_text(" ".join([tool_name, intent, arguments, content]))[:12],
        related_files=extract_related_files_from_text(" ".join([arguments, content]))[:12],
        reference_paths=extract_reference_paths(arguments, content)[:12] if kind == "skill" else [],
        content_type=infer_prompt_content_type(content),
        content_length=len(content),
        token_count=estimate_tokens(content) if content else 0,
        reproducible=bool(metadata_dict.get("reproducible", is_reproducible_tool(tool_name, content))),
        is_error=is_error_text(content),
    )


def message_content_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def stable_id(*parts: str) -> str:
    return stable_hash("\n".join(parts))


def truncate_one_line(text: str, max_chars: int) -> str:
    one_line = " ".join(str(text).split())
    if len(one_line) <= max_chars:
        return one_line
    return one_line[: max(0, max_chars - 1)] + "…"


def parse_arguments_object(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def extract_tool_intent(tool_name: str, arguments: str, metadata: dict[str, Any]) -> str:
    explicit = metadata.get("intent")
    if explicit:
        return truncate_one_line(str(explicit), 160)
    parsed = parse_arguments_object(arguments)
    if parsed.get("intent"):
        return truncate_one_line(str(parsed["intent"]), 160)
    for key in ("instruction", "query", "command", "file_path", "path", "server", "tool", "uri", "prompt"):
        value = parsed.get(key)
        if value:
            return truncate_one_line(f"{tool_name}: {value}", 160)
    return truncate_one_line(f"Call {tool_name}", 160)


def extract_keywords_from_text(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text[:4000])
    stop = {"true", "false", "null", "none", "content", "output", "error", "tool"}
    return dedupe_keep_order([word for word in words if word.lower() not in stop])[:30]


def extract_related_files_from_text(text: str) -> list[str]:
    return dedupe_keep_order(
        re.findall(r"(?<!\w)(?:/workspace/)?[\w./-]+\.[A-Za-z0-9]{1,8}(?!\w)", text[:4000])
    )[:20]


def extract_reference_paths(arguments: str, content: str) -> list[str]:
    candidates = re.findall(r"references/[\w./-]+", arguments + "\n" + content)
    return dedupe_keep_order(candidates)


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def tool_short_summary(tool_name: str, arguments: str, content: str, context_id: str, *, intent: str = "") -> str:
    target = ""
    parsed = parse_arguments_object(arguments)
    for key in ("file_path", "path", "command", "query", "skill_name", "reference_path", "server", "tool", "uri", "prompt"):
        if parsed.get(key):
            target = str(parsed[key])
            break
    parts = [f"{tool_name} output"]
    if intent:
        parts.append(f"intent={intent}")
    if target:
        parts.append(f"for {target}")
    if context_id:
        parts.append(f"context_id={context_id}")
    if content:
        parts.append(f"{len(content)} chars")
        if is_error_text(content):
            parts.append("error")
    return truncate_one_line("; ".join(parts), 240)


def skill_invocation_kind(tool_name: str) -> str:
    if tool_name == "search_tool":
        return "search"
    if tool_name in {"Get_all_tool", "Get_tool_by_name"}:
        return "list"
    if tool_name in {"search_skill_references", "Get_skill_reference"}:
        return "reference"
    if tool_name == "invoke_skill" or tool_name.startswith("skill_"):
        return "workflow"
    return ""


def infer_prompt_content_type(content: str) -> str:
    stripped = content.lstrip()
    if is_error_text(stripped):
        return "error"
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            return "text"
        return "json"
    return "text" if content else ""


def is_error_text(text: str) -> bool:
    return text.startswith("Tool execution error:") or text.startswith("Error:") or '"error"' in text[:300]


def file_state_paths(snapshot: dict) -> list[str]:
    files = snapshot.get("files", []) if isinstance(snapshot, dict) else []
    return [
        item["path"]
        for item in files
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    ]


def has_pending_tool_call(messages: list[dict[str, Any]]) -> bool:
    if not messages:
        return False
    last_message = messages[-1]
    return last_message.get("role") == "assistant" and bool(last_message.get("tool_calls"))


def can_finalize_context_rotation(
    messages: list[dict[str, Any]],
    current_turn_start: int | None,
) -> bool:
    if has_pending_tool_call(messages):
        return False
    if current_turn_start is None:
        return False
    if current_turn_start >= len(messages):
        return True
    return len(messages) == current_turn_start + 1


def snapshot_dict(value: Any | None) -> dict:
    to_dict = getattr(value, "to_dict", None)
    if not callable(to_dict):
        return {}
    try:
        result = to_dict()
    except Exception:
        return {}
    return result if isinstance(result, dict) else {}
