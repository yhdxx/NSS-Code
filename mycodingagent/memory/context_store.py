from __future__ import annotations

from typing import Protocol

from mycodingagent.memory.context_objects import RecoverableContextObject


class ExternalContextStore(Protocol):
    def save_context(self, context: RecoverableContextObject, content: str) -> str:
        ...

    def load_context(self, context_id: str) -> str | None:
        ...

    def load_partial_context(self, context_id: str, *, offset: int = 0, limit: int = 12000) -> tuple[str, int | None] | None:
        ...

    def delete_context(self, context_id: str) -> bool:
        ...

    def query_metadata(self, context_id: str) -> RecoverableContextObject | None:
        ...

    def search_metadata(self, session_id: str, query: str = "", *, limit: int = 20) -> list[RecoverableContextObject]:
        ...
