from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from time import time

from memory.context_objects import ContextContentType, ContextLifecycleState, RecoverableContextObject
from memory.models import (
    CheckpointRecord,
    ConversationSnapshot,
    HistoricalTurn,
    HistoricalSessionRef,
    SessionListItem,
    SessionState,
    SnapshotDelta,
    ToolInvocationMetadata,
    ToolOutputRecord,
)


class SQLiteMemoryStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_accessed_at REAL NOT NULL DEFAULT 0,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latest_context_json TEXT NOT NULL DEFAULT '[]',
                    latest_lrfu_json TEXT NOT NULL DEFAULT '{}',
                    latest_file_state_json TEXT NOT NULL DEFAULT '{}',
                    workspace_root TEXT NOT NULL DEFAULT '',
                    workspace_label TEXT NOT NULL DEFAULT '',
                    workspace_fingerprint TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._ensure_column(conn, "sessions", "last_accessed_at", "REAL NOT NULL DEFAULT 0")
            conn.execute("UPDATE sessions SET last_accessed_at = updated_at WHERE last_accessed_at = 0")
            self._ensure_column(conn, "sessions", "latest_file_state_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "sessions", "workspace_root", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "sessions", "workspace_label", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "sessions", "workspace_fingerprint", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_messages (
                    session_id TEXT NOT NULL,
                    message_index INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (session_id, message_index)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_tool_outputs (
                    output_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool_call_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    output_text TEXT NOT NULL,
                    output_size INTEGER NOT NULL,
                    reproducible INTEGER NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_turns (
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    user_content TEXT NOT NULL,
                    assistant_content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (session_id, turn_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_invocation_metadata (
                    metadata_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    call_index INTEGER NOT NULL,
                    tool_call_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    context_id TEXT NOT NULL,
                    invocation_kind TEXT NOT NULL,
                    args_preview TEXT NOT NULL,
                    args_hash TEXT NOT NULL,
                    short_summary TEXT NOT NULL,
                    keywords_json TEXT NOT NULL DEFAULT '[]',
                    related_files_json TEXT NOT NULL DEFAULT '[]',
                    reference_paths_json TEXT NOT NULL DEFAULT '[]',
                    content_type TEXT NOT NULL,
                    content_length INTEGER NOT NULL,
                    token_count INTEGER NOT NULL,
                    reproducible INTEGER NOT NULL,
                    is_error INTEGER NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recoverable_contexts (
                    context_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool_call_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    storage_key TEXT NOT NULL,
                    short_summary TEXT NOT NULL,
                    keywords_json TEXT NOT NULL DEFAULT '[]',
                    entities_json TEXT NOT NULL DEFAULT '[]',
                    related_files_json TEXT NOT NULL DEFAULT '[]',
                    timestamp REAL NOT NULL,
                    reproducible INTEGER NOT NULL,
                    token_count INTEGER NOT NULL,
                    source_tool TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    content_length INTEGER NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    last_accessed_at REAL NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    content_text TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_context_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    compressed_messages_json TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    pressure_ratio REAL NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    snapshot_version TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    previous_snapshot_id TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshot_deltas (
                    delta_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    base_snapshot_id TEXT NOT NULL,
                    turn_start_index INTEGER NOT NULL,
                    turn_end_index INTEGER NOT NULL,
                    delta_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoint_records (
                    checkpoint_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    previous_snapshot_id TEXT NOT NULL,
                    trigger_reason TEXT NOT NULL,
                    usage_ratio REAL NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_session_refs (
                    session_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    session_summary TEXT NOT NULL,
                    recoverable_context_refs_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_accessed_at REAL NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON session_messages(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_outputs_session ON session_tool_outputs(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_historical_turns_session ON historical_turns(session_id, turn_index)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_metadata_session ON tool_invocation_metadata(session_id, turn_index)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_metadata_context ON tool_invocation_metadata(context_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recoverable_contexts_session ON recoverable_contexts(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recoverable_contexts_tool_call ON recoverable_contexts(tool_call_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_context_snapshots_session ON session_context_snapshots(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversation_snapshots_session ON conversation_snapshots(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_deltas_session ON snapshot_deltas(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoint_records_session ON checkpoint_records(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_workspace_root ON sessions(workspace_root)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_workspace_fingerprint ON sessions(workspace_fingerprint)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_accessed_at ON sessions(last_accessed_at)")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def ensure_session(
        self,
        *,
        session_id: str,
        model: str,
        status: str = "active",
        workspace_root: str = "",
        workspace_label: str = "",
        workspace_fingerprint: str = "",
    ) -> None:
        now = time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(
                    session_id, created_at, updated_at, last_accessed_at, model, status,
                    workspace_root, workspace_label, workspace_fingerprint
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    last_accessed_at=excluded.last_accessed_at,
                    model=excluded.model,
                    status=CASE
                        WHEN sessions.status = 'historical' AND excluded.status = 'active' THEN sessions.status
                        ELSE excluded.status
                    END,
                    workspace_root=CASE WHEN excluded.workspace_root != '' THEN excluded.workspace_root ELSE sessions.workspace_root END,
                    workspace_label=CASE WHEN excluded.workspace_label != '' THEN excluded.workspace_label ELSE sessions.workspace_label END,
                    workspace_fingerprint=CASE WHEN excluded.workspace_fingerprint != '' THEN excluded.workspace_fingerprint ELSE sessions.workspace_fingerprint END
                """,
                (
                    session_id,
                    now,
                    now,
                    now,
                    model,
                    status,
                    workspace_root,
                    workspace_label,
                    workspace_fingerprint,
                ),
            )

    def save_messages(self, *, session_id: str, messages: list[dict]) -> None:
        now = time()
        with self._connect() as conn:
            if self._session_status(conn, session_id) == "historical":
                return
            conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
            conn.executemany(
                """
                INSERT INTO session_messages(session_id, message_index, role, content_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        session_id,
                        index,
                        str(message.get("role", "")),
                        json.dumps(message, ensure_ascii=False),
                        now,
                    )
                    for index, message in enumerate(messages)
                ],
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ?, last_accessed_at = ? WHERE session_id = ?",
                (now, now, session_id),
            )

    def _session_status(self, conn: sqlite3.Connection, session_id: str) -> str | None:
        row = conn.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return str(row["status"]) if row is not None else None

    def load_messages(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT content_json FROM session_messages
                WHERE session_id = ?
                ORDER BY message_index
                """,
                (session_id,),
            ).fetchall()
        return [json.loads(row["content_json"]) for row in rows]

    def save_historical_turns(self, *, session_id: str, turns: list[HistoricalTurn]) -> None:
        now = time()
        with self._connect() as conn:
            if self._session_status(conn, session_id) == "historical":
                return
            conn.execute("DELETE FROM historical_turns WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM tool_invocation_metadata WHERE session_id = ?", (session_id,))
            for turn in turns:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO historical_turns(
                        session_id, turn_id, turn_index, user_content, assistant_content, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        turn.turn_id,
                        turn.turn_index,
                        turn.user_content,
                        turn.assistant_content,
                        turn.created_at,
                    ),
                )
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO tool_invocation_metadata(
                        metadata_id, session_id, turn_id, turn_index, call_index,
                        tool_call_id, tool_name, kind, context_id, invocation_kind,
                        args_preview, args_hash, short_summary, keywords_json,
                        related_files_json, reference_paths_json, content_type,
                        content_length, token_count, reproducible, is_error, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            metadata.metadata_id,
                            metadata.session_id,
                            metadata.turn_id,
                            metadata.turn_index,
                            metadata.call_index,
                            metadata.tool_call_id,
                            metadata.tool_name,
                            metadata.kind,
                            metadata.context_id,
                            metadata.invocation_kind,
                            metadata.args_preview,
                            metadata.args_hash,
                            metadata.short_summary,
                            json.dumps(metadata.keywords, ensure_ascii=False),
                            json.dumps(metadata.related_files, ensure_ascii=False),
                            json.dumps(metadata.reference_paths, ensure_ascii=False),
                            metadata.content_type,
                            metadata.content_length,
                            metadata.token_count,
                            int(metadata.reproducible),
                            int(metadata.is_error),
                            metadata.created_at,
                        )
                        for metadata in turn.tool_metadata
                    ],
                )
            conn.execute(
                "UPDATE sessions SET updated_at = ?, last_accessed_at = ? WHERE session_id = ?",
                (now, now, session_id),
            )

    def load_historical_turns(self, session_id: str, *, limit: int | None = None) -> list[HistoricalTurn]:
        query = """
            SELECT * FROM historical_turns
            WHERE session_id = ?
            ORDER BY turn_index
        """
        params: list[object] = [session_id]
        if limit is not None:
            query += " LIMIT ?"
            params.append(max(1, limit))
        with self._connect() as conn:
            turn_rows = conn.execute(query, tuple(params)).fetchall()
            metadata_rows = conn.execute(
                """
                SELECT * FROM tool_invocation_metadata
                WHERE session_id = ?
                ORDER BY turn_index, call_index
                """,
                (session_id,),
            ).fetchall()
        metadata_by_turn: dict[str, list[ToolInvocationMetadata]] = {}
        for row in metadata_rows:
            metadata = tool_metadata_from_row(row)
            metadata_by_turn.setdefault(metadata.turn_id, []).append(metadata)
        return [
            HistoricalTurn(
                session_id=row["session_id"],
                turn_id=row["turn_id"],
                turn_index=int(row["turn_index"]),
                user_content=row["user_content"],
                assistant_content=row["assistant_content"],
                tool_metadata=metadata_by_turn.get(row["turn_id"], []),
                created_at=float(row["created_at"]),
            )
            for row in turn_rows
        ]

    def search_historical_turns(self, session_id: str, query: str, *, limit: int = 10) -> list[HistoricalTurn]:
        normalized = " ".join(query.split()).lower()
        if not normalized:
            return []
        matches: list[HistoricalTurn] = []
        for turn in self.load_historical_turns(session_id):
            haystack_parts = [turn.user_content, turn.assistant_content]
            for metadata in turn.tool_metadata:
                haystack_parts.extend(
                    [
                        metadata.tool_name,
                        metadata.short_summary,
                        metadata.args_preview,
                        " ".join(metadata.keywords),
                        " ".join(metadata.related_files),
                        " ".join(metadata.reference_paths),
                    ]
                )
            if normalized in " ".join(haystack_parts).lower():
                matches.append(turn)
            if len(matches) >= limit:
                break
        return matches

    def list_sessions(
        self,
        *,
        limit: int = 20,
        workspace_root: str | None = None,
        workspace_fingerprint: str | None = None,
    ) -> list[SessionListItem]:
        where: list[str] = []
        params: list[object] = []
        if workspace_root is not None:
            where.append("workspace_root = ?")
            params.append(workspace_root)
        if workspace_fingerprint is not None:
            where.append("workspace_fingerprint = ?")
            params.append(workspace_fingerprint)
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT session_id, updated_at, last_accessed_at, workspace_root, workspace_label, workspace_fingerprint
                FROM sessions
                {where_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()

        items: list[SessionListItem] = []
        for row in rows:
            messages = self.load_messages(row["session_id"])
            items.append(
                SessionListItem(
                    session_id=row["session_id"],
                    updated_at=float(row["updated_at"]),
                    last_accessed_at=float(row["last_accessed_at"]),
                    preview=session_preview(messages),
                    message_count=len(messages),
                    workspace_root=row["workspace_root"],
                    workspace_label=row["workspace_label"],
                    workspace_fingerprint=row["workspace_fingerprint"],
                )
            )
        return items

    def save_tool_output(self, record: ToolOutputRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO session_tool_outputs(
                    output_id, session_id, tool_call_id, tool_name, arguments_json,
                    output_text, output_size, reproducible, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.output_id,
                    record.session_id,
                    record.tool_call_id,
                    record.tool_name,
                    record.arguments_json,
                    record.output_text,
                    record.output_size,
                    int(record.reproducible),
                    record.created_at,
                ),
            )

    def save_context(self, context: RecoverableContextObject, content: str) -> str:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO recoverable_contexts(
                    context_id, session_id, tool_call_id, tool_name, storage_key,
                    short_summary, keywords_json, entities_json, related_files_json,
                    timestamp, reproducible, token_count, source_tool, content_type,
                    content_length, lifecycle_state, access_count, last_accessed_at,
                    metadata_json, content_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    context.id,
                    context.session_id,
                    context.tool_call_id,
                    context.tool_name,
                    context.storage_key,
                    context.short_summary,
                    json.dumps(context.keywords, ensure_ascii=False),
                    json.dumps(context.entities, ensure_ascii=False),
                    json.dumps(context.related_files, ensure_ascii=False),
                    context.timestamp,
                    int(context.reproducible),
                    context.token_count,
                    context.source_tool,
                    context.content_type.value,
                    context.content_length,
                    context.lifecycle_state.value,
                    context.access_count,
                    context.last_accessed_at,
                    json.dumps(context.metadata, ensure_ascii=False, default=str),
                    content,
                ),
            )
        return context.storage_key

    def load_context(self, context_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content_text FROM recoverable_contexts WHERE context_id = ?",
                (context_id,),
            ).fetchone()
            if row is None:
                return None
            self._touch_context(conn, context_id)
            return row["content_text"]

    def load_partial_context(self, context_id: str, *, offset: int = 0, limit: int = 12000) -> tuple[str, int | None] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content_text FROM recoverable_contexts WHERE context_id = ?",
                (context_id,),
            ).fetchone()
            if row is None:
                return None
            content = row["content_text"]
            start = min(max(0, offset), len(content))
            end = min(start + max(1, limit), len(content))
            self._touch_context(conn, context_id)
        return content[start:end], end if end < len(content) else None

    def delete_context(self, context_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM recoverable_contexts WHERE context_id = ?", (context_id,))
            return cursor.rowcount > 0

    def query_metadata(self, context_id: str) -> RecoverableContextObject | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM recoverable_contexts WHERE context_id = ?",
                (context_id,),
            ).fetchone()
        return context_from_row(row) if row is not None else None

    def search_metadata(self, session_id: str, query: str = "", *, limit: int = 20) -> list[RecoverableContextObject]:
        normalized = " ".join(query.split()).lower()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM recoverable_contexts
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session_id, max(1, limit * 5)),
            ).fetchall()
        contexts = [context_from_row(row) for row in rows]
        if not normalized:
            return contexts[:limit]
        matches: list[RecoverableContextObject] = []
        for context in contexts:
            haystack = " ".join(
                [
                    context.tool_name,
                    context.short_summary,
                    " ".join(context.keywords),
                    " ".join(context.entities),
                    " ".join(context.related_files),
                ]
            ).lower()
            if normalized in haystack:
                matches.append(context)
            if len(matches) >= limit:
                break
        return matches

    def _touch_context(self, conn: sqlite3.Connection, context_id: str) -> None:
        conn.execute(
            """
            UPDATE recoverable_contexts
            SET access_count = access_count + 1, last_accessed_at = ?
            WHERE context_id = ?
            """,
            (time(), context_id),
        )

    def get_tool_output(self, output_id: str) -> ToolOutputRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM session_tool_outputs WHERE output_id = ?",
                (output_id,),
            ).fetchone()
        if row is None:
            return None
        return ToolOutputRecord(
            output_id=row["output_id"],
            session_id=row["session_id"],
            tool_call_id=row["tool_call_id"],
            tool_name=row["tool_name"],
            arguments_json=row["arguments_json"],
            output_text=row["output_text"],
            output_size=row["output_size"],
            reproducible=bool(row["reproducible"]),
            created_at=row["created_at"],
        )

    def save_context_snapshot(
        self,
        *,
        snapshot_id: str,
        session_id: str,
        compressed_messages: list[dict],
        summary_text: str,
        pressure_ratio: float,
    ) -> None:
        now = time()
        compressed_json = json.dumps(compressed_messages, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO session_context_snapshots(
                    snapshot_id, session_id, compressed_messages_json,
                    summary_text, pressure_ratio, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (snapshot_id, session_id, compressed_json, summary_text, pressure_ratio, now),
            )
            conn.execute(
                """
                UPDATE sessions
                SET latest_context_json = ?, updated_at = ?, last_accessed_at = ?
                WHERE session_id = ?
                """,
                (compressed_json, now, now, session_id),
            )

    def save_lrfu_snapshot(self, *, session_id: str, lrfu: dict) -> None:
        now = time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET latest_lrfu_json = ?, updated_at = ?, last_accessed_at = ?
                WHERE session_id = ?
                """,
                (json.dumps(lrfu, ensure_ascii=False), now, now, session_id),
            )

    def save_file_state_snapshot(self, *, session_id: str, file_state: dict) -> None:
        now = time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET latest_file_state_json = ?, updated_at = ?, last_accessed_at = ?
                WHERE session_id = ?
                """,
                (json.dumps(file_state, ensure_ascii=False), now, now, session_id),
            )

    def touch_session(self, session_id: str) -> bool:
        now = time()
        with self._connect() as conn:
            if self._session_status(conn, session_id) == "historical":
                cursor = conn.execute(
                    """
                    UPDATE historical_session_refs
                    SET last_accessed_at = ?
                    WHERE session_id = ?
                    """,
                    (now, session_id),
                )
                conn.execute(
                    "UPDATE sessions SET last_accessed_at = ? WHERE session_id = ?",
                    (now, session_id),
                )
                return cursor.rowcount > 0
            cursor = conn.execute(
                "UPDATE sessions SET last_accessed_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            return cursor.rowcount > 0

    def delete_session(self, session_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM session_tool_outputs WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM historical_turns WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM tool_invocation_metadata WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM recoverable_contexts WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM session_context_snapshots WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM conversation_snapshots WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM snapshot_deltas WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM checkpoint_records WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM historical_session_refs WHERE session_id = ?", (session_id,))
            return cursor.rowcount > 0

    def delete_expired_sessions(self, *, max_age_seconds: float) -> int:
        cutoff = time() - max_age_seconds
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id FROM sessions WHERE last_accessed_at < ?",
                (cutoff,),
            ).fetchall()
            session_ids = [row["session_id"] for row in rows]
            for session_id in session_ids:
                conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM session_tool_outputs WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM historical_turns WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM tool_invocation_metadata WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM recoverable_contexts WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM session_context_snapshots WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM conversation_snapshots WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM snapshot_deltas WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM checkpoint_records WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM historical_session_refs WHERE session_id = ?", (session_id,))
            return len(session_ids)

    def load_session(self, session_id: str) -> SessionState | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    latest_context_json,
                    latest_lrfu_json,
                    latest_file_state_json,
                    last_accessed_at,
                    workspace_root,
                    workspace_label,
                    workspace_fingerprint
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionState(
            session_id=session_id,
            messages=self.load_messages(session_id),
            historical_turns=self.load_historical_turns(session_id),
            latest_context=json.loads(row["latest_context_json"] or "[]"),
            latest_lrfu=json.loads(row["latest_lrfu_json"] or "{}"),
            latest_file_state=json.loads(row["latest_file_state_json"] or "{}"),
            last_accessed_at=float(row["last_accessed_at"]),
            workspace_root=row["workspace_root"],
            workspace_label=row["workspace_label"],
            workspace_fingerprint=row["workspace_fingerprint"],
        )

    def save_conversation_snapshot(self, snapshot: ConversationSnapshot) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO conversation_snapshots(
                    snapshot_id, snapshot_version, session_id, previous_snapshot_id,
                    snapshot_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.snapshot_version,
                    snapshot.session_id,
                    snapshot.previous_snapshot_id,
                    json.dumps(asdict(snapshot), ensure_ascii=False, default=str),
                    snapshot.created_at,
                ),
            )

    def get_conversation_snapshot(self, snapshot_id: str) -> ConversationSnapshot | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT snapshot_json FROM conversation_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        return conversation_snapshot_from_dict(json.loads(row["snapshot_json"] or "{}"))

    def get_latest_snapshot_for_session(self, session_id: str) -> ConversationSnapshot | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT snapshot_json FROM conversation_snapshots
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return conversation_snapshot_from_dict(json.loads(row["snapshot_json"] or "{}"))

    def save_snapshot_delta(self, delta: SnapshotDelta) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO snapshot_deltas(
                    delta_id, session_id, base_snapshot_id, turn_start_index,
                    turn_end_index, delta_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delta.delta_id,
                    delta.session_id,
                    delta.base_snapshot_id,
                    delta.turn_start_index,
                    delta.turn_end_index,
                    json.dumps(asdict(delta), ensure_ascii=False, default=str),
                    delta.created_at,
                ),
            )

    def save_checkpoint_record(self, record: CheckpointRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO checkpoint_records(
                    checkpoint_id, session_id, snapshot_id, previous_snapshot_id,
                    trigger_reason, usage_ratio, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.checkpoint_id,
                    record.session_id,
                    record.snapshot_id,
                    record.previous_snapshot_id,
                    record.trigger_reason,
                    record.usage_ratio,
                    record.created_at,
                ),
            )

    def mark_session_historical(
        self,
        session_id: str,
        snapshot_id: str,
        summary: str,
        context_refs: list[str],
    ) -> None:
        now = time()
        with self._connect() as conn:
            created_row = conn.execute(
                "SELECT created_at FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            created_at = float(created_row["created_at"]) if created_row is not None else now
            conn.execute(
                """
                UPDATE sessions
                SET status = 'historical', updated_at = ?, last_accessed_at = ?
                WHERE session_id = ?
                """,
                (now, now, session_id),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO historical_session_refs(
                    session_id, snapshot_id, session_summary, recoverable_context_refs_json,
                    created_at, last_accessed_at, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    snapshot_id,
                    summary,
                    json.dumps(context_refs, ensure_ascii=False),
                    created_at,
                    now,
                    "historical",
                ),
            )

    def get_historical_session(self, session_id: str) -> HistoricalSessionRef | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM historical_session_refs WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return historical_session_from_row(row) if row is not None else None

    def list_historical_sessions(self, limit: int = 20) -> list[HistoricalSessionRef]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM historical_session_refs
                ORDER BY last_accessed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [historical_session_from_row(row) for row in rows]

    def touch_historical_session(self, session_id: str) -> bool:
        now = time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE historical_session_refs
                SET last_accessed_at = ?
                WHERE session_id = ?
                """,
                (now, session_id),
            )
            conn.execute(
                "UPDATE sessions SET last_accessed_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            return cursor.rowcount > 0


def session_preview(messages: list[dict], *, max_chars: int = 120) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message_content_to_text(message.get("content", ""))
        if not content or content.strip().lower() == "exit":
            continue
        return truncate_one_line(content, max_chars=max_chars)
    for message in reversed(messages):
        content = message_content_to_text(message.get("content", ""))
        if content:
            return truncate_one_line(content, max_chars=max_chars)
    return "(空会话)"


def message_content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def truncate_one_line(text: str, *, max_chars: int) -> str:
    one_line = " ".join(text.strip().split())
    if len(one_line) <= max_chars:
        return one_line
    return one_line[: max_chars - 1] + "…"


def context_from_row(row: sqlite3.Row) -> RecoverableContextObject:
    return RecoverableContextObject(
        id=row["context_id"],
        session_id=row["session_id"],
        tool_call_id=row["tool_call_id"],
        tool_name=row["tool_name"],
        storage_key=row["storage_key"],
        short_summary=row["short_summary"],
        keywords=json.loads(row["keywords_json"] or "[]"),
        entities=json.loads(row["entities_json"] or "[]"),
        related_files=json.loads(row["related_files_json"] or "[]"),
        timestamp=float(row["timestamp"]),
        reproducible=bool(row["reproducible"]),
        token_count=int(row["token_count"]),
        source_tool=row["source_tool"],
        content_type=ContextContentType(row["content_type"] or ContextContentType.UNKNOWN.value),
        content_length=int(row["content_length"]),
        lifecycle_state=ContextLifecycleState(row["lifecycle_state"] or ContextLifecycleState.EXTERNAL.value),
        access_count=int(row["access_count"]),
        last_accessed_at=float(row["last_accessed_at"]),
        metadata=json.loads(row["metadata_json"] or "{}"),
    )


def tool_metadata_from_row(row: sqlite3.Row) -> ToolInvocationMetadata:
    return ToolInvocationMetadata(
        metadata_id=row["metadata_id"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        turn_index=int(row["turn_index"]),
        call_index=int(row["call_index"]),
        tool_call_id=row["tool_call_id"],
        tool_name=row["tool_name"],
        kind=row["kind"],
        context_id=row["context_id"],
        invocation_kind=row["invocation_kind"],
        args_preview=row["args_preview"],
        args_hash=row["args_hash"],
        short_summary=row["short_summary"],
        keywords=json.loads(row["keywords_json"] or "[]"),
        related_files=json.loads(row["related_files_json"] or "[]"),
        reference_paths=json.loads(row["reference_paths_json"] or "[]"),
        content_type=row["content_type"],
        content_length=int(row["content_length"]),
        token_count=int(row["token_count"]),
        reproducible=bool(row["reproducible"]),
        is_error=bool(row["is_error"]),
        created_at=float(row["created_at"]),
    )


def conversation_snapshot_from_dict(data: dict) -> ConversationSnapshot:
    return ConversationSnapshot(
        snapshot_id=str(data.get("snapshot_id", "")),
        snapshot_version=str(data.get("snapshot_version", "1.0")),
        session_id=str(data.get("session_id", "")),
        previous_snapshot_id=str(data.get("previous_snapshot_id", "")),
        overall_task_summary=str(data.get("overall_task_summary", "")),
        reasoning_conclusions=list(data.get("reasoning_conclusions") or []),
        project_status=str(data.get("project_status", "")),
        unfinished_tasks=list(data.get("unfinished_tasks") or []),
        user_intentions=list(data.get("user_intentions") or []),
        important_decisions=list(data.get("important_decisions") or []),
        recoverable_context_refs=list(data.get("recoverable_context_refs") or []),
        workspace_state=dict(data.get("workspace_state") or {}),
        memory_state=dict(data.get("memory_state") or {}),
        created_at=float(data.get("created_at") or time()),
    )


def historical_session_from_row(row: sqlite3.Row) -> HistoricalSessionRef:
    return HistoricalSessionRef(
        session_id=row["session_id"],
        snapshot_id=row["snapshot_id"],
        session_summary=row["session_summary"],
        recoverable_context_refs=json.loads(row["recoverable_context_refs_json"] or "[]"),
        created_at=float(row["created_at"]),
        last_accessed_at=float(row["last_accessed_at"]),
        status=row["status"],
    )
