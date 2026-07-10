from __future__ import annotations

import time
from dataclasses import dataclass, field

from mycodingagent.mcp_integration.config import MCPServerConfig
from mycodingagent.mcp_integration.models import MCPItemSummary, MCPServerSummary


@dataclass
class MCPMetadataEntry:
    config: MCPServerConfig
    tools: list[MCPItemSummary] = field(default_factory=list)
    resources: list[MCPItemSummary] = field(default_factory=list)
    prompts: list[MCPItemSummary] = field(default_factory=list)
    connected: bool = False
    available: bool = True
    error: str = ""
    updated_at: float = 0.0

    def summary(self) -> MCPServerSummary:
        return MCPServerSummary(
            name=self.config.name,
            description=self.config.description,
            tags=self.config.tags,
            aliases=self.config.aliases,
            abbreviations=self.config.abbreviations,
            synonyms=self.config.synonyms,
            keywords=self.config.keywords,
            available=self.available,
            error=self.error,
            tools_count=len(self.tools),
            resources_count=len(self.resources),
            prompts_count=len(self.prompts),
            updated_at=self.updated_at,
        )


class MCPMetadataCache:
    def __init__(self) -> None:
        self._entries: dict[str, MCPMetadataEntry] = {}

    def sync_configs(self, configs: dict[str, MCPServerConfig]) -> None:
        entries: dict[str, MCPMetadataEntry] = {}
        for name, config in configs.items():
            existing = self._entries.get(name)
            if existing is None or existing.config != config:
                entries[name] = MCPMetadataEntry(config=config)
            else:
                entries[name] = existing
        self._entries = entries

    def get(self, server: str) -> MCPMetadataEntry | None:
        return self._entries.get(server)

    def servers(self) -> list[MCPServerSummary]:
        return [entry.summary() for entry in sorted(self._entries.values(), key=lambda item: item.config.name)]

    def update_discovery(
        self,
        server: str,
        *,
        tools: list[MCPItemSummary] | None = None,
        resources: list[MCPItemSummary] | None = None,
        prompts: list[MCPItemSummary] | None = None,
        connected: bool = True,
        error: str = "",
    ) -> None:
        entry = self._entries.get(server)
        if entry is None:
            return
        if tools is not None:
            entry.tools = tools
        if resources is not None:
            entry.resources = resources
        if prompts is not None:
            entry.prompts = prompts
        entry.connected = connected
        entry.error = error
        entry.available = not error
        entry.updated_at = time.time()

    def mark_error(self, server: str, error: str) -> None:
        entry = self._entries.get(server)
        if entry is None:
            return
        entry.connected = False
        entry.available = False
        entry.error = error
        entry.updated_at = time.time()

    def mark_available(self, server: str) -> None:
        entry = self._entries.get(server)
        if entry is None:
            return
        entry.available = True
        entry.error = ""
        entry.updated_at = time.time()

    def unavailable_servers(self) -> list[str]:
        return [
            entry.config.name
            for entry in sorted(self._entries.values(), key=lambda item: item.config.name)
            if not entry.available
        ]
