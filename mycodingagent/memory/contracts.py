from __future__ import annotations

from typing import Protocol

from mycodingagent.memory.models import ContextEpochState


class ContextEpochControl(Protocol):
    def get_current_session_id(self) -> str | None:
        ...

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
    ) -> ContextEpochState:
        ...
