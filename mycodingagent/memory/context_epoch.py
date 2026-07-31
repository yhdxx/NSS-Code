from __future__ import annotations

from time import time
from typing import Any, Protocol
from uuid import uuid4

from mycodingagent.memory.budget import estimate_tokens
from mycodingagent.memory.models import ContextEpochState, ContextEpochStatus, HotContextBudgetSnapshot


class ContextEpochStore(Protocol):
    def save_context_epoch(self, state: ContextEpochState) -> None:
        ...

    def load_active_context_epoch(self, session_id: str) -> ContextEpochState | None:
        ...


class ContextEpochManager:
    def __init__(
        self,
        *,
        store: ContextEpochStore,
        context_window: int,
        warning_ratio: float,
        force_ratio: float,
    ) -> None:
        self.store = store
        self.context_window = context_window
        self.warning_ratio = warning_ratio
        self.force_ratio = force_ratio
        self._states: dict[str, ContextEpochState] = {}

    def remember(self, state: ContextEpochState) -> ContextEpochState:
        self._states[state.session_id] = state
        return state

    def get(self, session_id: str) -> ContextEpochState | None:
        cached = self._states.get(session_id)
        if cached is not None:
            return cached
        stored = self.store.load_active_context_epoch(session_id)
        return self.remember(stored) if stored is not None else None

    def ensure(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        current_turn_start: int | None = None,
    ) -> ContextEpochState:
        existing = self.get(session_id)
        if existing is not None:
            return existing
        start_message_index = last_user_message_index(messages)
        if start_message_index is None:
            start_message_index = current_turn_start if current_turn_start is not None else len(messages)
        return self.create(
            session_id=session_id,
            start_message_index=max(0, min(start_message_index, len(messages))),
        )

    def create(self, *, session_id: str, start_message_index: int) -> ContextEpochState:
        state = ContextEpochState(
            epoch_id=uuid4().hex,
            session_id=session_id,
            start_message_index=max(0, start_message_index),
        )
        self.remember(state)
        self.store.save_context_epoch(state)
        return state

    def request_commit(
        self,
        *,
        session_id: str,
        reason: str,
        summary: str,
        retain_context_ids: list[str] | None = None,
        active_files: list[str] | None = None,
        next_context_hint: str = "",
        trigger: str = "model",
        next_start_message_index: int | None = None,
    ) -> ContextEpochState:
        state = self.get(session_id)
        if state is None:
            raise ValueError("no active working context epoch")
        normalized_reason = " ".join(reason.split())
        normalized_summary = summary.strip()
        if not normalized_reason:
            raise ValueError("reason is required")
        if not normalized_summary:
            raise ValueError("summary is required")
        retain_ids = dedupe_strings(retain_context_ids or [])
        files = dedupe_strings(active_files or [])
        next_hint = next_context_hint.strip()
        next_start = (
            max(state.start_message_index, next_start_message_index)
            if next_start_message_index is not None
            else None
        )
        if state.status == ContextEpochStatus.PENDING_COMMIT:
            if (
                state.reason == normalized_reason
                and state.summary == normalized_summary
                and state.retain_context_ids == retain_ids
                and state.active_files == files
                and state.next_context_hint == next_hint
                and state.next_start_message_index == next_start
            ):
                return state
            raise ValueError("working context commit is already pending")
        state.status = ContextEpochStatus.PENDING_COMMIT
        state.trigger = trigger
        state.reason = normalized_reason
        state.summary = normalized_summary
        state.retain_context_ids = retain_ids
        state.active_files = files
        state.next_context_hint = next_hint
        state.next_start_message_index = next_start
        self.store.save_context_epoch(state)
        return state

    def finalize(
        self,
        *,
        session_id: str,
        end_message_index: int,
        pending_tool_call: bool,
    ) -> tuple[ContextEpochState, ContextEpochState] | None:
        state = self.get(session_id)
        if state is None or state.status != ContextEpochStatus.PENDING_COMMIT or pending_tool_call:
            return None
        requested_boundary = (
            state.next_start_message_index
            if state.next_start_message_index is not None
            else end_message_index
        )
        boundary = max(state.start_message_index, min(requested_boundary, end_message_index))
        state.status = ContextEpochStatus.COMMITTED
        state.end_message_index = boundary
        state.committed_at = time()
        self.store.save_context_epoch(state)
        next_state = self.create(session_id=session_id, start_message_index=boundary)
        return state, next_state

    def snapshot(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        current_turn_start: int | None = None,
    ) -> HotContextBudgetSnapshot:
        state = self.ensure(
            session_id=session_id,
            messages=messages,
            current_turn_start=current_turn_start,
        )
        start = max(0, min(state.start_message_index, len(messages)))
        token_count = estimate_tokens(messages[start:]) if start < len(messages) else 0
        usage_ratio = token_count / max(1, self.context_window)
        return HotContextBudgetSnapshot(
            epoch_id=state.epoch_id,
            start_message_index=start,
            token_count=token_count,
            context_window=self.context_window,
            usage_ratio=usage_ratio,
            warning=usage_ratio >= self.warning_ratio,
            force_commit=usage_ratio >= self.force_ratio,
            pending_commit=state.status == ContextEpochStatus.PENDING_COMMIT,
        )

    def delete(self, session_id: str) -> None:
        self._states.pop(session_id, None)


def last_user_message_index(messages: list[dict[str, Any]]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index
    return None


def dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def collect_context_epoch_files(
    messages: list[dict[str, Any]],
    start_message_index: int,
    end_message_index: int | None = None,
) -> list[str]:
    files: list[str] = []
    end = len(messages) if end_message_index is None else max(0, min(end_message_index, len(messages)))
    for message in messages[max(0, start_message_index) : end]:
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            continue
        for key in ("related_files", "reference_paths"):
            value = metadata.get(key)
            if isinstance(value, list):
                files.extend(str(item) for item in value)
        for key in ("file_path", "path"):
            value = metadata.get(key)
            if isinstance(value, str):
                files.append(value)
    return dedupe_strings(files)


def automatic_context_epoch_summary(
    messages: list[dict[str, Any]],
    start_message_index: int,
    end_message_index: int | None = None,
) -> str:
    end = len(messages) if end_message_index is None else max(0, min(end_message_index, len(messages)))
    user_messages = [
        str(message.get("content", "")).strip()
        for message in messages[max(0, start_message_index) : end]
        if message.get("role") == "user" and str(message.get("content", "")).strip()
    ]
    if not user_messages:
        return "工作上下文达到配置的 Token 阈值后自动提交。"
    latest = user_messages[-1]
    if len(latest) > 800:
        latest = latest[:800] + "..."
    return f"自动提交工作上下文。最近的用户请求：{latest}"


def retained_hot_start_index(
    messages: list[dict[str, Any]],
    *,
    start_message_index: int,
    retained_turns: int,
) -> int:
    turn_starts = user_turn_starts(
        messages,
        start_message_index=start_message_index,
        end_message_index=len(messages),
    )
    if not turn_starts:
        return len(messages)
    retained = max(1, retained_turns)
    return turn_starts[-retained] if len(turn_starts) >= retained else turn_starts[0]


def user_turn_starts(
    messages: list[dict[str, Any]],
    *,
    start_message_index: int = 0,
    end_message_index: int | None = None,
) -> list[int]:
    end = len(messages) if end_message_index is None else max(0, min(end_message_index, len(messages)))
    return [
        index
        for index, message in enumerate(messages[max(0, start_message_index) : end], start=max(0, start_message_index))
        if message.get("role") == "user"
    ]


def format_hot_context_notice(snapshot: HotContextBudgetSnapshot) -> str:
    if snapshot.pending_commit:
        action = "已有待处理提交，将在当前轮次结束后应用。"
    elif snapshot.force_commit:
        action = "Runtime 已强制轮换工作上下文。不要因为本通知再次调用 CommitWorkingContext。"
    else:
        action = "当前任务或主题完成时调用 CommitWorkingContext。"
    return (
        "热工作上下文通知\n"
        f"epoch_id: {snapshot.epoch_id}\n"
        f"hot_context_tokens: {snapshot.token_count}\n"
        f"context_window: {snapshot.context_window}\n"
        f"hot_context_ratio: {snapshot.usage_ratio:.2%}\n"
        f"force_commit: {str(snapshot.force_commit).lower()}\n"
        f"{action}"
    )


def format_context_epoch_commit_report(
    committed: ContextEpochState,
    next_state: ContextEpochState,
) -> str:
    return (
        "[WORK CONTEXT COMMIT]\n"
        f"  committed_epoch: {committed.epoch_id}\n"
        f"  trigger: {committed.trigger}\n"
        f"  message_range: {committed.start_message_index}:{committed.end_message_index}\n"
        f"  next_epoch: {next_state.epoch_id}\n"
        f"  next_start: {next_state.start_message_index}"
    )
