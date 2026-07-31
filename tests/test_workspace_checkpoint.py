from __future__ import annotations

import asyncio

from pydantic import BaseModel

from mycodingagent.memory.models import ExecutionRecord
from mycodingagent.memory.runtime import MemoryRuntime
from mycodingagent.memory.stores import SQLiteMemoryStore
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
