from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any


class MemoryType(str, Enum):
    USER_PROFILE = "user_profile"
    USER_PREFERENCE = "user_preference"
    PROJECT_FACT = "project_fact"
    DECISION = "decision"
    WORKFLOW_CANDIDATE = "workflow_candidate"
    SKILL_CANDIDATE = "skill_candidate"


class MemoryScope(str, Enum):
    USER = "user"
    WORKSPACE = "workspace"
    PROJECT = "project"


class MemoryItemStatus(str, Enum):
    ACTIVE = "active"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


class MemoryVersionStatus(str, Enum):
    STAGING = "staging"
    COMMITTED = "committed"
    FAILED = "failed"


class ExtractionStatus(str, Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    COMMITTED = "committed"
    FAILED = "failed"


@dataclass(frozen=True)
class LongTermMemoryItem:
    memory_uid: str
    version_id: str
    memory_type: MemoryType
    scope: MemoryScope
    content: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    status: MemoryItemStatus = MemoryItemStatus.ACTIVE
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)

    def to_context_payload(self, *, include_uid: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.memory_type.value,
            "scope": self.scope.value,
            "content": self.content,
        }
        if include_uid:
            payload["memory_uid"] = self.memory_uid
        return payload


@dataclass(frozen=True)
class LongTermMemoryVersion:
    version_id: str
    user_id: str
    workspace_fingerprint: str
    workspace_label: str = ""
    status: MemoryVersionStatus = MemoryVersionStatus.STAGING
    parent_version_id: str = ""
    source_session_id: str = ""
    created_at: float = field(default_factory=time)
    committed_at: float = 0.0
    error_text: str = ""


@dataclass(frozen=True)
class ExtractionJob:
    extraction_id: str
    session_id: str
    user_id: str
    workspace_fingerprint: str
    workspace_label: str
    workspace_root: str
    status: ExtractionStatus
    source_hash: str
    source_message_count: int
    created_at: float
    updated_at: float
    started_at: float = 0.0
    finished_at: float = 0.0
    error_text: str = ""
    committed_version_id: str = ""


@dataclass(frozen=True)
class LongTermMemoryContext:
    version_id: str
    summary: str
    memories: list[LongTermMemoryItem] = field(default_factory=list)
    workflow_candidates: list[LongTermMemoryItem] = field(default_factory=list)
    skill_candidates: list[LongTermMemoryItem] = field(default_factory=list)
    query_id: str = ""

    def to_runtime_payload(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "memories": [item.to_context_payload() for item in self.memories],
            "workflow_candidates": [
                item.to_context_payload(include_uid=True) for item in self.workflow_candidates
            ],
            "skill_candidates": [
                item.to_context_payload(include_uid=True) for item in self.skill_candidates
            ],
        }


@dataclass(frozen=True)
class ExtractionResult:
    status: str
    extraction_id: str = ""
    version_id: str = ""
    error: str = ""
