from __future__ import annotations

import time
import hashlib
import json
import sqlite3
from dataclasses import asdict
from dataclasses import dataclass, field
from pathlib import Path

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
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._entries: dict[str, MCPMetadataEntry] = {}
        self._db_path = Path(db_path).expanduser() if db_path else None
        if self._db_path is not None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mcp_metadata_cache (
                        server_name TEXT PRIMARY KEY,
                        config_hash TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    )
                    """
                )

    def sync_configs(self, configs: dict[str, MCPServerConfig]) -> None:
        entries: dict[str, MCPMetadataEntry] = {}
        for name, config in configs.items():
            existing = self._entries.get(name)
            if existing is None or existing.config != config:
                entries[name] = self._load_entry(config) or MCPMetadataEntry(config=config)
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
        self._persist(entry)

    def mark_error(self, server: str, error: str) -> None:
        entry = self._entries.get(server)
        if entry is None:
            return
        entry.connected = False
        entry.available = False
        entry.error = error
        entry.updated_at = time.time()
        self._persist(entry)

    def mark_available(self, server: str) -> None:
        entry = self._entries.get(server)
        if entry is None:
            return
        entry.available = True
        entry.error = ""
        entry.updated_at = time.time()
        self._persist(entry)

    def unavailable_servers(self) -> list[str]:
        return [
            entry.config.name
            for entry in sorted(self._entries.values(), key=lambda item: item.config.name)
            if not entry.available
        ]

    def _connect(self) -> sqlite3.Connection:
        if self._db_path is None:
            raise RuntimeError("persistent MCP cache is disabled")
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _config_hash(config: MCPServerConfig) -> str:
        payload = json.dumps(asdict(config), ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load_entry(self, config: MCPServerConfig) -> MCPMetadataEntry | None:
        if self._db_path is None:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT config_hash, payload_json, updated_at FROM mcp_metadata_cache WHERE server_name = ?",
                (config.name,),
            ).fetchone()
        if row is None or row["config_hash"] != self._config_hash(config):
            return None
        try:
            payload = json.loads(row["payload_json"])
            return MCPMetadataEntry(
                config=config,
                tools=[MCPItemSummary(**item) for item in payload.get("tools", [])],
                resources=[MCPItemSummary(**item) for item in payload.get("resources", [])],
                prompts=[MCPItemSummary(**item) for item in payload.get("prompts", [])],
                connected=False,
                available=True,
                updated_at=float(row["updated_at"]),
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _persist(self, entry: MCPMetadataEntry) -> None:
        if self._db_path is None:
            return
        payload = {
            "tools": [asdict(item) for item in entry.tools],
            "resources": [asdict(item) for item in entry.resources],
            "prompts": [asdict(item) for item in entry.prompts],
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mcp_metadata_cache(server_name, config_hash, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(server_name) DO UPDATE SET
                    config_hash=excluded.config_hash,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    entry.config.name,
                    self._config_hash(entry.config),
                    json.dumps(payload, ensure_ascii=False, default=str),
                    entry.updated_at,
                ),
            )
