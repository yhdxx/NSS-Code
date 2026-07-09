from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

from mcp_client.cache import MCPMetadataCache
from mcp_client.config import MCPConfigLoader, MCPServerConfig
from mcp_client.execution import normalize_mcp_result
from mcp_client.models import MCPExecutionResult, MCPItemSummary, MCPServerSummary


class MCPClientManager:
    """Own real MCP protocol connections, discovery metadata, and protocol calls."""

    def __init__(
        self,
        *,
        config_loader: MCPConfigLoader | None = None,
        metadata_cache: MCPMetadataCache | None = None,
    ) -> None:
        self.config_loader = config_loader or MCPConfigLoader()
        self.metadata_cache = metadata_cache or MCPMetadataCache()
        self.server_configs: dict[str, MCPServerConfig] = {}
        self._sessions: dict[str, Any] = {}
        self._session_contexts: dict[str, Any] = {}

    async def initialize(self) -> None:
        self.reload_config()

    def reload_config(self) -> None:
        self.server_configs = self.config_loader.load()
        self.metadata_cache.sync_configs(self.server_configs)

    async def close(self) -> None:
        for server in list(self._sessions):
            await self._close_session(server)

    def server_count(self) -> int:
        return len(self.server_configs)

    def connected_count(self) -> int:
        return sum(1 for server in self.metadata_cache.servers() if server.connected)

    def list_servers(self) -> list[MCPServerSummary]:
        return self.metadata_cache.servers()

    async def refresh_server(self, server: str) -> MCPServerSummary | None:
        if server not in self.server_configs:
            return None
        try:
            await self._ensure_session(server)
            tools = await self._list_tools_from_session(server)
            resources = await self._list_resources_from_session(server)
            prompts = await self._list_prompts_from_session(server)
            self.metadata_cache.update_discovery(
                server,
                tools=tools,
                resources=resources,
                prompts=prompts,
                connected=True,
                error="",
            )
        except Exception as exc:
            self.metadata_cache.mark_error(server, str(exc))
        entry = self.metadata_cache.get(server)
        return entry.summary() if entry is not None else None

    async def list_tools(self, server: str) -> dict[str, Any]:
        summary = await self._ensure_discovered(server)
        entry = self.metadata_cache.get(server)
        if summary is None or entry is None:
            return {"error": f"MCP server not found: {server}", "tools": []}
        return {"server": summary.to_payload(), "tools": [item.to_payload() for item in entry.tools]}

    async def list_resources(self, server: str) -> dict[str, Any]:
        summary = await self._ensure_discovered(server)
        entry = self.metadata_cache.get(server)
        if summary is None or entry is None:
            return {"error": f"MCP server not found: {server}", "resources": []}
        return {"server": summary.to_payload(), "resources": [item.to_payload() for item in entry.resources]}

    async def list_prompts(self, server: str) -> dict[str, Any]:
        summary = await self._ensure_discovered(server)
        entry = self.metadata_cache.get(server)
        if summary is None or entry is None:
            return {"error": f"MCP server not found: {server}", "prompts": []}
        return {"server": summary.to_payload(), "prompts": [item.to_payload() for item in entry.prompts]}

    async def call_tool(self, server: str, tool: str, arguments: dict[str, Any] | None = None) -> MCPExecutionResult:
        if server not in self.server_configs:
            return MCPExecutionResult(server=server, operation="tool", name=tool, is_error=True, content_text=f"MCP server not found: {server}", content_type="error")
        session = await self._ensure_session(server)
        try:
            result = await session.call_tool(tool, arguments or {})
        except Exception as exc:
            return MCPExecutionResult(server=server, operation="tool", name=tool, is_error=True, content_text=f"MCP tool call failed: {exc}", content_type="error")
        return normalize_mcp_result(server=server, operation="tool", name=tool, result=result)

    async def read_resource(self, server: str, uri: str) -> MCPExecutionResult:
        if server not in self.server_configs:
            return MCPExecutionResult(server=server, operation="resource", name=uri, is_error=True, content_text=f"MCP server not found: {server}", content_type="error")
        session = await self._ensure_session(server)
        try:
            result = await session.read_resource(uri)
        except Exception as exc:
            return MCPExecutionResult(server=server, operation="resource", name=uri, is_error=True, content_text=f"MCP resource read failed: {exc}", content_type="error")
        return normalize_mcp_result(server=server, operation="resource", name=uri, result=result)

    async def get_prompt(self, server: str, prompt: str, arguments: dict[str, Any] | None = None) -> MCPExecutionResult:
        if server not in self.server_configs:
            return MCPExecutionResult(server=server, operation="prompt", name=prompt, is_error=True, content_text=f"MCP server not found: {server}", content_type="error")
        session = await self._ensure_session(server)
        try:
            result = await session.get_prompt(prompt, arguments or {})
        except Exception as exc:
            return MCPExecutionResult(server=server, operation="prompt", name=prompt, is_error=True, content_text=f"MCP prompt get failed: {exc}", content_type="error")
        return normalize_mcp_result(server=server, operation="prompt", name=prompt, result=result)

    async def _ensure_discovered(self, server: str) -> MCPServerSummary | None:
        entry = self.metadata_cache.get(server)
        if entry is None:
            return None
        if entry.updated_at > 0 and not entry.error:
            return entry.summary()
        return await self.refresh_server(server)

    async def _ensure_session(self, server: str) -> Any:
        existing = self._sessions.get(server)
        if existing is not None:
            return existing
        config = self.server_configs[server]
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:
            raise RuntimeError("Python package 'mcp' is required for real MCP discovery") from exc

        env = os.environ.copy()
        env.update(config.env)
        env.setdefault("npm_config_cache", "/tmp/mycodingagent-npm-cache")
        params = StdioServerParameters(command=config.command, args=list(config.args), env=env)
        stdio_context = stdio_client(params)
        session_context = None
        try:
            read_stream, write_stream = await stdio_context.__aenter__()
            session_context = ClientSession(read_stream, write_stream)
            session = await session_context.__aenter__()
            await session.initialize()
            self._session_contexts[server] = (session_context, stdio_context)
            self._sessions[server] = session
            return session
        except Exception:
            if session_context is not None:
                with contextlib.suppress(Exception):
                    await session_context.__aexit__(None, None, None)
            with contextlib.suppress(Exception):
                await stdio_context.__aexit__(None, None, None)
            raise

    async def _close_session(self, server: str) -> None:
        self._sessions.pop(server, None)
        contexts = self._session_contexts.pop(server, None)
        if contexts is None:
            return
        session_context, stdio_context = contexts
        with contextlib.suppress(Exception):
            await session_context.__aexit__(None, None, None)
        with contextlib.suppress(Exception):
            await stdio_context.__aexit__(None, None, None)

    async def _list_tools_from_session(self, server: str) -> list[MCPItemSummary]:
        session = await self._ensure_session(server)
        result = await session.list_tools()
        return [_item_summary(item) for item in getattr(result, "tools", [])]

    async def _list_resources_from_session(self, server: str) -> list[MCPItemSummary]:
        session = await self._ensure_session(server)
        with contextlib.suppress(Exception):
            result = await session.list_resources()
            return [_item_summary(item) for item in getattr(result, "resources", [])]
        return []

    async def _list_prompts_from_session(self, server: str) -> list[MCPItemSummary]:
        session = await self._ensure_session(server)
        with contextlib.suppress(Exception):
            result = await session.list_prompts()
            return [_item_summary(item) for item in getattr(result, "prompts", [])]
        return []


def _item_summary(item: Any) -> MCPItemSummary:
    uri = str(getattr(item, "uri", "") or "")
    raw_name = str(getattr(item, "name", "") or "")
    name = uri or raw_name
    description = str(getattr(item, "description", "") or "")
    metadata: dict[str, Any] = {}
    if raw_name and raw_name != name:
        metadata["name"] = raw_name
    for key in ("uri", "mimeType", "title"):
        value = getattr(item, key, None)
        if value:
            metadata[key] = str(value)
    return MCPItemSummary(name=name, description=description, metadata=metadata)
