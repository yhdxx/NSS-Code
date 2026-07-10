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

    def summary(self) -> str:
        if (
            not self.changed
            and not self.reference_added
            and not self.reference_updated
            and not self.reference_deleted
            and not self.embedding_cache_hits
            and not self.embedding_cache_misses
        ):
            return "Skill index unchanged."
        parts = [
            f"added={self.added}",
            f"updated={self.updated}",
            f"deleted={self.deleted}",
        ]
        if self.reference_added or self.reference_updated or self.reference_deleted:
            parts.append(f"reference_added={self.reference_added}")
            parts.append(f"reference_updated={self.reference_updated}")
            parts.append(f"reference_deleted={self.reference_deleted}")
        if self.embedding_cache_hits or self.embedding_cache_misses:
            parts.append(f"embedding_cache_hits={self.embedding_cache_hits}")
            parts.append(f"embedding_cache_misses={self.embedding_cache_misses}")
        if self.rejected:
            parts.append(f"rejected={len(self.rejected)}")
        return "Skill index updated: " + ", ".join(parts)
