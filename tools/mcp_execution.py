from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from mcp_client.hooks import MCPToolApprovalHook, USER_DENIED_MESSAGE
from mcp_client.manager import MCPClientManager
from mcp_client.policy import MCPApprovalRequest, MCPToolPermissionPolicy
from tools.base import Tool, ToolResult

MAX_INTENT_CHARS = 160


class CallToolParams(BaseModel):
    server: str = Field(description="Exact MCP server name")
    tool: str = Field(description="Exact MCP tool name exposed by the server")
    arguments: dict[str, Any] = Field(default_factory=dict, description="MCP tool arguments")
    intent: str = Field(description="Short intent for this MCP tool call; required for virtualization metadata")


class ReadResourceParams(BaseModel):
    server: str = Field(description="Exact MCP server name")
    uri: str = Field(description="Exact MCP resource URI")
    intent: str = Field(description="Short intent for this MCP resource read; required for virtualization metadata")


class GetPromptParams(BaseModel):
    server: str = Field(description="Exact MCP server name")
    prompt: str = Field(description="Exact MCP prompt name")
    arguments: dict[str, Any] = Field(default_factory=dict, description="MCP prompt arguments")
    intent: str = Field(description="Short intent for this MCP prompt retrieval; required for virtualization metadata")


class CallMCPToolTool(Tool):
    name = "call_tool"
    description = (
        "Call one tool from a configured MCP server. Provide a short intent. "
        "Read-only tools run directly; write/dangerous/unknown tools require user approval."
    )
    params_model = CallToolParams
    category = "command"
    is_concurrency_safe = False
    is_system_tool = True

    def __init__(
        self,
        manager: MCPClientManager,
        policy: MCPToolPermissionPolicy,
        approval_hook: MCPToolApprovalHook,
    ) -> None:
        self._manager = manager
        self._policy = policy
        self._approval_hook = approval_hook

    async def execute(self, params: CallToolParams) -> ToolResult:
        intent = _compact_intent(params.intent)
        if not intent:
            return ToolResult(output="MCP tool calls require a short intent.", is_error=True)
        config = self._manager.server_configs.get(params.server)
        risk = self._policy.classify(server_config=config, tool_name=params.tool)
        decision = await self._approval_hook.approve(
            MCPApprovalRequest(
                server=params.server,
                tool=params.tool,
                risk=risk,
                intent=intent,
                arguments=params.arguments,
            )
        )
        if not decision.allowed:
            return ToolResult(output=USER_DENIED_MESSAGE, is_error=True)
        approval = decision.reason or "user_allowed"
        result = await self._manager.call_tool(params.server, params.tool, params.arguments)
        payload = result.to_payload()
        payload["intent"] = intent
        payload["risk"] = risk
        payload["approval"] = approval
        payload["mcp_server"] = params.server
        payload["mcp_tool"] = params.tool
        return _json_result(payload, is_error=result.is_error)


class ReadMCPResourceTool(Tool):
    name = "read_resource"
    description = "Read one MCP resource by URI from a configured server. Provide a short intent."
    params_model = ReadResourceParams
    category = "read"
    is_concurrency_safe = False
    is_system_tool = True

    def __init__(self, manager: MCPClientManager) -> None:
        self._manager = manager

    async def execute(self, params: ReadResourceParams) -> ToolResult:
        intent = _compact_intent(params.intent)
        if not intent:
            return ToolResult(output="MCP resource reads require a short intent.", is_error=True)
        result = await self._manager.read_resource(params.server, params.uri)
        payload = result.to_payload()
        payload["intent"] = intent
        payload["risk"] = "read"
        payload["approval"] = "auto_allowed"
        payload["mcp_server"] = params.server
        payload["mcp_resource"] = params.uri
        return _json_result(payload, is_error=result.is_error)


class GetMCPPromptTool(Tool):
    name = "get_prompt"
    description = "Get one MCP prompt by name from a configured server. Provide a short intent."
    params_model = GetPromptParams
    category = "read"
    is_concurrency_safe = False
    is_system_tool = True

    def __init__(self, manager: MCPClientManager) -> None:
        self._manager = manager

    async def execute(self, params: GetPromptParams) -> ToolResult:
        intent = _compact_intent(params.intent)
        if not intent:
            return ToolResult(output="MCP prompt retrieval requires a short intent.", is_error=True)
        result = await self._manager.get_prompt(params.server, params.prompt, params.arguments)
        payload = result.to_payload()
        payload["intent"] = intent
        payload["risk"] = "read"
        payload["approval"] = "auto_allowed"
        payload["mcp_server"] = params.server
        payload["mcp_prompt"] = params.prompt
        return _json_result(payload, is_error=result.is_error)


def register_mcp_execution_tools(
    registry,
    *,
    manager: MCPClientManager,
    policy: MCPToolPermissionPolicy,
    approval_hook: MCPToolApprovalHook,
) -> None:
    registry.register(CallMCPToolTool(manager, policy, approval_hook))
    registry.register(ReadMCPResourceTool(manager))
    registry.register(GetMCPPromptTool(manager))


def _compact_intent(value: str) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= MAX_INTENT_CHARS:
        return text
    return text[:MAX_INTENT_CHARS]


def _json_result(payload: dict[str, Any], *, is_error: bool = False) -> ToolResult:
    return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2, default=str), is_error=is_error)
