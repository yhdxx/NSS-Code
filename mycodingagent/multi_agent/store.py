from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from time import time
from typing import Any

from mycodingagent.configuration import CONFIG

from mycodingagent.multi_agent.models import MultiAgentRun, RunStatus, TERMINAL_STATUSES
from mycodingagent.sqlite_utils import SQLITE_CONNECTION_FACTORY


def default_multi_agent_db_path() -> Path:
    return CONFIG.memory.db_path.with_name("multi_agent.sqlite3")


class MultiAgentStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_multi_agent_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, factory=SQLITE_CONNECTION_FACTORY)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS multi_agent_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_multi_agent_runs_status_updated "
                "ON multi_agent_runs(status, updated_at)"
            )

    def save_run(self, run: MultiAgentRun) -> None:
        run.updated_at = time()
        payload = json.dumps(run.to_dict(), ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO multi_agent_runs (run_id, status, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (run.run_id, run.status.value, payload, run.created_at, run.updated_at),
            )

    def load_run(self, run_id: str) -> MultiAgentRun | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM multi_agent_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return MultiAgentRun.from_dict(json.loads(row["payload"]))

    def list_unfinished(self, *, limit: int = 10) -> list[MultiAgentRun]:
        terminal = tuple(status.value for status in TERMINAL_STATUSES)
        placeholders = ",".join("?" for _ in terminal)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT payload FROM multi_agent_runs
                WHERE status NOT IN ({placeholders})
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (*terminal, limit),
            ).fetchall()
        return [MultiAgentRun.from_dict(json.loads(row["payload"])) for row in rows]

    def list_recent(self, *, limit: int = 10) -> list[MultiAgentRun]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM multi_agent_runs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [MultiAgentRun.from_dict(json.loads(row["payload"])) for row in rows]

    def set_agent_messages(self, run_id: str, message_key: str, messages: list[dict[str, Any]]) -> None:
        """Update one subagent message stream without rewriting the full run payload."""
        updated_at = time()
        json_path = "$." + json.dumps(message_key, ensure_ascii=False)
        messages_json = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE multi_agent_runs
                SET payload = json_set(
                        payload,
                        '$.subagent_messages',
                        json_set(json_extract(payload, '$.subagent_messages'), ?, json(?)),
                        '$.updated_at',
                        ?
                    ),
                    updated_at = ?
                WHERE run_id = ?
                """,
                (json_path, messages_json, updated_at, updated_at, run_id),
            )
        if cursor.rowcount == 0:
            raise ValueError(f"multi-agent run not found: {run_id}")

    def mark_failed(self, run: MultiAgentRun, error: str) -> MultiAgentRun:
        run.status = RunStatus.FAILED
        run.error = error
        run.add_event("failed", error=error)
        self.save_run(run)
        return run
