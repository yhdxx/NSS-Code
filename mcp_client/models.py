from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class MCPItemSummary:
    name: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MCPServerSummary:
    name: str
    description: str = ""
    tags: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    abbreviations: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    available: bool = True
    error: str = ""
    tools_count: int = 0
    resources_count: int = 0
    prompts_count: int = 0
    updated_at: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MCPExecutionResult:
    server: str
    operation: str
    name: str
    is_error: bool = False
    content_text: str = ""
    content_type: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)
