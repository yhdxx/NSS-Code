from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from mycodingagent.mcp_integration.hooks import MCPToolApprovalHook, USER_DENIED_MESSAGE
from mycodingagent.mcp_integration.manager import MCPClientManager
from mycodingagent.mcp_integration.policy import MCPApprovalRequest, MCPToolPermissionPolicy
from mycodingagent.tool_contracts import MAX_TOOL_INTENT_CHARS
from mycodingagent.tool_runtime.base import Tool, ToolResult


class CallToolParams(BaseModel):
    server: str = Field(description="准确的 MCP Server 名称")
    tool: str = Field(description="Server 暴露的准确 MCP 工具名称")
    arguments: dict[str, Any] = Field(default_factory=dict, description="MCP 工具参数")
    intent: str = Field(description="本次 MCP 工具调用的简短目的，用于上下文虚拟化元数据")


class ReadResourceParams(BaseModel):
    server: str = Field(description="准确的 MCP Server 名称")
    uri: str = Field(description="准确的 MCP 资源 URI")
    intent: str = Field(description="本次 MCP 资源读取的简短目的，用于上下文虚拟化元数据")


class GetPromptParams(BaseModel):
    server: str = Field(description="准确的 MCP Server 名称")
    prompt: str = Field(description="准确的 MCP Prompt 名称")
    arguments: dict[str, Any] = Field(default_factory=dict, description="MCP Prompt 参数")
    intent: str = Field(description="本次 MCP Prompt 获取的简短目的，用于上下文虚拟化元数据")


class CallMCPToolTool(Tool):
    name = "call_mcp_tool"
    description = (
        "调用已配置 MCP Server 中的一个工具，并提供简短 intent。调用前必须先通过 list_mcp_tools 或 search_mcp_tools "
        "实际查看该工具的名称、描述和参数元数据；只读工具可以直接执行，写入、危险或未知工具需要用户批准。"
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
            return ToolResult(output="MCP 工具调用需要提供简短 intent。", is_error=True)
        if self._manager.is_direct_tool_server(params.server):
            return ToolResult(
                output="Playwright 工具已直接注册为本地 Tool，请调用对应 browser_* 工具。",
                is_error=True,
            )
        cached_metadata = self._manager.cached_tool_payload(params.server, params.tool)
        if not self._manager.discovery_gate.allows(params.server, params.tool, cached_metadata):
            return _discovery_required_result(params.server, params.tool)
        config = self._manager.server_configs.get(params.server)
        try:
            live_metadata = await self._manager.live_tool_metadata(params.server, params.tool)
        except Exception:
            live_metadata = {}
        current_metadata = self._manager.cached_tool_payload(params.server, params.tool)
        if not self._manager.discovery_gate.allows(params.server, params.tool, current_metadata):
            return _discovery_required_result(params.server, params.tool, metadata_changed=True)
        risk = self._policy.classify(
            server_config=config,
            tool_name=params.tool,
            tool_metadata=live_metadata,
        )
        approval = "auto_allowed_read"
        if self._policy.requires_approval(risk):
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
    name = "read_mcp_resource"
    description = "根据 URI 从已配置的 Server 读取一个 MCP 资源，并提供简短 intent。"
    params_model = ReadResourceParams
    category = "read"
    is_concurrency_safe = False
    is_system_tool = True

    def __init__(self, manager: MCPClientManager) -> None:
        self._manager = manager

    async def execute(self, params: ReadResourceParams) -> ToolResult:
        intent = _compact_intent(params.intent)
        if not intent:
            return ToolResult(output="MCP 资源读取需要提供简短 intent。", is_error=True)
        if self._manager.is_direct_tool_server(params.server):
            return ToolResult(output="Playwright 不通过 MCP resource 提供给模型。", is_error=True)
        result = await self._manager.read_resource(params.server, params.uri)
        payload = result.to_payload()
        payload["intent"] = intent
        payload["risk"] = "read"
        payload["approval"] = "auto_allowed"
        payload["mcp_server"] = params.server
        payload["mcp_resource"] = params.uri
        return _json_result(payload, is_error=result.is_error)


class GetMCPPromptTool(Tool):
    name = "get_mcp_prompt"
    description = "根据名称从已配置的 Server 获取一个 MCP Prompt，并提供简短 intent。"
    params_model = GetPromptParams
    category = "read"
    is_concurrency_safe = False
    is_system_tool = True

    def __init__(self, manager: MCPClientManager) -> None:
        self._manager = manager

    async def execute(self, params: GetPromptParams) -> ToolResult:
        intent = _compact_intent(params.intent)
        if not intent:
            return ToolResult(output="获取 MCP Prompt 需要提供简短 intent。", is_error=True)
        if self._manager.is_direct_tool_server(params.server):
            return ToolResult(output="Playwright 不通过 MCP prompt 提供给模型。", is_error=True)
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
    if len(text) <= MAX_TOOL_INTENT_CHARS:
        return text
    return text[:MAX_TOOL_INTENT_CHARS]


def _discovery_required_result(server: str, tool: str, *, metadata_changed: bool = False) -> ToolResult:
    message = (
        "MCP 工具元数据已变化，必须重新查看名称、描述和参数元数据。"
        if metadata_changed
        else "调用 MCP 工具前必须先查看该工具的名称、描述和参数元数据。"
    )
    return _json_result(
        {
            "error": message,
            "error_code": "mcp_tool_metadata_changed" if metadata_changed else "mcp_tool_not_discovered",
            "server": server,
            "tool": tool,
            "required_discovery": [
                {"tool": "search_mcp_tools", "arguments": {"server": server, "query": tool}},
                {"tool": "list_mcp_tools", "arguments": {"server": server}},
            ],
        },
        is_error=True,
    )


def _json_result(payload: dict[str, Any], *, is_error: bool = False) -> ToolResult:
    return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2, default=str), is_error=is_error)
