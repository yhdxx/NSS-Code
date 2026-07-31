from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from mycodingagent.capability_discovery import CapabilityRouter
from mycodingagent.mcp_integration import MCPClientManager
from mycodingagent.tool_runtime.base import Tool, ToolResult

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class PaginationParams(BaseModel):
    offset: int = Field(default=0, ge=0, description="结果偏移量，从 0 开始")
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="最多返回的结果数量")


class ServerSearchParams(PaginationParams):
    query: str = Field(description="用于搜索 MCP Server 的能力、服务或任务描述")


class ServerNameParams(PaginationParams):
    server: str = Field(description="准确的 MCP Server 名称")


class ServerItemSearchParams(ServerNameParams):
    query: str = Field(description="要搜索的工具、资源或 Prompt 名称或描述")


class _ServerItemsTool(Tool):
    params_model = ServerNameParams
    category = "read"
    is_concurrency_safe = False
    is_system_tool = True
    item_key: Literal["tools", "resources", "prompts"]
    list_method: str

    def __init__(self, manager: MCPClientManager, router: CapabilityRouter | None = None) -> None:
        self._manager = manager
        self._router = router

    async def execute(self, params: ServerNameParams) -> ToolResult:
        if self._router is not None:
            self._router.record_mcp_server_use(params.server, reward=0.3)
        method = getattr(self._manager, self.list_method)
        result = await method(params.server)
        if result.get("error"):
            return _json_result(result, is_error=True)
        payload = {
            "server": result.get("server", {}),
            **_paginate(result.get(self.item_key, []), offset=params.offset, limit=params.limit, item_key=self.item_key),
        }
        if self.item_key == "tools":
            self._manager.discovery_gate.record_tools(params.server, payload["tools"])
        return _json_result(payload)


class _ServerItemSearchTool(_ServerItemsTool):
    params_model = ServerItemSearchParams

    async def execute(self, params: ServerItemSearchParams) -> ToolResult:
        if self._router is not None:
            self._router.record_mcp_server_use(params.server, reward=0.5)
        method = getattr(self._manager, self.list_method)
        result = await method(params.server)
        if result.get("error"):
            return _json_result(result, is_error=True)
        matches = _search_items(params.query, result.get(self.item_key, []))
        payload = {
            "server": result.get("server", {}),
            **_paginate(matches, offset=params.offset, limit=params.limit, item_key=self.item_key),
        }
        if self.item_key == "tools":
            self._manager.discovery_gate.record_tools(params.server, payload["tools"])
        return _json_result(payload)


class ListServersTool(Tool):
    name = "list_mcp_servers"
    description = (
        "列出已配置的 MCP Server、元数据和可用状态。本操作不会连接 Server，也不能证明当前已连接。"
        "available=true 表示 Server 可用或尚未发生失败；使用 list_mcp_tools、list_mcp_resources "
        "或 list_mcp_prompts 探测 discovery。"
        "支持 offset/limit 分页。"
    )
    params_model = PaginationParams
    category = "read"
    is_concurrency_safe = True
    is_system_tool = True

    def __init__(self, manager: MCPClientManager) -> None:
        self._manager = manager

    async def execute(self, params: PaginationParams) -> ToolResult:
        servers = [server.to_payload() for server in self._manager.list_servers()]
        return _json_result(_paginate(servers, offset=params.offset, limit=params.limit, item_key="servers"))


class SearchServersTool(Tool):
    name = "search_mcp_servers"
    description = (
        "按名称、描述、标签、别名、缩写、同义词和多语言关键词搜索已配置的 MCP Server。"
        "支持 offset/limit 分页。"
    )
    params_model = ServerSearchParams
    category = "read"
    is_concurrency_safe = True
    is_system_tool = True

    def __init__(self, router: CapabilityRouter) -> None:
        self._router = router

    async def execute(self, params: ServerSearchParams) -> ToolResult:
        result = await self._router.route(params.query)
        servers = [
            item.to_payload()
            for item in result.recommendations
            if item.kind == "mcp_server"
        ]
        return _json_result(
            {
                **_paginate(servers, offset=params.offset, limit=params.limit, item_key="servers"),
                "mcp_server_total_count": result.mcp_server_total_count,
                "note": result.note,
            }
        )


class ListToolsTool(_ServerItemsTool):
    name = "list_mcp_tools"
    description = (
        "列出一个 MCP Server 暴露的工具、描述和参数元数据，不会执行工具。只有本次实际返回的工具才满足 "
        "call_mcp_tool 的调用前发现门禁；支持 offset/limit 分页。"
    )
    item_key = "tools"
    list_method = "list_tools"


class SearchToolsTool(_ServerItemSearchTool):
    name = "search_mcp_tools"
    description = (
        "按名称或描述搜索一个 MCP Server 暴露的工具元数据，不会执行工具。只有本次实际返回的工具才满足 "
        "call_mcp_tool 的调用前发现门禁；支持 offset/limit 分页。"
    )
    item_key = "tools"
    list_method = "list_tools"


class ListResourcesTool(_ServerItemsTool):
    name = "list_mcp_resources"
    description = "列出一个 MCP Server 暴露的资源摘要，不会读取资源内容。支持 offset/limit 分页。"
    item_key = "resources"
    list_method = "list_resources"


class SearchResourcesTool(_ServerItemSearchTool):
    name = "search_mcp_resources"
    description = "搜索一个 MCP Server 暴露的资源摘要，不会读取资源内容。支持 offset/limit 分页。"
    item_key = "resources"
    list_method = "list_resources"


class ListPromptsTool(_ServerItemsTool):
    name = "list_mcp_prompts"
    description = "列出一个 MCP Server 暴露的 Prompt 摘要，不会读取 Prompt 内容。支持 offset/limit 分页。"
    item_key = "prompts"
    list_method = "list_prompts"


class SearchPromptsTool(_ServerItemSearchTool):
    name = "search_mcp_prompts"
    description = "搜索一个 MCP Server 暴露的 Prompt 摘要，不会读取 Prompt 内容。支持 offset/limit 分页。"
    item_key = "prompts"
    list_method = "list_prompts"


def register_mcp_discovery_tools(
    registry,
    *,
    manager: MCPClientManager,
    router: CapabilityRouter,
) -> None:
    registry.register(ListServersTool(manager))
    registry.register(SearchServersTool(router))
    registry.register(ListToolsTool(manager, router))
    registry.register(SearchToolsTool(manager, router))
    registry.register(ListResourcesTool(manager, router))
    registry.register(SearchResourcesTool(manager, router))
    registry.register(ListPromptsTool(manager, router))
    registry.register(SearchPromptsTool(manager, router))


def _search_items(query: str, items: list[dict]) -> list[dict]:
    query_terms = {term.lower() for term in query.replace("_", " ").split() if term.strip()}
    if not query_terms:
        return list(items)
    scored: list[tuple[float, dict]] = []
    for item in items:
        haystack = f"{item.get('name', '')} {item.get('description', '')} {item.get('metadata', '')}".lower()
        score = sum(1.0 for term in query_terms if term in haystack)
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("name", ""))))
    return [item for _, item in scored]


def _paginate(items: list[dict], *, offset: int, limit: int, item_key: str) -> dict:
    total = len(items)
    safe_offset = max(0, offset)
    safe_limit = min(max(1, limit), MAX_LIMIT)
    page = items[safe_offset : safe_offset + safe_limit]
    next_offset = safe_offset + len(page)
    has_more = next_offset < total
    return {
        "count": len(page),
        "total": total,
        "offset": safe_offset,
        "limit": safe_limit,
        "has_more": has_more,
        "next_offset": next_offset if has_more else None,
        item_key: page,
    }


def _json_result(payload: dict, *, is_error: bool = False) -> ToolResult:
    return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2), is_error=is_error)
