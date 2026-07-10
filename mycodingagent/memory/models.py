from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any
from uuid import uuid4


class MemoryScope(str, Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    COMPRESSED_CONTEXT = "compressed_context"


class ContextEpochStatus(str, Enum):
    ACTIVE = "active"
    PENDING_COMMIT = "pending_commit"
    COMMITTED = "committed"


@dataclass
class ContextEpochState:
    epoch_id: str
    session_id: str
    start_message_index: int
    status: ContextEpochStatus = ContextEpochStatus.ACTIVE
    end_message_index: int | None = None
    trigger: str = ""
    reason: str = ""
    summary: str = ""
    retain_context_ids: list[str] = field(default_factory=list)
    active_files: list[str] = field(default_factory=list)
    next_context_hint: str = ""
    created_at: float = field(default_factory=time)
    committed_at: float | None = None


@dataclass(frozen=True)
class HotContextBudgetSnapshot:
    epoch_id: str
    start_message_index: int
    token_count: int
    context_window: int
    usage_ratio: float
    warning: bool
    force_commit: bool
    pending_commit: bool


@dataclass
class MemoryEntry:
    content: str
    scope: MemoryScope
    metadata: dict[str, Any] = field(default_factory=dict)
    entry_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)


@dataclass
class MemoryQuery:
    query: str = ""
    scope: MemoryScope | None = None
    limit: int = 10
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompressionResult:
    content: str = ""
    source_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenUsageRecord:
    usage_id: str
    session_id: str
    request_index: int
    prompt_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    prompt_hash: str = ""
    tools_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time)


@dataclass
class TokenUsageSummary:
    request_count: int = 0
    prompt_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, record: TokenUsageRecord) -> None:
        self.request_count += 1
        self.prompt_tokens += record.prompt_tokens
        self.prompt_cache_hit_tokens += record.prompt_cache_hit_tokens
        self.prompt_cache_miss_tokens += record.prompt_cache_miss_tokens
        self.completion_tokens += record.completion_tokens
        self.total_tokens += record.total_tokens


@dataclass
class ToolOutputRecord:
    output_id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    arguments_json: str
    output_text: str
    output_size: int
    reproducible: bool
    created_at: float = field(default_factory=time)


@dataclass
class ToolInvocationMetadata:
    metadata_id: str
    session_id: str
    turn_id: str
    turn_index: int
    call_index: int
    tool_call_id: str
    tool_name: str
    kind: str
    context_id: str = ""
    invocation_kind: str = ""
    intent: str = ""
    args_preview: str = ""
    args_hash: str = ""
    short_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    reference_paths: list[str] = field(default_factory=list)
    content_type: str = ""
    content_length: int = 0
    token_count: int = 0
    reproducible: bool = False
    is_error: bool = False
    created_at: float = field(default_factory=time)


@dataclass
class HistoricalTurn:
    turn_id: str
    session_id: str
    turn_index: int
    user_content: str
    assistant_content: str
    tool_metadata: list[ToolInvocationMetadata] = field(default_factory=list)
    created_at: float = field(default_factory=time)


@dataclass
class ConversationSnapshot:
    snapshot_id: str
    snapshot_version: str
    session_id: str
    previous_snapshot_id: str = ""
    overall_task_summary: str = ""
    reasoning_conclusions: list[str] = field(default_factory=list)
    project_status: str = ""
    unfinished_tasks: list[str] = field(default_factory=list)
    user_intentions: list[str] = field(default_factory=list)
    important_decisions: list[str] = field(default_factory=list)
    recoverable_context_refs: list[str] = field(default_factory=list)
    workspace_state: dict[str, Any] = field(default_factory=dict)
    memory_state: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time)


@dataclass
class SnapshotDelta:
    delta_id: str
    session_id: str
    base_snapshot_id: str
    turn_start_index: int
    turn_end_index: int
    new_user_intentions: list[str] = field(default_factory=list)
    new_reasoning_conclusions: list[str] = field(default_factory=list)
    new_decisions: list[str] = field(default_factory=list)
    new_unfinished_tasks: list[str] = field(default_factory=list)
    new_recoverable_context_refs: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time)


@dataclass
class CheckpointRecord:
    checkpoint_id: str
    session_id: str
    snapshot_id: str
    previous_snapshot_id: str
    trigger_reason: str
    usage_ratio: float
    created_at: float = field(default_factory=time)


@dataclass
class HistoricalSessionRef:
    session_id: str
    snapshot_id: str
    session_summary: str
    recoverable_context_refs: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time)
    last_accessed_at: float = field(default_factory=time)
    status: str = "historical"


@dataclass
class SessionState:
    session_id: str
    messages: list[dict[str, Any]]
    historical_turns: list[HistoricalTurn] = field(default_factory=list)
    latest_context: list[dict[str, Any]] = field(default_factory=list)
    latest_lrfu: dict[str, Any] = field(default_factory=dict)
    latest_file_state: dict[str, Any] = field(default_factory=dict)
    last_accessed_at: float = 0.0
    workspace_root: str = ""
    workspace_label: str = ""
    workspace_fingerprint: str = ""
    token_usage: TokenUsageSummary = field(default_factory=TokenUsageSummary)
    context_epoch: ContextEpochState | None = None


@dataclass
class SessionListItem:
    session_id: str
    updated_at: float
    last_accessed_at: float
    preview: str
    message_count: int
    workspace_root: str = ""
    workspace_label: str = ""
    workspace_fingerprint: str = ""
