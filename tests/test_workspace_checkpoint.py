from __future__ import annotations

import asyncio
import sqlite3
from time import time

from pydantic import BaseModel

from mycodingagent.memory.models import ExecutionRecord, WorkspaceCheckpoint
from mycodingagent.memory.runtime import MemoryRuntime
from mycodingagent.memory.stores import SQLiteMemoryStore
from mycodingagent.commands import CommandContext
from mycodingagent.commands import handlers
from mycodingagent.terminal_ui.checkpoint_selector import format_checkpoint_option
from mycodingagent.tool_runtime.base import Tool, ToolResult
from mycodingagent.tool_runtime.execution import execute_tool


def _runtime(tmp_path):
    return MemoryRuntime(
        store=SQLiteMemoryStore(tmp_path / "sessions.sqlite3"),
        workspace_root=str(tmp_path),
    )


def test_workspace_checkpoint_restores_modified_and_created_files(tmp_path):
    existing = tmp_path / "existing.txt"
    created = tmp_path / "created.txt"
    existing.write_text("before", encoding="utf-8")
    runtime = _runtime(tmp_path)
    session_id = runtime.start_session("test")
    runtime.begin_workspace_checkpoint(prompt="change files", message_index=2)
    checkpoint_id = runtime.list_workspace_checkpoints()[-1].checkpoint_id

    runtime.capture_before(existing)
    existing.write_text("after", encoding="utf-8")
    runtime.capture_after(existing)
    runtime.capture_before(created)
    created.write_text("new", encoding="utf-8")
    runtime.capture_after(created)
    result = runtime.rewind_workspace(checkpoint_id)

    assert session_id
    assert result.ok
    assert existing.read_text(encoding="utf-8") == "before"
    assert not created.exists()


def test_workspace_checkpoint_refuses_external_overwrite(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("before", encoding="utf-8")
    runtime = _runtime(tmp_path)
    runtime.start_session("test")
    runtime.begin_workspace_checkpoint(prompt="change", message_index=0)
    checkpoint_id = runtime.list_workspace_checkpoints()[-1].checkpoint_id
    runtime.capture_before(path)
    path.write_text("agent", encoding="utf-8")
    runtime.capture_after(path)
    path.write_text("external", encoding="utf-8")

    result = runtime.rewind_workspace(checkpoint_id)

    assert result.conflicts == ("file.txt",)
    assert path.read_text(encoding="utf-8") == "external"


def test_checkpoint_option_identifies_turn_and_checkpoint():
    checkpoint = WorkspaceCheckpoint(
        checkpoint_id="abcdef123456",
        session_id="session",
        turn_index=7,
        message_index=3,
        prompt="review the change",
    )

    assert format_checkpoint_option(checkpoint) == "turn 7 | abcdef12 | review the change"


def test_conversation_only_rewind_keeps_workspace_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "file.txt"
    path.write_text("before", encoding="utf-8")
    runtime = _runtime(tmp_path)
    runtime.start_session("test")
    runtime.begin_workspace_checkpoint(prompt="change", message_index=2)
    checkpoint = runtime.list_workspace_checkpoints()[-1]
    runtime.capture_before(path)
    path.write_text("after", encoding="utf-8")
    runtime.capture_after(path)
    monkeypatch.setattr(handlers, "select_checkpoint_interactively", lambda checkpoints: checkpoint.checkpoint_id)
    monkeypatch.setattr(handlers, "select_rewind_scope_interactively", lambda: "conversation")

    result = asyncio.run(
        handlers.handle_rewind_command(
            CommandContext(runtime, None, [{"role": "system"}, {"role": "user"}, {"role": "assistant"}]),
            "",
        )
    )

    assert result.messages == [{"role": "system"}, {"role": "user"}]
    assert runtime.list_workspace_checkpoints() == [checkpoint]
    assert path.read_text(encoding="utf-8") == "after"
    assert runtime.store.load_workspace_blob(checkpoint_file_hash(runtime.store, checkpoint.checkpoint_id)) == b"before"


def test_expired_workspace_snapshots_and_orphaned_blobs_are_cleaned(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("before", encoding="utf-8")
    db_path = tmp_path / "sessions.sqlite3"
    runtime = _runtime(tmp_path)
    runtime.start_session("test")
    runtime.begin_workspace_checkpoint(prompt="old change", message_index=0)
    checkpoint = runtime.list_workspace_checkpoints()[-1]
    runtime.capture_before(path)
    before_hash = checkpoint_file_hash(runtime.store, checkpoint.checkpoint_id)
    old_time = time() - (31 * 24 * 60 * 60)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE workspace_checkpoints SET created_at = ?", (old_time,))
        conn.execute("UPDATE workspace_snapshot_blobs SET created_at = ?", (old_time,))

    cleaned = runtime.store.cleanup_expired_workspace_snapshots(max_age_seconds=30 * 24 * 60 * 60)

    assert cleaned == (1, 1)
    assert runtime.list_workspace_checkpoints() == []
    assert runtime.store.load_workspace_blob(before_hash) is None


def test_expired_blob_shared_by_live_checkpoint_is_retained(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("before", encoding="utf-8")
    runtime = _runtime(tmp_path)
    runtime.start_session("test")
    runtime.begin_workspace_checkpoint(prompt="first", message_index=0)
    first = runtime.list_workspace_checkpoints()[-1]
    runtime.capture_before(path)
    shared_hash = checkpoint_file_hash(runtime.store, first.checkpoint_id)
    runtime.begin_workspace_checkpoint(prompt="second", message_index=1)
    second = runtime.list_workspace_checkpoints()[-1]
    runtime.capture_before(path)
    old_time = time() - (31 * 24 * 60 * 60)
    with sqlite3.connect(tmp_path / "sessions.sqlite3") as conn:
        conn.execute("UPDATE workspace_snapshot_blobs SET created_at = ?", (old_time,))
        conn.execute("UPDATE workspace_checkpoints SET created_at = ? WHERE checkpoint_id = ?", (old_time, first.checkpoint_id))

    runtime.store.cleanup_expired_workspace_snapshots(max_age_seconds=30 * 24 * 60 * 60)

    assert runtime.store.load_workspace_blob(shared_hash) is not None
    assert runtime.list_workspace_checkpoints() == [second]


def test_legacy_workspace_blobs_receive_retention_timestamp(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE workspace_snapshot_blobs(content_hash TEXT PRIMARY KEY, content BLOB NOT NULL)"
        )
        conn.execute(
            "INSERT INTO workspace_snapshot_blobs(content_hash, content) VALUES (?, ?)",
            ("hash", b"content"),
        )

    store = SQLiteMemoryStore(db_path)

    with store._connect() as conn:
        row = conn.execute(
            "SELECT created_at FROM workspace_snapshot_blobs WHERE content_hash = ?",
            ("hash",),
        ).fetchone()
    assert row is not None
    assert row["created_at"] > 0


def checkpoint_file_hash(store: SQLiteMemoryStore, checkpoint_id: str) -> str:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT before_hash FROM workspace_checkpoint_files WHERE checkpoint_id = ?",
            (checkpoint_id,),
        ).fetchone()
    assert row is not None
    return str(row["before_hash"])


class _Params(BaseModel):
    value: str


class _RecordedTool(Tool):
    name = "Recorded"
    description = "record"
    params_model = _Params

    async def execute(self, params: _Params) -> ToolResult:
        return ToolResult(params.value)


def test_execution_record_is_persisted_and_finished(tmp_path):
    runtime = _runtime(tmp_path)
    session_id = runtime.start_session("test")

    result = asyncio.run(
        execute_tool(
            _RecordedTool(),
            {"value": "ok"},
            execution_recorder=runtime,
            session_id=session_id,
        )
    )
    records = runtime.store.list_executions(session_id)

    assert result.is_error is False
    assert records[0].status == "succeeded"
    assert records[0].args_preview == '{"value": "ok"}'


def test_store_reconciles_running_execution_after_restart(tmp_path):
    db_path = tmp_path / "sessions.sqlite3"
    store = SQLiteMemoryStore(db_path)
    store.start_execution(
        ExecutionRecord(
            execution_id="running",
            session_id="s",
            tool_name="WriteFile",
            risk="write",
            status="running",
            args_hash="hash",
            args_preview="{}",
        )
    )

    restarted = SQLiteMemoryStore(db_path)

    assert restarted.list_executions("s")[0].status == "interrupted"
