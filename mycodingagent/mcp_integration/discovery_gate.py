from __future__ import annotations

import hashlib
import json
from typing import Any


class MCPDiscoveryGate:
    """Require model-visible MCP metadata before execution."""

    def __init__(self) -> None:
        self._observed_tools: dict[tuple[str, str], str] = {}

    def record_tools(self, server: str, tools: list[dict[str, Any]]) -> None:
        for tool in tools:
            name = str(tool.get("name", "")).strip()
            if name:
                self._observed_tools[(server, name)] = self._fingerprint(tool)

    def allows(self, server: str, tool: str, current_metadata: dict[str, Any] | None) -> bool:
        observed = self._observed_tools.get((server, tool))
        return observed is not None and current_metadata is not None and observed == self._fingerprint(current_metadata)

    def invalidate_server(self, server: str) -> None:
        self._observed_tools = {
            key: fingerprint for key, fingerprint in self._observed_tools.items() if key[0] != server
        }

    def clear(self) -> None:
        self._observed_tools.clear()

    @staticmethod
    def _fingerprint(payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
