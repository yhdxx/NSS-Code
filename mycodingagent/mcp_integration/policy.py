from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mycodingagent.mcp_integration.config import MCPServerConfig

MCPToolRisk = Literal["read", "write", "dangerous", "unknown"]

READ_PREFIXES = ("get", "list", "search", "read", "fetch", "query", "inspect")
WRITE_PREFIXES = ("create", "update", "add", "comment", "push", "fork", "open", "submit")
DANGEROUS_PREFIXES = ("delete", "remove", "merge", "close", "archive", "publish", "deploy", "overwrite")


@dataclass(frozen=True)
class MCPApprovalRequest:
    server: str
    tool: str
    risk: MCPToolRisk
    intent: str
    arguments: dict


@dataclass(frozen=True)
class MCPApprovalDecision:
    allowed: bool
    reason: str = ""


class MCPToolPermissionPolicy:
    def classify(
        self,
        *,
        server_config: MCPServerConfig | None,
        tool_name: str,
        tool_metadata: dict | None = None,
    ) -> MCPToolRisk:
        normalized = tool_name.strip().lower()
        permissions = server_config.permissions if server_config is not None else None
        if permissions is not None:
            if _matches(normalized, permissions.dangerous_tools):
                return "dangerous"
            if _matches(normalized, permissions.write_tools):
                return "write"
            if _matches(normalized, permissions.read_tools):
                return "read"
        annotations = (tool_metadata or {}).get("annotations", {})
        if isinstance(annotations, dict):
            if annotations.get("destructiveHint") is True:
                return "dangerous"
            if annotations.get("readOnlyHint") is True:
                return "read"
            if annotations.get("readOnlyHint") is False:
                return "write"
        if normalized.startswith(DANGEROUS_PREFIXES) or any(f"_{item}" in normalized for item in DANGEROUS_PREFIXES):
            return "dangerous"
        if normalized.startswith(WRITE_PREFIXES) or any(f"_{item}" in normalized for item in WRITE_PREFIXES):
            return "write"
        if normalized.startswith(READ_PREFIXES) or any(f"_{item}" in normalized for item in READ_PREFIXES):
            return "read"
        if permissions is not None and permissions.readonly_by_default:
            return "read"
        return "unknown"

    def requires_approval(self, risk: MCPToolRisk) -> bool:
        return risk != "read"


def _matches(tool_name: str, configured: tuple[str, ...]) -> bool:
    return any(tool_name == item.strip().lower() for item in configured)
