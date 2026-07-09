from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from capabilities import CapabilityRouter
from mcp_client import MCPClientManager
from tools.base import Tool, ToolResult

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class PaginationParams(BaseModel):
    offset: int = Field(default=0, ge=0, description="Zero-based result offset")
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Maximum results to return")


class ServerSearchParams(PaginationParams):
    query: str = Field(description="Capability, service, or task to search MCP servers for")


class ServerNameParams(PaginationParams):
    server: str = Field(description="Exact MCP server name")


class ServerItemSearchParams(ServerNameParams):
    query: str = Field(description="Tool, resource, or prompt name/description to search for")


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
        return _json_result(payload)


class ListServersTool(Tool):
    name = "list_servers"
    description = "List configured MCP servers with metadata and connection/discovery status. Supports offset/limit pagination."
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
    name = "search_servers"
    description = (
        "Search configured MCP servers by name, description, tags, aliases, abbreviations, synonyms, "
        "and multilingual keywords. Supports offset/limit pagination."
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
    name = "list_tools"
    description = "List MCP tools exposed by one MCP server. This does not execute tools. Supports offset/limit pagination."
    item_key = "tools"
    list_method = "list_tools"


class SearchToolsTool(_ServerItemSearchTool):
    name = "search_tools"
    description = "Search MCP tool summaries exposed by one MCP server. This does not execute tools. Supports offset/limit pagination."
    item_key = "tools"
    list_method = "list_tools"


class ListResourcesTool(_ServerItemsTool):
    name = "list_resources"
    description = "List MCP resource summaries exposed by one MCP server. This does not read resource contents. Supports offset/limit pagination."
    item_key = "resources"
    list_method = "list_resources"


class SearchResourcesTool(_ServerItemSearchTool):
    name = "search_resources"
    description = "Search MCP resource summaries exposed by one MCP server. This does not read resource contents. Supports offset/limit pagination."
    item_key = "resources"
    list_method = "list_resources"


class ListPromptsTool(_ServerItemsTool):
    name = "list_prompts"
    description = "List MCP prompt summaries exposed by one MCP server. This does not read prompt contents. Supports offset/limit pagination."
    item_key = "prompts"
    list_method = "list_prompts"


class SearchPromptsTool(_ServerItemSearchTool):
    name = "search_prompts"
    description = "Search MCP prompt summaries exposed by one MCP server. This does not read prompt contents. Supports offset/limit pagination."
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
