from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ReviewResult:
    approved: bool = True
    reason: str = ""


@dataclass
class SkillRecord:
    name: str
    tool_name: str
    description: str
    content: str
    source_path: Path
    content_hash: str
    updated_at: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillReferenceRecord:
    ref_id: str
    skill_tool_name: str
    skill_name: str
    reference_path: str
    file_name: str
    content: str
    source_path: Path
    content_hash: str
    updated_at: float


@dataclass
class SearchResult:
    record: SkillRecord
    score: float
    keyword_score: float
    semantic_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillSyncReport:
    changed: bool = False
    added: int = 0
    updated: int = 0
    deleted: int = 0
    reference_added: int = 0
    reference_updated: int = 0
    reference_deleted: int = 0
    embedding_cache_hits: int = 0
    embedding_cache_misses: int = 0
    rejected: list[str] = field(default_factory=list)
