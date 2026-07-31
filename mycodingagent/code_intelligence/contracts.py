from __future__ import annotations

from typing import Any, Protocol


class CodeIndexService(Protocol):
    def query(self, operation: str, **kwargs: Any) -> dict[str, Any]: ...


class LSPService(Protocol):
    async def query(self, operation: str, **kwargs: Any) -> dict[str, Any]: ...
