from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from mycodingagent.configuration import CONFIG


STATIC_DIR = Path(__file__).resolve().parent / "static"


def _default_skill_lrfu_db() -> Path:
    index_dir = CONFIG.skills.index_dir or (CONFIG.skills.root / ".skill_runtime")
    return index_dir / "user_skill_lrfu.sqlite3"


class DashboardDataProvider:
    def __init__(
        self,
        *,
        memory_db: Path | str | None = None,
        multi_agent_db: Path | str | None = None,
        skill_lrfu_db: Path | str | None = None,
        workspace_root: Path | str | None = None,
    ) -> None:
        self.memory_db = Path(memory_db or CONFIG.memory.db_path).expanduser()
        self.multi_agent_db = Path(multi_agent_db or CONFIG.memory.db_path.with_name("multi_agent.sqlite3")).expanduser()
        self.skill_lrfu_db = Path(skill_lrfu_db or _default_skill_lrfu_db()).expanduser()
        self.workspace_root = Path(workspace_root or os.getcwd()).expanduser().resolve()

    def state(self, *, session_id: str = "", limit: int = 20) -> dict[str, Any]:
        sessions = self._sessions(limit=limit)
        selected_session_id = session_id or (sessions[0]["session_id"] if sessions else "")
        messages = self._messages(selected_session_id) if selected_session_id else []
        return {
            "generated_at": time.time(),
            "paths": {
                "memory_db": str(self.memory_db),
                "multi_agent_db": str(self.multi_agent_db),
                "skill_lrfu_db": str(self.skill_lrfu_db),
                "workspace_root": str(self.workspace_root),
            },
            "sessions": sessions,
            "selected_session_id": selected_session_id,
            "messages": messages,
            "turns": self._turns(messages),
            "model_context": self._model_context(selected_session_id, messages),
            "token_usage": self._token_usage(selected_session_id),
            "context_epochs": self._context_epochs(selected_session_id),
            "recoverable_contexts": self._recoverable_contexts(selected_session_id),
            "multi_agent_runs": self._multi_agent_runs(limit=limit),
            "lrfu": self._lrfu(selected_session_id),
            "project": self._project_index(limit=600),
        }

    def file_payload(self, relative_path: str) -> dict[str, Any]:
        requested = unquote(relative_path).strip().lstrip("/")
        path = (self.workspace_root / requested).resolve()
        if not path.is_file() or not self._inside_workspace(path):
            return {"error": "file_not_found_or_outside_workspace", "path": requested}
        text = path.read_text(encoding="utf-8", errors="replace")
        return {
            "path": str(path.relative_to(self.workspace_root)),
            "size": len(text),
            "lines": _line_count(text),
            "content": text,
        }

    def _connect(self, path: Path) -> sqlite3.Connection | None:
        if not path.exists():
            return None
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_exists(self, conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        return row is not None

    def _sessions(self, *, limit: int) -> list[dict[str, Any]]:
        conn = self._connect(self.memory_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "sessions"):
                return []
            rows = conn.execute(
                """
                SELECT session_id, created_at, updated_at, last_accessed_at, model, status,
                       workspace_root, workspace_label, latest_lrfu_json
                FROM sessions
                ORDER BY last_accessed_at DESC, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_dict(row, parse_json_fields={"latest_lrfu_json"}) for row in rows]

    def _messages(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._connect(self.memory_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "session_messages"):
                return []
            rows = conn.execute(
                """
                SELECT message_index, role, content_json, created_at
                FROM session_messages
                WHERE session_id = ?
                ORDER BY message_index
                """,
                (session_id,),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            payload = _safe_json(row["content_json"], {})
            if not isinstance(payload, dict):
                payload = {"content": payload}
            payload.setdefault("role", row["role"])
            payload["message_index"] = int(row["message_index"])
            payload["created_at"] = float(row["created_at"])
            messages.append(payload)
        return messages

    def _turns(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        turns: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for message in messages:
            if message.get("role") == "user":
                current = {
                    "turn_index": len(turns) + 1,
                    "start_message_index": message.get("message_index"),
                    "end_message_index": message.get("message_index"),
                    "user": message,
                    "messages": [message],
                }
                turns.append(current)
                continue
            if current is None:
                current = {
                    "turn_index": 0,
                    "start_message_index": message.get("message_index"),
                    "end_message_index": message.get("message_index"),
                    "user": None,
                    "messages": [message],
                }
                turns.append(current)
            else:
                current["messages"].append(message)
                current["end_message_index"] = message.get("message_index")
        return turns

    def _model_context(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        requests = self._model_context_requests(session_id)
        if requests:
            return {
                "kind": "persisted_model_request",
                "note": "Shows the exact model_messages persisted immediately before each model API request.",
                "latest_messages": requests[0].get("model_messages", []),
                "requests": requests,
                "snapshots": self._context_snapshots(session_id),
            }
        snapshots = self._context_snapshots(session_id)
        latest_messages = snapshots[0].get("compressed_messages", []) if snapshots else messages
        return {
            "kind": "persisted_snapshot" if snapshots else "stored_conversation_prefix",
            "note": (
                "No exact model request has been persisted for this session yet. This view shows the latest "
                "compressed snapshot when available; otherwise it shows the stored conversation messages."
            ),
            "latest_messages": latest_messages,
            "requests": [],
            "snapshots": snapshots,
        }

    def _model_context_requests(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._connect(self.memory_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "session_model_contexts"):
                return []
            rows = conn.execute(
                """
                SELECT context_id, request_index, model_messages_json, tools_json, rendered_prompt,
                       prompt_hash, tools_hash, metadata_json, created_at
                FROM session_model_contexts
                WHERE session_id = ?
                ORDER BY request_index DESC
                LIMIT 20
                """,
                (session_id,),
            ).fetchall()
        requests = []
        for row in rows:
            requests.append({
                "context_id": row["context_id"],
                "request_index": int(row["request_index"]),
                "model_messages": _safe_json(row["model_messages_json"], []),
                "tools": _safe_json(row["tools_json"], []),
                "rendered_prompt": row["rendered_prompt"],
                "prompt_hash": row["prompt_hash"],
                "tools_hash": row["tools_hash"],
                "metadata": _safe_json(row["metadata_json"], {}),
                "created_at": float(row["created_at"]),
            })
        return requests

    def _context_snapshots(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._connect(self.memory_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "session_context_snapshots"):
                return []
            rows = conn.execute(
                """
                SELECT snapshot_id, compressed_messages_json, summary_text, pressure_ratio, created_at
                FROM session_context_snapshots
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (session_id,),
            ).fetchall()
        items = []
        for row in rows:
            items.append({
                "snapshot_id": row["snapshot_id"],
                "compressed_messages": _safe_json(row["compressed_messages_json"], []),
                "summary_text": row["summary_text"],
                "pressure_ratio": float(row["pressure_ratio"]),
                "created_at": float(row["created_at"]),
            })
        return items

    def _token_usage(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._connect(self.memory_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "session_token_usage"):
                return []
            rows = conn.execute(
                """
                SELECT request_index, prompt_tokens, prompt_cache_hit_tokens, prompt_cache_miss_tokens,
                       completion_tokens, total_tokens, model, prompt_hash, tools_hash, metadata_json, created_at
                FROM session_token_usage
                WHERE session_id = ?
                ORDER BY request_index
                """,
                (session_id,),
            ).fetchall()
        return [_row_dict(row, parse_json_fields={"metadata_json"}) for row in rows]

    def _context_epochs(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._connect(self.memory_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "context_epochs"):
                return []
            rows = conn.execute(
                """
                SELECT *
                FROM context_epochs
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT 30
                """,
                (session_id,),
            ).fetchall()
        return [_row_dict(row, parse_json_fields={"retain_context_ids_json", "active_files_json"}) for row in rows]

    def _recoverable_contexts(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._connect(self.memory_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "recoverable_contexts"):
                return []
            rows = conn.execute(
                """
                SELECT context_id, tool_call_id, tool_name, short_summary, content_length,
                       token_count, lifecycle_state, access_count, last_accessed_at, timestamp
                FROM recoverable_contexts
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT 80
                """,
                (session_id,),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def _multi_agent_runs(self, *, limit: int) -> list[dict[str, Any]]:
        conn = self._connect(self.multi_agent_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "multi_agent_runs"):
                return []
            rows = conn.execute(
                """
                SELECT run_id, status, payload, created_at, updated_at
                FROM multi_agent_runs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        runs = []
        for row in rows:
            payload = _safe_json(row["payload"], {})
            runs.append({
                "run_id": row["run_id"],
                "status": row["status"],
                "created_at": float(row["created_at"]),
                "updated_at": float(row["updated_at"]),
                "task": payload.get("task", ""),
                "plan_summary": payload.get("plan_summary", ""),
                "submitted_plan": payload.get("submitted_plan", []),
                "approved_plan": payload.get("approved_plan", []),
                "scheduled_tasks": payload.get("scheduled_tasks", {}),
                "events": payload.get("events", []),
                "subagent_messages": payload.get("subagent_messages", {}),
                "subagent_rounds_used": payload.get("subagent_rounds_used", {}),
                "subagent_tool_calls_used": payload.get("subagent_tool_calls_used", {}),
                "error": payload.get("error", ""),
            })
        return runs

    def _lrfu(self, session_id: str) -> dict[str, Any]:
        session_snapshot = {}
        for session in self._sessions(limit=50):
            if session.get("session_id") == session_id:
                session_snapshot = session.get("latest_lrfu_json") or {}
                break
        return {
            "session_snapshot": session_snapshot,
            "user_skill_lrfu": self._user_skill_lrfu(),
            "pending_sessions": self._pending_skill_sessions(),
            "pending_updates": self._pending_skill_updates(),
        }

    def _user_skill_lrfu(self) -> list[dict[str, Any]]:
        conn = self._connect(self.skill_lrfu_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "user_skill_lrfu"):
                return []
            rows = conn.execute(
                """
                SELECT user_id, skill_name, score, last_update_round
                FROM user_skill_lrfu
                ORDER BY score DESC, last_update_round DESC, skill_name
                LIMIT 100
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def _pending_skill_sessions(self) -> list[dict[str, Any]]:
        conn = self._connect(self.skill_lrfu_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "pending_skill_sessions"):
                return []
            rows = conn.execute(
                """
                SELECT *
                FROM pending_skill_sessions
                ORDER BY updated_at DESC
                LIMIT 50
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def _pending_skill_updates(self) -> list[dict[str, Any]]:
        conn = self._connect(self.skill_lrfu_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "pending_skill_updates"):
                return []
            rows = conn.execute(
                """
                SELECT *
                FROM pending_skill_updates
                ORDER BY updated_at DESC
                LIMIT 100
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def _project_index(self, *, limit: int) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        omitted = 0
        for path in sorted(self.workspace_root.rglob("*")):
            if not path.is_file() or self._skip_path(path):
                continue
            if len(items) >= limit:
                omitted += 1
                continue
            relative = path.relative_to(self.workspace_root)
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            items.append({"path": str(relative), "size": size})
        return {"files": items, "omitted": omitted}

    def _inside_workspace(self, path: Path) -> bool:
        try:
            path.relative_to(self.workspace_root)
        except ValueError:
            return False
        return True

    def _skip_path(self, path: Path) -> bool:
        skip = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
        return any(part in skip for part in path.relative_to(self.workspace_root).parts)


class DashboardHandler(BaseHTTPRequestHandler):
    provider: DashboardDataProvider

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            qs = parse_qs(parsed.query)
            session_id = (qs.get("session_id") or [""])[0]
            payload = self.provider.state(session_id=session_id)
            self._send_json(payload)
            return
        if parsed.path == "/api/file":
            qs = parse_qs(parsed.query)
            path = (qs.get("path") or [""])[0]
            self._send_json(self.provider.file_payload(path))
            return
        self._send_static(parsed.path)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if not target.is_file() or STATIC_DIR not in target.parents:
            self.send_error(404)
            return
        content_type, _ = mimetypes.guess_type(target)
        raw = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _row_dict(row: sqlite3.Row, *, parse_json_fields: set[str] | None = None) -> dict[str, Any]:
    parse_json_fields = parse_json_fields or set()
    result: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if key in parse_json_fields:
            result[key] = _safe_json(value, {})
        else:
            result[key] = value
    return result


def _safe_json(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def _line_count(text: str) -> int:
    return text.count("\n") + (0 if text.endswith("\n") or text == "" else 1)


def build_server(
    *,
    host: str,
    port: int,
    memory_db: Path | str | None = None,
    multi_agent_db: Path | str | None = None,
    skill_lrfu_db: Path | str | None = None,
    workspace_root: Path | str | None = None,
) -> ThreadingHTTPServer:
    provider = DashboardDataProvider(
        memory_db=memory_db,
        multi_agent_db=multi_agent_db,
        skill_lrfu_db=skill_lrfu_db,
        workspace_root=workspace_root,
    )
    handler = type("BoundDashboardHandler", (DashboardHandler,), {"provider": provider})
    return ThreadingHTTPServer((host, port), handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the myCodingAgent runtime dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--memory-db", default=str(CONFIG.memory.db_path))
    parser.add_argument("--multi-agent-db", default=str(CONFIG.memory.db_path.with_name("multi_agent.sqlite3")))
    parser.add_argument("--skill-lrfu-db", default=str(_default_skill_lrfu_db()))
    parser.add_argument("--workspace-root", default=os.getcwd())
    args = parser.parse_args()

    server = build_server(
        host=args.host,
        port=args.port,
        memory_db=args.memory_db,
        multi_agent_db=args.multi_agent_db,
        skill_lrfu_db=args.skill_lrfu_db,
        workspace_root=args.workspace_root,
    )
    print(f"Dashboard: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
