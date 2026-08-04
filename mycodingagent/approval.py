from __future__ import annotations

from enum import Enum


class ApprovalMode(str, Enum):
    DEFAULT = "default"
    AUTO = "auto"

    @classmethod
    def parse(cls, value: str | "ApprovalMode") -> "ApprovalMode":
        if isinstance(value, cls):
            return value
        return cls(str(value).strip().lower())


class ApprovalRuntime:
    """Process-local approval mode shared by Bash and MCP approval hooks."""

    def __init__(self, mode: str | ApprovalMode = ApprovalMode.DEFAULT) -> None:
        self._mode = ApprovalMode.parse(mode)

    @property
    def mode(self) -> ApprovalMode:
        return self._mode

    @property
    def auto_approve(self) -> bool:
        return self._mode is ApprovalMode.AUTO

    def set_mode(self, mode: str | ApprovalMode) -> ApprovalMode:
        self._mode = ApprovalMode.parse(mode)
        return self._mode
