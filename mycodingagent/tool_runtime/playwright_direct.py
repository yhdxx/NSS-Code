from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from mycodingagent.mcp_integration.hooks import MCPToolApprovalHook, USER_DENIED_MESSAGE
from mycodingagent.mcp_integration.manager import MCPClientManager
from mycodingagent.mcp_integration.models import MCPItemSummary
from mycodingagent.mcp_integration.policy import MCPApprovalRequest, MCPToolPermissionPolicy
from mycodingagent.tool_contracts import MAX_TOOL_INTENT_CHARS, apply_tool_intent_schema
from mycodingagent.tool_runtime.base import Tool, ToolResult


class _PlaywrightDirectParams(BaseModel):
    model_config = ConfigDict(extra="allow")
    intent: str = ""


class PlaywrightDirectTool(Tool):
    """Expose one discovered Playwright MCP tool as a normal local tool."""

    category = "command"
    is_system_tool = True
    is_playwright_tool = True
    params_model = _PlaywrightDirectParams

    def __init__(
        self,
        manager: MCPClientManager,
        policy: MCPToolPermissionPolicy,
        approval_hook: MCPToolApprovalHook,
        summary: MCPItemSummary,
    ) -> None:
        self._manager = manager
        self._policy = policy
        self._approval_hook = approval_hook
        self._remote_name = summary.name
        self.name = _schema_name(summary.name)
        self.description = summary.description or f"调用 Playwright 浏览器工具 {summary.name}。"
        if summary.name in {"browser_take_screenshot", "browser_pdf_save"}:
            self.description += " Runtime 会把输出保存到当前工作区的会话专属目录，并在结果中返回工作区相对路径。"
        self._remote_schema = _input_schema(summary.metadata)
        if summary.name in _READ_TOOL_NAMES:
            self.category = "read"

    def get_schema(self) -> dict[str, Any]:
        schema = dict(self._remote_schema)
        properties = dict(schema.get("properties") or {})
        apply_tool_intent_schema(schema)
        properties = schema["properties"]
        required = [str(value) for value in list(schema.get("required") or []) if str(value) != "intent"]
        required.append("intent")
        schema["type"] = "object"
        schema["properties"] = properties
        schema["required"] = required
        schema.setdefault("additionalProperties", True)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }

    async def execute(self, params: BaseModel) -> ToolResult:
        values = params.model_dump(exclude={"intent"})
        intent = str(getattr(params, "intent", "") or self.description[:MAX_TOOL_INTENT_CHARS])
        config = self._manager.server_configs.get("playwright")
        if config is None:
            return ToolResult("Playwright MCP 未启用。", is_error=True)
        metadata = self._manager.cached_tool_payload("playwright", self._remote_name) or {}
        risk = self._policy.classify(
            server_config=config,
            tool_name=self._remote_name,
            tool_metadata=metadata.get("metadata", {}) if isinstance(metadata, dict) else {},
        )
        if self._policy.requires_approval(risk):
            decision = await self._approval_hook.approve(
                MCPApprovalRequest(
                    server="playwright",
                    tool=self._remote_name,
                    risk=risk,
                    intent=intent,
                    arguments=values,
                )
            )
            if not decision.allowed:
                return ToolResult(USER_DENIED_MESSAGE, is_error=True)
        result = await self._manager.call_tool("playwright", self._remote_name, values)
        payload = result.to_payload()
        payload.update({"core_browser_tool": self.name, "direct_playwright_tool": True, "risk": risk})
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), is_error=result.is_error)


def _schema_name(remote_name: str) -> str:
    return "".join(char if char.isalnum() or char == "_" else "_" for char in remote_name).strip("_")


def _input_schema(metadata: dict[str, Any]) -> dict[str, Any]:
    raw = metadata.get("inputSchema") if isinstance(metadata, dict) else None
    return dict(raw) if isinstance(raw, dict) and raw.get("type") == "object" else {
        "type": "object",
        "properties": {},
        "additionalProperties": True,
    }


_READ_TOOL_NAMES = frozenset(
    {
        "browser_navigate",
        "browser_navigate_back",
        "browser_navigate_forward",
        "browser_reload",
        "browser_snapshot",
        "browser_take_screenshot",
        "browser_tabs",
        "browser_console_messages",
        "browser_network_requests",
        "browser_network_request",
        "browser_pdf_save",
    }
)


def register_discovered_playwright_tools(
    registry: Any,
    *,
    manager: MCPClientManager,
    policy: MCPToolPermissionPolicy,
    approval_hook: MCPToolApprovalHook,
) -> int:
    summaries = manager.cached_tools("playwright")
    for summary in summaries:
        registry.register(PlaywrightDirectTool(manager, policy, approval_hook, summary))
    return len(summaries)
