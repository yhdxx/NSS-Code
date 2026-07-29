from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import queue
import sqlite3
import threading
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
        mcp_manager: Any | None = None,
    ) -> None:
        self.memory_db = Path(memory_db or CONFIG.memory.db_path).expanduser()
        self.multi_agent_db = Path(multi_agent_db or CONFIG.memory.db_path.with_name("multi_agent.sqlite3")).expanduser()
        self.skill_lrfu_db = Path(skill_lrfu_db or _default_skill_lrfu_db()).expanduser()
        self.workspace_root = Path(workspace_root or os.getcwd()).expanduser().resolve()
        self.mcp_manager = mcp_manager

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
            "capabilities": self._capabilities(selected_session_id),
            "mcp": self._mcp(),
            "long_term_memory": self._long_term_memory(selected_session_id),
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
                SELECT context_id, request_index, model_messages_json, tools_json,
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
                "prompt_hash": row["prompt_hash"],
                "tools_hash": row["tools_hash"],
                "metadata": _safe_json(row["metadata_json"], {}),
                "created_at": float(row["created_at"]),
            })
        return requests

    def _runtime_observations(self, session_id: str, *, include_payloads: bool = False) -> list[dict[str, Any]]:
        conn = self._connect(self.memory_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "session_runtime_observations"):
                return []
            rows = conn.execute(
                """
                SELECT observation_id, request_index, user_prompt, context_mode,
                       capability_result_json, long_term_memory_json, metadata_json, created_at
                FROM session_runtime_observations
                WHERE session_id = ?
                ORDER BY request_index DESC
                LIMIT 30
                """,
                (session_id,),
            ).fetchall()
        observations: list[dict[str, Any]] = []
        for row in rows:
            capability_result = _safe_json(row["capability_result_json"], {})
            long_term_memory = _safe_json(row["long_term_memory_json"], {})
            metadata = _safe_json(row["metadata_json"], {})
            if not isinstance(capability_result, dict):
                capability_result = {}
            if not isinstance(long_term_memory, dict):
                long_term_memory = {}
            if not isinstance(metadata, dict):
                metadata = {}
            recommendations = capability_result.get("recommendations", [])
            if not isinstance(recommendations, list):
                recommendations = []
            memory_items = long_term_memory.get("memories", [])
            if not isinstance(memory_items, list):
                memory_items = []
            observation = {
                "request_index": int(row["request_index"]),
                "user_prompt": row["user_prompt"],
                "context_mode": row["context_mode"],
                "tool_count": int(metadata.get("tool_count") or 0),
                "recommended_skill_count": len(
                    [item for item in recommendations if isinstance(item, dict) and item.get("kind") == "skill"]
                ),
                "recommended_mcp_count": len(
                    [item for item in recommendations if isinstance(item, dict) and item.get("kind") == "mcp_server"]
                ),
                "memory_item_count": len(memory_items),
                "created_at": float(row["created_at"]),
            }
            if include_payloads:
                observation["capability_result"] = capability_result
                observation["long_term_memory"] = long_term_memory
            observations.append(observation)
        return observations

    def _capabilities(self, session_id: str) -> dict[str, Any]:
        observations = self._runtime_observations(session_id, include_payloads=True)
        latest = observations[0] if observations else {}
        capability_result = latest.get("capability_result") or {}
        if not isinstance(capability_result, dict):
            capability_result = {}
        recommendations = capability_result.get("recommendations") or []
        if not isinstance(recommendations, list):
            recommendations = []
        return {
            "latest": capability_result,
            "recent": self._runtime_observations(session_id),
            "recommended_skills": [
                item for item in recommendations if isinstance(item, dict) and item.get("kind") == "skill"
            ],
            "recommended_mcp_servers": [
                item for item in recommendations if isinstance(item, dict) and item.get("kind") == "mcp_server"
            ],
        }

    def _mcp(self) -> dict[str, Any]:
        if self.mcp_manager is None:
            return {"live": False, "servers": []}
        try:
            servers = [server.to_payload() for server in self.mcp_manager.list_servers()]
        except Exception as exc:
            return {"live": True, "servers": [], "error": str(exc)}
        return {
            "live": True,
            "server_count": self.mcp_manager.server_count(),
            "available_count": self.mcp_manager.available_count(),
            "servers": servers,
        }

    def _long_term_memory(self, session_id: str) -> dict[str, Any]:
        observations = self._runtime_observations(session_id, include_payloads=True)
        latest_context = (observations[0].get("long_term_memory") if observations else {}) or {}
        return {
            "latest_context": latest_context,
            "versions": self._long_term_memory_versions(),
            "items": self._long_term_memory_items(),
            "extractions": self._long_term_memory_extractions(),
            "turn_usage": self._long_term_memory_turn_usage(session_id),
        }

    def _long_term_memory_versions(self) -> list[dict[str, Any]]:
        conn = self._connect(self.memory_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "long_term_memory_versions"):
                return []
            rows = conn.execute(
                """
                SELECT *
                FROM long_term_memory_versions
                ORDER BY committed_at DESC, created_at DESC
                LIMIT 20
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def _long_term_memory_items(self) -> list[dict[str, Any]]:
        conn = self._connect(self.memory_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "long_term_memory_items"):
                return []
            rows = conn.execute(
                """
                SELECT *
                FROM long_term_memory_items
                ORDER BY updated_at DESC
                LIMIT 100
                """
            ).fetchall()
        return [_row_dict(row, parse_json_fields={"evidence_json", "metadata_json"}) for row in rows]

    def _long_term_memory_extractions(self) -> list[dict[str, Any]]:
        conn = self._connect(self.memory_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "long_term_memory_extractions"):
                return []
            rows = conn.execute(
                """
                SELECT *
                FROM long_term_memory_extractions
                ORDER BY updated_at DESC
                LIMIT 50
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def _long_term_memory_turn_usage(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._connect(self.memory_db)
        if conn is None:
            return []
        with conn:
            if not self._table_exists(conn, "long_term_memory_turn_usage"):
                return []
            rows = conn.execute(
                """
                SELECT *
                FROM long_term_memory_turn_usage
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (session_id,),
            ).fetchall()
        return [
            _row_dict(
                row,
                parse_json_fields={
                    "exposed_workflow_json",
                    "exposed_skill_json",
                    "used_skill_json",
                    "prompted_json",
                },
            )
            for row in rows
        ]

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


class DashboardEventHub:
    def __init__(self) -> None:
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def publish(self, event: str, payload: dict[str, Any]) -> None:
        message = {"event": event, "payload": payload, "created_at": time.time()}
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(message)


class DashboardAgentBridge:
    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        api_client: Any,
        registry: Any,
        tools: list[dict],
        get_messages: Any,
        set_messages: Any,
        skill_runtime: Any | None = None,
        core_tool_schemas: list[dict] | None = None,
        workspace_tracker: Any | None = None,
        memory_runtime: Any | None = None,
        file_state_cache: Any | None = None,
        capability_router: Any | None = None,
        long_term_memory_runtime: Any | None = None,
        event_hub: DashboardEventHub | None = None,
    ) -> None:
        self.loop = loop
        self.api_client = api_client
        self.registry = registry
        self.tools = tools
        self.get_messages = get_messages
        self.set_messages = set_messages
        self.skill_runtime = skill_runtime
        self.core_tool_schemas = core_tool_schemas
        self.workspace_tracker = workspace_tracker
        self.memory_runtime = memory_runtime
        self.file_state_cache = file_state_cache
        self.capability_router = capability_router
        self.long_term_memory_runtime = long_term_memory_runtime
        self.event_hub = event_hub
        self._busy_lock = threading.Lock()

    def submit(self, message: str) -> dict[str, Any]:
        prompt = message.strip()
        if not prompt:
            return {"ok": False, "error": "empty_message"}
        if not self._busy_lock.acquire(blocking=False):
            return {"ok": False, "error": "busy"}
        future = asyncio.run_coroutine_threadsafe(self._run(prompt), self.loop)
        try:
            return future.result()
        finally:
            self._busy_lock.release()

    async def _run(self, prompt: str) -> dict[str, Any]:
        from mycodingagent.llm_runtime import client as agent_client

        self._publish("chat_started", {"message": prompt})
        try:
            previous_messages = self.get_messages() if callable(self.get_messages) else []
            answer, updated_messages = await agent_client.ask_deepseek(
                self.api_client,
                prompt,
                self.registry,
                self.tools,
                previous_messages or None,
                skill_runtime=self.skill_runtime,
                core_tool_schemas=self.core_tool_schemas,
                workspace_tracker=self.workspace_tracker,
                memory_runtime=self.memory_runtime,
                capability_router=self.capability_router,
                long_term_memory_runtime=self.long_term_memory_runtime,
            )
            if self.memory_runtime is not None:
                rollover = await self.memory_runtime.on_turn_completed(
                    messages=updated_messages,
                    skill_runtime=self.skill_runtime,
                    file_state_cache=self.file_state_cache,
                    workspace_tracker=self.workspace_tracker,
                    system_prompt_source=updated_messages[0] if updated_messages else None,
                    tools=self.tools,
                    current_prompt=prompt,
                )
                if rollover.performed and rollover.new_messages is not None:
                    updated_messages = rollover.new_messages
            if callable(self.set_messages):
                self.set_messages(updated_messages)
            payload = {"ok": True, "answer": answer, "message_count": len(updated_messages)}
            self._publish("chat_completed", payload)
            return payload
        except Exception as exc:
            payload = {"ok": False, "error": str(exc)}
            self._publish("chat_error", payload)
            return payload

    def _publish(self, event: str, payload: dict[str, Any]) -> None:
        if self.event_hub is not None:
            self.event_hub.publish(event, payload)


class DashboardHandler(BaseHTTPRequestHandler):
    provider: DashboardDataProvider
    bridge: DashboardAgentBridge | None = None
    event_hub: DashboardEventHub | None = None

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
        if parsed.path == "/api/events":
            self._send_events()
            return
        self._send_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/chat":
            self._send_json({"ok": False, "error": "not_found"}, status=404)
            return
        if self.bridge is None:
            self._send_json({"ok": False, "error": "chat_unavailable"}, status=503)
            return
        payload = self._read_json_body()
        message = str(payload.get("message") or "")
        result = self.bridge.submit(message)
        self._send_json(result, status=200 if result.get("ok") else 409 if result.get("error") == "busy" else 400)

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

    def _send_events(self) -> None:
        if self.event_hub is None:
            self._send_json({"ok": False, "error": "events_unavailable"}, status=503)
            return
        subscriber = self.event_hub.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                try:
                    message = subscriber.get(timeout=15)
                except queue.Empty:
                    message = {"event": "heartbeat", "payload": {}, "created_at": time.time()}
                raw = (
                    f"event: {message['event']}\n"
                    f"data: {json.dumps(message, ensure_ascii=False, default=str)}\n\n"
                ).encode("utf-8")
                self.wfile.write(raw)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            self.event_hub.unsubscribe(subscriber)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

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
    mcp_manager: Any | None = None,
    bridge: DashboardAgentBridge | None = None,
    event_hub: DashboardEventHub | None = None,
) -> ThreadingHTTPServer:
    event_hub = event_hub or DashboardEventHub()
    provider = DashboardDataProvider(
        memory_db=memory_db,
        multi_agent_db=multi_agent_db,
        skill_lrfu_db=skill_lrfu_db,
        workspace_root=workspace_root,
        mcp_manager=mcp_manager,
    )
    handler = type(
        "BoundDashboardHandler",
        (DashboardHandler,),
        {"provider": provider, "bridge": bridge, "event_hub": event_hub},
    )
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
