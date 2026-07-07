from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from time import time
from typing import Any, Protocol
from uuid import uuid4

from config import CONFIG
from memory.budget import PromptBudgetSnapshot
from memory.models import CheckpointRecord, ConversationSnapshot, SnapshotDelta


SNAPSHOT_FIELD_ORDER = (
    "snapshot_version",
    "snapshot_id",
    "previous_snapshot_id",
    "overall_task_summary",
    "reasoning_conclusions",
    "project_status",
    "unfinished_tasks",
    "user_intentions",
    "important_decisions",
    "recoverable_context_refs",
    "workspace_state",
    "memory_state",
)


@dataclass(frozen=True)
class TurnState:
    completed: bool = True
    pending_tool_call: bool = False
    active_recovery: bool = False
    retrying_error: bool = False
    turn_end_index: int = 0


@dataclass(frozen=True)
class CheckpointDecision:
    should_checkpoint: bool
    candidate: bool = False
    trigger_reason: str = ""


@dataclass(frozen=True)
class RolloverResult:
    performed: bool = False
    new_session_id: str = ""
    new_messages: list[dict[str, Any]] | None = None
    snapshot_id: str = ""


class SnapshotGenerator(Protocol):
    def generate_delta(
        self,
        *,
        session_id: str,
        previous_snapshot: ConversationSnapshot | None,
        new_messages: list[dict[str, Any]],
        runtime_state: dict[str, Any],
        turn_start_index: int,
        turn_end_index: int,
    ) -> SnapshotDelta:
        ...

    def merge_snapshot(
        self,
        *,
        session_id: str,
        previous_snapshot: ConversationSnapshot | None,
        delta: SnapshotDelta,
        runtime_state: dict[str, Any],
    ) -> ConversationSnapshot:
        ...


class StructuredSnapshotGenerator:
    def generate_delta(
        self,
        *,
        session_id: str,
        previous_snapshot: ConversationSnapshot | None,
        new_messages: list[dict[str, Any]],
        runtime_state: dict[str, Any],
        turn_start_index: int,
        turn_end_index: int,
    ) -> SnapshotDelta:
        base_snapshot_id = previous_snapshot.snapshot_id if previous_snapshot is not None else ""
        user_intentions: list[str] = []
        conclusions: list[str] = []
        decisions: list[str] = []
        unfinished: list[str] = []
        context_refs: list[str] = []

        for message in new_messages:
            role = str(message.get("role", ""))
            text = message_text(message)
            if role == "user" and text:
                user_intentions.append(truncate(text, 500))
            elif role == "assistant" and text:
                conclusions.append(truncate(text, 700))
                for line in extracted_action_lines(text):
                    target = decisions if looks_like_decision(line) else unfinished
                    target.append(truncate(line, 300))
            metadata = message.get("metadata")
            if isinstance(metadata, dict):
                output_id = metadata.get("output_id") or metadata.get("context_id")
                if isinstance(output_id, str) and output_id:
                    context_refs.append(output_id)
            if role == "tool":
                for ref in extract_context_refs(text):
                    context_refs.append(ref)

        runtime_refs = runtime_state.get("recoverable_context_refs", [])
        if isinstance(runtime_refs, list):
            context_refs.extend(str(ref) for ref in runtime_refs if ref)

        return SnapshotDelta(
            delta_id=uuid4().hex,
            session_id=session_id,
            base_snapshot_id=base_snapshot_id,
            turn_start_index=turn_start_index,
            turn_end_index=turn_end_index,
            new_user_intentions=dedupe(user_intentions),
            new_reasoning_conclusions=dedupe(conclusions),
            new_decisions=dedupe(decisions),
            new_unfinished_tasks=dedupe(unfinished),
            new_recoverable_context_refs=dedupe(context_refs),
        )

    def merge_snapshot(
        self,
        *,
        session_id: str,
        previous_snapshot: ConversationSnapshot | None,
        delta: SnapshotDelta,
        runtime_state: dict[str, Any],
    ) -> ConversationSnapshot:
        previous_snapshot_id = previous_snapshot.snapshot_id if previous_snapshot is not None else ""
        user_intentions = merge_lists(
            previous_snapshot.user_intentions if previous_snapshot is not None else [],
            delta.new_user_intentions,
        )
        reasoning_conclusions = merge_lists(
            previous_snapshot.reasoning_conclusions if previous_snapshot is not None else [],
            delta.new_reasoning_conclusions,
        )
        important_decisions = merge_lists(
            previous_snapshot.important_decisions if previous_snapshot is not None else [],
            delta.new_decisions,
        )
        unfinished_tasks = merge_lists(
            previous_snapshot.unfinished_tasks if previous_snapshot is not None else [],
            delta.new_unfinished_tasks,
        )
        context_refs = merge_lists(
            previous_snapshot.recoverable_context_refs if previous_snapshot is not None else [],
            delta.new_recoverable_context_refs,
        )
        workspace_state = dict(previous_snapshot.workspace_state) if previous_snapshot is not None else {}
        workspace_state.update(runtime_state.get("workspace_state", {}))
        memory_state = dict(previous_snapshot.memory_state) if previous_snapshot is not None else {}
        memory_state.update(runtime_state.get("memory_state", {}))
        project_status = infer_project_status(delta, previous_snapshot)
        summary = build_summary(user_intentions, reasoning_conclusions, project_status)

        return ConversationSnapshot(
            snapshot_id=uuid4().hex,
            snapshot_version=CONFIG.memory.snapshot_version,
            session_id=session_id,
            previous_snapshot_id=previous_snapshot_id,
            overall_task_summary=summary,
            reasoning_conclusions=reasoning_conclusions,
            project_status=project_status,
            unfinished_tasks=unfinished_tasks,
            user_intentions=user_intentions,
            important_decisions=important_decisions,
            recoverable_context_refs=context_refs,
            workspace_state=workspace_state,
            memory_state=memory_state,
        )


class CheckpointManager:
    def __init__(
        self,
        *,
        memory_runtime: Any,
        prompt_budget_manager: Any,
        snapshot_generator: SnapshotGenerator | None = None,
    ) -> None:
        self.memory_runtime = memory_runtime
        self.prompt_budget_manager = prompt_budget_manager
        self.snapshot_generator = snapshot_generator or StructuredSnapshotGenerator()
        self.previous_checkpoint_index = 0
        self.last_rollover_turn_index = 0

    def should_checkpoint(self, turn_state: TurnState, budget_snapshot: PromptBudgetSnapshot) -> CheckpointDecision:
        if not CONFIG.memory.checkpoint_enabled:
            return CheckpointDecision(False, trigger_reason="disabled")
        if (
            not turn_state.completed
            or turn_state.pending_tool_call
            or turn_state.active_recovery
            or turn_state.retrying_error
        ):
            return CheckpointDecision(False, trigger_reason="unstable_turn")
        usage_ratio = budget_snapshot.usage_ratio
        if usage_ratio < CONFIG.memory.checkpoint_soft_ratio:
            return CheckpointDecision(False, trigger_reason="below_soft_threshold")
        if usage_ratio >= CONFIG.memory.checkpoint_hard_ratio:
            return CheckpointDecision(True, trigger_reason="hard_threshold")
        min_turns = max(1, CONFIG.memory.checkpoint_min_turns_between_rollovers)
        if turn_state.turn_end_index - self.last_rollover_turn_index >= min_turns:
            return CheckpointDecision(True, candidate=True, trigger_reason="soft_threshold")
        return CheckpointDecision(False, candidate=True, trigger_reason="soft_threshold_wait")

    def create_session_delta(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        previous_checkpoint_index: int | None = None,
        runtime_state: dict[str, Any] | None = None,
    ) -> SnapshotDelta:
        start = self.previous_checkpoint_index if previous_checkpoint_index is None else previous_checkpoint_index
        start = max(0, min(start, len(messages)))
        recent_turns = max(1, CONFIG.memory.checkpoint_recent_delta_turns)
        bounded_start = max(start, len(messages) - recent_turns * 4)
        previous_snapshot = self.memory_runtime.store.get_latest_snapshot_for_session(session_id)
        return self.snapshot_generator.generate_delta(
            session_id=session_id,
            previous_snapshot=previous_snapshot,
            new_messages=messages[bounded_start:],
            runtime_state=runtime_state or {},
            turn_start_index=bounded_start,
            turn_end_index=len(messages),
        )

    def create_incremental_snapshot(
        self,
        previous_snapshot: ConversationSnapshot | None,
        delta: SnapshotDelta,
        runtime_state: dict[str, Any] | None = None,
    ) -> ConversationSnapshot:
        return self.snapshot_generator.merge_snapshot(
            session_id=delta.session_id,
            previous_snapshot=previous_snapshot,
            delta=delta,
            runtime_state=runtime_state or {},
        )

    def checkpoint_session(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        runtime_state: dict[str, Any],
        trigger_reason: str,
        usage_ratio: float,
    ) -> ConversationSnapshot:
        previous_snapshot = self._latest_runtime_snapshot(session_id)
        delta = self.create_session_delta(session_id, messages, self.previous_checkpoint_index, runtime_state)
        snapshot = self.create_incremental_snapshot(previous_snapshot, delta, runtime_state)
        self.memory_runtime.store.save_snapshot_delta(delta)
        self.memory_runtime.store.save_conversation_snapshot(snapshot)
        self.memory_runtime.store.save_checkpoint_record(
            CheckpointRecord(
                checkpoint_id=uuid4().hex,
                session_id=session_id,
                snapshot_id=snapshot.snapshot_id,
                previous_snapshot_id=snapshot.previous_snapshot_id,
                trigger_reason=trigger_reason,
                usage_ratio=usage_ratio,
            )
        )
        self.memory_runtime.latest_snapshot_id = snapshot.snapshot_id
        self.previous_checkpoint_index = len(messages)
        return snapshot

    def rollover_session(
        self,
        *,
        session_id: str,
        snapshot: ConversationSnapshot,
        system_prompt_source: dict[str, Any] | None,
    ) -> RolloverResult:
        summary = snapshot.overall_task_summary or snapshot.project_status or "Session checkpoint snapshot."
        self.memory_runtime.store.mark_session_historical(
            session_id,
            snapshot.snapshot_id,
            summary,
            snapshot.recoverable_context_refs,
        )
        new_session_id = uuid4().hex
        system_message = copy_system_message(system_prompt_source)
        new_messages = [system_message, {"role": "system", "content": format_snapshot_prompt(snapshot)}]
        self.memory_runtime.current_session_id = new_session_id
        self.memory_runtime.store.ensure_session(
            session_id=new_session_id,
            model=self.memory_runtime.model,
            workspace_root=self.memory_runtime.workspace_root,
            workspace_label=self.memory_runtime.workspace_label,
            workspace_fingerprint=self.memory_runtime.workspace_fingerprint,
        )
        self.memory_runtime.store.save_messages(session_id=new_session_id, messages=new_messages)
        self.last_rollover_turn_index = self.previous_checkpoint_index
        self.previous_checkpoint_index = len(new_messages)
        return RolloverResult(
            performed=True,
            new_session_id=new_session_id,
            new_messages=new_messages,
            snapshot_id=snapshot.snapshot_id,
        )

    def restore_session_snapshot(self, session_id: str) -> ConversationSnapshot | None:
        historical = self.memory_runtime.store.get_historical_session(session_id)
        if historical is None:
            return None
        self.memory_runtime.store.touch_historical_session(session_id)
        return self.memory_runtime.store.get_conversation_snapshot(historical.snapshot_id)

    def _latest_runtime_snapshot(self, session_id: str) -> ConversationSnapshot | None:
        snapshot_id = getattr(self.memory_runtime, "latest_snapshot_id", "")
        if snapshot_id:
            snapshot = self.memory_runtime.store.get_conversation_snapshot(snapshot_id)
            if snapshot is not None:
                return snapshot
        return self.memory_runtime.store.get_latest_snapshot_for_session(session_id)


def format_snapshot_prompt(snapshot: ConversationSnapshot) -> str:
    payload = asdict(snapshot)
    lines = ["CONVERSATION SNAPSHOT"]
    for field_name in SNAPSHOT_FIELD_ORDER:
        lines.append(f"{field_name}: {json.dumps(payload.get(field_name), ensure_ascii=False, default=str)}")
    return "\n".join(lines)


def copy_system_message(system_prompt_source: dict[str, Any] | None) -> dict[str, Any]:
    if system_prompt_source and system_prompt_source.get("role") == "system":
        return {"role": "system", "content": system_prompt_source.get("content", "")}
    return {"role": "system", "content": ""}


def message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    return json.dumps(content, ensure_ascii=False, default=str)


def extracted_action_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip(" \t-*0123456789.、")
        if line:
            lines.append(line)
    return lines[:10]


def looks_like_decision(line: str) -> bool:
    lowered = line.lower()
    return any(marker in lowered for marker in ("decision", "decided", "采用", "选择", "决定", "实现为"))


def extract_context_refs(text: str) -> list[str]:
    refs: list[str] = []
    for line in text.splitlines():
        if "context_id:" in line or "output_id:" in line:
            refs.append(line.split(":", 1)[1].strip())
    return [ref for ref in refs if ref]


def infer_project_status(delta: SnapshotDelta, previous_snapshot: ConversationSnapshot | None) -> str:
    if delta.new_unfinished_tasks:
        return "in_progress"
    if delta.new_reasoning_conclusions or delta.new_decisions:
        return "stable"
    if previous_snapshot is not None and previous_snapshot.project_status:
        return previous_snapshot.project_status
    return "active"


def build_summary(user_intentions: list[str], conclusions: list[str], project_status: str) -> str:
    parts = []
    if user_intentions:
        parts.append(f"Latest user intent: {user_intentions[-1]}")
    if conclusions:
        parts.append(f"Latest conclusion: {conclusions[-1]}")
    parts.append(f"Project status: {project_status}")
    return " ".join(parts)


def merge_lists(existing: list[str], incoming: list[str], *, limit: int = 80) -> list[str]:
    return dedupe([*existing, *incoming])[-limit:]


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = " ".join(str(item).split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def truncate(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"
