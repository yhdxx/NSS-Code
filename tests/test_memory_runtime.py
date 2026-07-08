from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import sqlite3
import sys
import types
from time import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

openai_stub = types.ModuleType("openai")
openai_stub.AsyncOpenAI = object
openai_stub.APIConnectionError = Exception
openai_stub.APIError = Exception
openai_stub.APITimeoutError = Exception
sys.modules.setdefault("openai", openai_stub)

import client as agent_client
from config import CONFIG
from memory import ConversationSnapshot, MemoryRuntime, SQLiteMemoryStore, SnapshotDelta
from memory.budget import BudgetStage, PromptBudgetSnapshot
from memory.checkpoint import SNAPSHOT_FIELD_ORDER, TurnState, format_snapshot_prompt
from memory.compressor import ContextCompressor, is_reproducible_tool
from memory.runtime import format_compression_report
from memory.stores import session_preview
from memory.message_filters import is_skill_related_tool, persistent_assistant_tool_message
from session_switch import has_conversation_content, save_current_session_if_needed
from skills.session_skill_cache import SessionSkillCache
from tools import create_default_registry
from tools.memory_lookup import (
    GetStoredToolOutput,
    GetStoredToolOutputParams,
    RecoverContext,
    RecoverContextParams,
    RestoreSession,
    RestoreSessionParams,
    SearchRecoverableContext,
    SearchRecoverableContextParams,
    SearchSessionHistory,
    SearchSessionHistoryParams,
)


class FileStateCacheStub:
    def __init__(self):
        self._state = {}

    def record(self, path: str, content: str, mtime_ns: int) -> None:
        self._state[path] = (content, mtime_ns)

    def get_state(self, path: str):
        return self._state.get(path)

    def to_dict(self) -> dict:
        return {
            "files": [
                {"path": path, "content": content, "mtime_ns": mtime_ns}
                for path, (content, mtime_ns) in self._state.items()
            ]
        }

    def load_dict(self, data: dict) -> None:
        self._state = {
            item["path"]: (item["content"], item["mtime_ns"])
            for item in data.get("files", [])
        }


class WorkspaceTrackerStub:
    def __init__(self, changed_paths: list[str], omitted: int = 0):
        self.changed_paths = changed_paths
        self.omitted = omitted
        self.consume_calls = 0

    def consume_external_changes(self) -> tuple[list[str], int]:
        self.consume_calls += 1
        if self.consume_calls == 1:
            return self.changed_paths, self.omitted
        return [], 0


def test_workspace_notice_is_temporary_system_message():
    messages = [{"role": "system", "content": "fixed"}, {"role": "user", "content": "work"}]
    tracker = WorkspaceTrackerStub(["app.py"], omitted=2)

    rendered = agent_client.with_workspace_change_notice(messages, tracker)

    assert rendered[:-1] == messages
    assert rendered[-1]["role"] == "system"
    assert "环境通知" in rendered[-1]["content"]
    assert "app.py" in rendered[-1]["content"]
    assert "另有 2 个文件未列出" in rendered[-1]["content"]
    assert messages == [{"role": "system", "content": "fixed"}, {"role": "user", "content": "work"}]


def test_ask_deepseek_reuses_turn_tools_and_omits_temporary_system_from_history(monkeypatch):
    async def scenario():
        tools_seen = []
        messages_seen = []
        build_calls = 0

        async def fake_build_round_tools(prompt, default_tools, skill_runtime, core_tool_schemas):
            nonlocal build_calls
            build_calls += 1
            return [{"type": "function", "function": {"name": "FakeTool", "parameters": {"type": "object"}}}]

        async def fake_stream_one_round(_client, _model, messages, tools):
            messages_seen.append(copy.deepcopy(messages))
            tools_seen.append(tools)
            if len(messages_seen) == 1:
                return "", [agent_client.PendingToolCall("call_1", "FakeTool", "{}")]
            return "done", []

        async def fake_execute_local_tool(registry, tool_name, raw_args, skill_runtime):
            return "tool ok"

        monkeypatch.setattr(agent_client, "build_round_tools", fake_build_round_tools)
        monkeypatch.setattr(agent_client, "stream_one_round", fake_stream_one_round)
        monkeypatch.setattr(agent_client, "execute_local_tool", fake_execute_local_tool)

        history = [{"role": "system", "content": "fixed system"}]
        tracker = WorkspaceTrackerStub(["changed.py"])
        _text, updated = await agent_client.ask_deepseek(
            client=object(),
            prompt="do work",
            registry=object(),
            tools=[],
            messages=history,
            workspace_tracker=tracker,
        )

        assert build_calls == 1
        assert len(tools_seen) == 2
        assert tools_seen[0] is tools_seen[1]
        assert messages_seen[0][-1]["role"] == "system"
        assert "changed.py" in messages_seen[0][-1]["content"]
        assert messages_seen[1][-1]["role"] == "tool"
        assert not any(
            message.get("role") == "system" and "环境通知" in message.get("content", "")
            for message in updated
        )
        assert updated == history

    asyncio.run(scenario())


def test_session_id_is_stable_and_messages_restore(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("deepseek-v4-flash")
    assert runtime.get_current_session_id() == session_id
    assert runtime.start_session("deepseek-v4-flash") == session_id

    messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    runtime.save_messages(session_id, messages)
    restored = runtime.load_session(session_id)

    assert restored is not None
    assert restored.messages == messages


def test_delete_session_removes_related_records(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    runtime.save_messages(session_id, [{"role": "user", "content": "delete me"}])
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="call_1",
        tool_name="ReadFile",
        arguments="{}",
        output="content",
    )
    runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=[{"role": "user", "content": "summary"}],
        tools=[],
        current_prompt="next",
    )

    assert runtime.delete_session(session_id)

    assert runtime.load_session(session_id) is None
    assert runtime.get_tool_output(output_id) is None
    assert runtime.get_current_session_id() is None


def test_expired_sessions_are_deleted_by_last_access_time(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    runtime = MemoryRuntime(store=store)
    fresh_session_id = runtime.start_session("test")
    runtime.save_messages(fresh_session_id, [{"role": "user", "content": "fresh"}])
    expired_session_id = "expired"
    store.ensure_session(session_id=expired_session_id, model="test")
    store.save_messages(session_id=expired_session_id, messages=[{"role": "user", "content": "old"}])

    with sqlite3.connect(tmp_path / "memory.sqlite3") as conn:
        conn.execute(
            "UPDATE sessions SET last_accessed_at = ? WHERE session_id = ?",
            (time() - (31 * 24 * 60 * 60), expired_session_id),
        )

    assert runtime.cleanup_expired_sessions() == 1
    assert runtime.load_session(expired_session_id) is None
    assert runtime.load_session(fresh_session_id) is not None


def test_load_session_refreshes_expiry_clock(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    runtime = MemoryRuntime(store=store)
    session_id = runtime.start_session("test")
    runtime.save_messages(session_id, [{"role": "user", "content": "keep"}])
    old_access_time = time() - (31 * 24 * 60 * 60)
    with sqlite3.connect(tmp_path / "memory.sqlite3") as conn:
        conn.execute("UPDATE sessions SET last_accessed_at = ? WHERE session_id = ?", (old_access_time, session_id))

    assert runtime.load_session(session_id) is not None

    assert runtime.cleanup_expired_sessions() == 0
    assert runtime.load_session(session_id) is not None


def test_legacy_database_backfills_last_accessed_at(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    updated_at = time() - 123
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
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
        conn.execute(
            """
            INSERT INTO sessions(
                session_id, created_at, updated_at, model, status,
                workspace_root, workspace_label, workspace_fingerprint
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("legacy", updated_at - 1, updated_at, "test", "active", "", "", ""),
        )

    store = SQLiteMemoryStore(db_path)
    state = store.load_session("legacy")

    assert state is not None
    assert state.last_accessed_at == updated_at


def test_async_writer_persists_after_drain(tmp_path):
    async def scenario():
        runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
        session_id = runtime.start_session("deepseek-v4-flash")
        messages = [{"role": "user", "content": "async hello"}, {"role": "assistant", "content": "async hi"}]

        runtime.save_messages(session_id, messages)
        await runtime.drain()
        restored = runtime.load_session(session_id)
        await runtime.close()

        assert restored is not None
        assert restored.messages == messages

    asyncio.run(scenario())


def test_save_messages_now_persists_without_drain(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("deepseek-v4-flash")
    messages = [{"role": "user", "content": "sync hello"}, {"role": "assistant", "content": "sync hi"}]

    runtime.save_messages_now(session_id, messages)
    restored = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3")).load_session(session_id)

    assert restored is not None
    assert restored.messages == messages


def test_save_messages_now_is_not_overwritten_by_stale_async_save(tmp_path):
    async def scenario():
        runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
        session_id = runtime.start_session("deepseek-v4-flash")
        stale_messages = [{"role": "user", "content": "old"}]
        final_messages = [{"role": "user", "content": "new"}, {"role": "assistant", "content": "done"}]

        runtime.save_messages(session_id, stale_messages)
        runtime.save_messages_now(session_id, final_messages)
        await runtime.drain()
        restored = runtime.load_session(session_id)
        await runtime.close()

        assert restored is not None
        assert restored.messages == final_messages

    asyncio.run(scenario())


def test_save_current_session_before_switch_uses_existing_session_id(tmp_path):
    async def scenario():
        runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
        session_id = runtime.start_session("test")
        messages = [{"role": "user", "content": "current work"}, {"role": "assistant", "content": "done"}]
        await runtime.drain()

        saved_id = save_current_session_if_needed(
            memory_runtime=runtime,
            messages=messages,
            skill_runtime=None,
        )
        await runtime.drain()
        restored = runtime.load_session(session_id)
        await runtime.close()

        assert saved_id == session_id
        assert restored is not None
        assert restored.messages == messages

    asyncio.run(scenario())


def test_file_state_snapshot_round_trip_and_recheck(tmp_path):
    async def scenario():
        runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
        session_id = runtime.start_session("test")
        file_path = str(tmp_path / "target.py")
        cache = FileStateCacheStub()
        cache.record(file_path, "old", 123)

        runtime.save_file_state_snapshot(session_id, cache)
        await runtime.drain()

        restored_cache = FileStateCacheStub()

        class TrackerStub:
            marked_paths = []

            def mark_paths_for_recheck(self, paths):
                self.marked_paths = list(paths)

        tracker = TrackerStub()
        snapshot = runtime.load_file_state_snapshot(session_id, restored_cache, tracker)
        await runtime.close()

        assert snapshot == {"files": [{"path": file_path, "content": "old", "mtime_ns": 123}]}
        assert restored_cache.get_state(file_path) == ("old", 123)
        assert tracker.marked_paths == [file_path]

    asyncio.run(scenario())


def test_empty_current_session_is_not_saved_before_switch(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))

    assert not has_conversation_content([])
    assert not has_conversation_content([{"role": "system", "content": "system prompt"}])
    assert save_current_session_if_needed(memory_runtime=runtime, messages=[], skill_runtime=None) == ""


def test_session_list_uses_last_non_exit_user_message(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    runtime.save_messages(
        session_id,
        [
            {"role": "user", "content": "第一轮需求"},
            {"role": "assistant", "content": "回答"},
            {"role": "user", "content": "最后一个有效需求"},
            {"role": "assistant", "content": "回答"},
            {"role": "user", "content": "exit"},
        ],
    )

    sessions = runtime.list_sessions(limit=10)

    assert len(sessions) == 1
    assert sessions[0].session_id == session_id
    assert sessions[0].preview == "最后一个有效需求"
    assert sessions[0].message_count == 5


def test_session_list_defaults_to_current_workspace(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    runtime_a = MemoryRuntime(store=store, workspace_root=tmp_path / "workspace-a")
    runtime_b = MemoryRuntime(store=store, workspace_root=tmp_path / "workspace-b")
    session_a = runtime_a.start_session("test")
    runtime_a.save_messages(session_a, [{"role": "user", "content": "from a"}])
    session_b = runtime_b.start_session("test")
    runtime_b.save_messages(session_b, [{"role": "user", "content": "from b"}])

    sessions_a = runtime_a.list_sessions(limit=10)
    sessions_all = runtime_a.list_sessions(limit=10, include_all=True)

    assert [session.session_id for session in sessions_a] == [session_a]
    assert {session.session_id for session in sessions_all} == {session_a, session_b}


def test_migrated_workspace_sessions_match_fingerprint(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    (workspace_a / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (workspace_b / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    runtime_a = MemoryRuntime(store=store, workspace_root=workspace_a)
    runtime_b = MemoryRuntime(store=store, workspace_root=workspace_b)
    session_a = runtime_a.start_session("test")
    runtime_a.save_messages(session_a, [{"role": "user", "content": "from migrated project"}])
    runtime_b.start_session("test")

    migrated = runtime_b.list_migrated_workspace_sessions(limit=10)

    assert [session.session_id for session in migrated] == [session_a]


def test_session_preview_falls_back_when_no_user_message():
    assert session_preview([{"role": "assistant", "content": "only answer"}]) == "only answer"
    assert session_preview([]) == "(空会话)"


def test_current_turn_small_tool_output_stays_inline(tmp_path):
    compressor = ContextCompressor(context_window=1000, tool_preview_chars=5)
    runtime = MemoryRuntime(
        store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        compressor=compressor,
    )
    session_id = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="call_1",
        tool_name="ReadFile",
        arguments="{}",
        output="abcdefg" * 20,
    )
    messages = [
        {"role": "user", "content": "x" * 30},
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "abcdefg" * 20,
            "metadata": {"output_id": output_id},
        },
    ]

    compressed = runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=messages,
        tools=[],
        current_prompt="next",
    )

    stored = runtime.get_tool_output(output_id)
    assert stored is not None
    assert stored.output_text == "abcdefg" * 20
    assert compressed[-1]["content"] == "abcdefg" * 20
    assert "metadata" not in compressed[-1]


def test_get_stored_tool_output_returns_current_session_chunk(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="call_1",
        tool_name="ReadFile",
        arguments='{"file_path":"a.py"}',
        output="0123456789abcdef",
    )
    tool = GetStoredToolOutput(runtime)

    result = asyncio.run(tool.execute(GetStoredToolOutputParams(output_id=output_id, offset=4, limit=6)))

    assert not result.is_error
    assert '"tool_name": "ReadFile"' in result.output
    assert '"next_offset": 10' in result.output
    assert result.output.endswith("456789")


def test_recover_context_returns_partial_context_metadata(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="call_1",
        tool_name="ReadFile",
        arguments='{"file_path":"billing.py"}',
        output="0123456789abcdef",
    )
    tool = RecoverContext(runtime)

    result = asyncio.run(tool.execute(RecoverContextParams(context_id=output_id, offset=4, limit=6)))

    assert not result.is_error
    assert '"context_id":' in result.output
    assert '"tool_name": "ReadFile"' in result.output
    assert '"next_offset": 10' in result.output
    assert result.output.endswith("456789")


def test_search_recoverable_context_finds_metadata(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="call_1",
        tool_name="ReadFile",
        arguments='{"file_path":"billing.py"}',
        output="def calculate_invoice_total(): pass",
    )
    tool = SearchRecoverableContext(runtime)

    result = asyncio.run(tool.execute(SearchRecoverableContextParams(query="billing", limit=5)))

    assert not result.is_error
    assert '"match_count": 1' in result.output
    assert "billing.py" in result.output


def test_get_stored_tool_output_recovers_other_session_with_owner_metadata(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    first_session_id = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=first_session_id,
        tool_call_id="call_1",
        tool_name="ReadFile",
        arguments="{}",
        output="secret",
    )
    runtime.clear_current_session_id()
    runtime.start_session("test")
    tool = GetStoredToolOutput(runtime)

    result = asyncio.run(tool.execute(GetStoredToolOutputParams(output_id=output_id)))

    assert not result.is_error
    assert f'"owner_session_id": "{first_session_id}"' in result.output
    assert result.output.endswith("secret")


def test_search_session_history_finds_virtualized_turns(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    runtime.save_messages_now(
        session_id,
        [
            {"role": "system", "content": "hidden target"},
            {"role": "user", "content": "please inspect billing flow"},
            {"role": "assistant", "content": "billing flow uses invoices"},
        ],
    )
    tool = SearchSessionHistory(runtime, preview_chars=80)

    result = asyncio.run(tool.execute(SearchSessionHistoryParams(query="billing", limit=5)))

    assert not result.is_error
    assert '"match_count": 1' in result.output
    assert '"turn_index": 0' in result.output
    assert "billing flow uses invoices" in result.output
    assert "hidden target" not in result.output


def test_memory_lookup_tools_are_registered_when_memory_runtime_exists(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    registry = create_default_registry(memory_runtime=runtime)

    schemas = registry.get_all_schemas("openai")
    names = {schema["name"] for schema in schemas}
    output_schema = next(schema for schema in schemas if schema["name"] == "GetStoredToolOutput")

    assert {
        "GetStoredToolOutput",
        "RecoverContext",
        "RestoreSession",
        "SearchRecoverableContext",
        "SearchSessionHistory",
        "GetRecentConversationTurns",
        "SummarizeCurrentTurnMessage",
    } <= names
    assert "output_id" in output_schema["parameters"]["properties"]


def test_large_tool_output_becomes_recoverable_preview(tmp_path):
    compressor = ContextCompressor(context_window=1000)
    runtime = MemoryRuntime(
        store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        compressor=compressor,
    )
    session_id = runtime.start_session("test")
    output = "abcdefg" * 20000
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="call_1",
        tool_name="ReadFile",
        arguments='{"file_path":"large.py"}',
        output=output,
    )

    prompt_content = runtime.tool_output_prompt_content(
        output_id=output_id,
        output=output,
        messages=[{"role": "user", "content": "inspect"}],
        tools=[],
        current_prompt="inspect",
    )

    assert "[Recoverable context stored]" in prompt_content
    assert f"context_id: {output_id}" in prompt_content
    assert "PROMPT BUDGET" in prompt_content
    assert len(prompt_content) < len(output)


def test_prepare_messages_can_skip_persisting_temporary_context_snapshot(tmp_path):
    compressor = ContextCompressor(context_window=1000)
    runtime = MemoryRuntime(
        store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        compressor=compressor,
    )
    session_id = runtime.start_session("test")
    runtime.save_messages_now(session_id, [{"role": "user", "content": "persisted"}])

    runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=[
            {"role": "user", "content": "persisted"},
            {"role": "tool", "tool_call_id": "skill_call", "content": "SKILL:\nINSTRUCTIONS:\nsecret"},
        ],
        tools=[],
        current_prompt="next",
        persist_snapshot=False,
    )

    restored = runtime.load_session(session_id)

    assert restored is not None
    assert restored.latest_context == []
    assert restored.messages == [{"role": "user", "content": "persisted"}]


def test_skill_related_calls_are_retained_for_historical_placeholders():
    assistant_message = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "skill_call",
                "type": "function",
                "function": {"name": "skill_review", "arguments": "{}"},
            },
            {
                "id": "core_call",
                "type": "function",
                "function": {"name": "ReadFile", "arguments": "{}"},
            },
        ],
    }

    persistent = persistent_assistant_tool_message(assistant_message)

    assert is_skill_related_tool("skill_review")
    assert is_skill_related_tool("search_tool")
    assert not is_skill_related_tool("ReadFile")
    assert persistent == assistant_message


def test_historical_render_preserves_tool_topology_with_virtualized_outputs(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="read_call",
        tool_name="ReadFile",
        arguments='{"file_path":"app.py"}',
        output="print('large output')" * 100,
    )
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "inspect app"},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "skill_call", "type": "function", "function": {"name": "skill_review", "arguments": "{}"}},
                {
                    "id": "read_call",
                    "type": "function",
                    "function": {"name": "ReadFile", "arguments": '{"file_path":"app.py"}'},
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "skill_call",
            "content": "[Skill output omitted after current turn]",
            "metadata": {"tool_name": "skill_review", "skill_omitted": True},
        },
        {
            "role": "tool",
            "tool_call_id": "read_call",
            "content": "print('large output')" * 100,
            "metadata": {"output_id": output_id, "tool_name": "ReadFile"},
        },
        {"role": "assistant", "content": "done"},
    ]
    runtime.save_messages_now(session_id, messages)

    rendered = runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=[*messages, {"role": "user", "content": "next"}],
        tools=[],
        current_prompt="next",
        current_turn_start=len(messages),
    )

    roles = [(message["role"], message.get("tool_call_id", "")) for message in rendered]
    assert roles[:6] == [
        ("system", ""),
        ("user", ""),
        ("assistant", ""),
        ("tool", "skill_call"),
        ("tool", "read_call"),
        ("assistant", ""),
    ]
    assert "HISTORICAL TOOL INDEX" not in "\n".join(str(message.get("content", "")) for message in rendered)
    assert "Skill output is omitted after the current turn" in rendered[3]["content"]
    assert "Historical tool output virtualized" in rendered[4]["content"]
    assert output_id in rendered[4]["content"]


def test_summary_stage_keeps_recent_context(tmp_path):
    compressor = ContextCompressor(context_window=100, recent_messages_after_summary=1)
    runtime = MemoryRuntime(
        store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        compressor=compressor,
    )
    session_id = runtime.start_session("test")
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "x" * 200},
        {"role": "assistant", "content": "y" * 200},
    ]

    compressed = runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=messages,
        tools=[],
        current_prompt="next",
        summary_text="ENGINEERING STATE\nGOAL:\n- test",
    )

    assert compressed[0]["role"] == "system"
    assert "ENGINEERING STATE" in compressed[1]["content"]
    assert compressed[-1] == messages[-1]


def test_compression_report_contains_required_metrics(tmp_path):
    compressor = ContextCompressor(context_window=1000, tool_preview_chars=5)
    runtime = MemoryRuntime(
        store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        compressor=compressor,
    )
    session_id = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="call_1",
        tool_name="ReadFile",
        arguments="{}",
        output="abcdefg" * 20,
    )
    result = compressor.compress_messages(
        [
            {"role": "user", "content": "x" * 30},
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "abcdefg" * 20,
                "metadata": {"output_id": output_id},
            },
        ],
        current_prompt="next",
        tool_output_refs=runtime._tool_output_refs,
    )
    report = format_compression_report(result)

    assert "current_context_size:" in report
    assert "context_window:" in report
    assert "window_usage:" in report
    assert "action:" in report
    assert "compressed_context_size:" in report


def test_reproducible_tool_classification():
    assert is_reproducible_tool("ReadFile", "content")
    assert is_reproducible_tool("Grep", "content")
    assert not is_reproducible_tool("Bash", "content")
    assert not is_reproducible_tool("WriteFile", "content")
    assert not is_reproducible_tool("ReadFile", "Error: failed")


def test_lrfu_snapshot_round_trip(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    cache = SessionSkillCache()
    cache.touch("skill_a", current_round=1, reward=2.0)

    class SkillRuntimeStub:
        session_skill_cache = cache

    runtime.save_lrfu_snapshot(session_id, SkillRuntimeStub())

    restored_cache = SessionSkillCache()

    class RestoredSkillRuntimeStub:
        session_skill_cache = restored_cache

    runtime.load_lrfu_snapshot(session_id, RestoredSkillRuntimeStub())
    candidates = restored_cache.top_candidates(limit=1, current_round=1)

    assert candidates[0].skill_name == "skill_a"
    assert candidates[0].score == 2.0


def budget_snapshot(usage_ratio: float) -> PromptBudgetSnapshot:
    return PromptBudgetSnapshot(
        context_window=100,
        current_tokens=int(usage_ratio * 100),
        remaining_tokens=max(0, 100 - int(usage_ratio * 100)),
        reserved_reasoning_tokens=0,
        reserved_output_tokens=0,
        reserved_tool_tokens=0,
        usable_tokens=max(0, 100 - int(usage_ratio * 100)),
        usage_ratio=usage_ratio,
        stage=BudgetStage.NORMAL,
    )


def test_checkpoint_decision_requires_completed_turn(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    manager = runtime.checkpoint_manager
    hard_snapshot = budget_snapshot(CONFIG.memory.checkpoint_hard_ratio + 0.01)

    assert not manager.should_checkpoint(TurnState(completed=False, turn_end_index=10), hard_snapshot).should_checkpoint
    assert not manager.should_checkpoint(TurnState(pending_tool_call=True, turn_end_index=10), hard_snapshot).should_checkpoint
    assert not manager.should_checkpoint(TurnState(active_recovery=True, turn_end_index=10), hard_snapshot).should_checkpoint
    assert not manager.should_checkpoint(TurnState(retrying_error=True, turn_end_index=10), hard_snapshot).should_checkpoint


def test_checkpoint_decision_uses_soft_and_hard_thresholds(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    manager = runtime.checkpoint_manager
    low_ratio = max(0.0, CONFIG.memory.checkpoint_soft_ratio - 0.01)
    soft_ratio = min(CONFIG.memory.checkpoint_hard_ratio - 0.01, CONFIG.memory.checkpoint_soft_ratio + 0.01)
    hard_ratio = CONFIG.memory.checkpoint_hard_ratio + 0.01

    low = manager.should_checkpoint(TurnState(turn_end_index=10), budget_snapshot(low_ratio))
    soft = manager.should_checkpoint(TurnState(turn_end_index=10), budget_snapshot(soft_ratio))
    hard = manager.should_checkpoint(TurnState(turn_end_index=1), budget_snapshot(hard_ratio))

    assert not low.should_checkpoint
    assert soft.should_checkpoint
    assert soft.candidate
    assert hard.should_checkpoint
    assert hard.trigger_reason == "hard_threshold"


def test_snapshot_has_version(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "build checkpoint"}]

    snapshot = runtime.create_checkpoint(
        session_id=session_id,
        messages=messages,
        runtime_state={},
        trigger_reason="test",
        usage_ratio=0.9,
    )
    restored = runtime.store.get_conversation_snapshot(snapshot.snapshot_id)

    assert snapshot.snapshot_version == CONFIG.memory.snapshot_version
    assert restored is not None
    assert restored.snapshot_version == CONFIG.memory.snapshot_version


def test_incremental_snapshot_merges_previous_snapshot_and_delta(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    previous = ConversationSnapshot(
        snapshot_id="snapshot-1",
        snapshot_version="1.0",
        session_id="session-1",
        important_decisions=["keep existing decision"],
        unfinished_tasks=["keep existing task"],
        recoverable_context_refs=["ctx-old"],
    )
    delta = SnapshotDelta(
        delta_id="delta-1",
        session_id="session-1",
        base_snapshot_id="snapshot-1",
        turn_start_index=2,
        turn_end_index=4,
        new_decisions=["add new decision"],
        new_unfinished_tasks=["add new task"],
        new_recoverable_context_refs=["ctx-new"],
    )

    snapshot = runtime.checkpoint_manager.create_incremental_snapshot(previous, delta, {})

    assert snapshot.previous_snapshot_id == "snapshot-1"
    assert snapshot.snapshot_version == CONFIG.memory.snapshot_version
    assert snapshot.important_decisions == ["keep existing decision", "add new decision"]
    assert snapshot.unfinished_tasks == ["keep existing task", "add new task"]
    assert snapshot.recoverable_context_refs == ["ctx-old", "ctx-new"]


def test_snapshot_delta_only_uses_messages_since_last_checkpoint(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old user request"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new user request"},
        {"role": "assistant", "content": "new answer"},
    ]

    delta = runtime.checkpoint_manager.create_session_delta(
        session_id,
        messages,
        previous_checkpoint_index=3,
    )

    assert delta.turn_start_index == 3
    assert delta.new_user_intentions == ["new user request"]
    assert "old user request" not in delta.new_user_intentions


def test_rollover_marks_old_session_historical(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    old_messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "old"}]
    runtime.save_messages_now(session_id, old_messages)
    snapshot = ConversationSnapshot(
        snapshot_id="snapshot-1",
        snapshot_version="1.0",
        session_id=session_id,
        overall_task_summary="summary",
    )
    runtime.store.save_conversation_snapshot(snapshot)

    rollover = runtime.rollover_to_new_session(
        session_id=session_id,
        snapshot=snapshot,
        system_prompt_source=old_messages[0],
    )

    historical = runtime.store.get_historical_session(session_id)
    assert rollover.performed
    assert rollover.new_session_id != session_id
    assert historical is not None
    assert historical.status == "historical"

    runtime.save_messages_now(session_id, [{"role": "user", "content": "should not overwrite"}])
    assert runtime.store.load_messages(session_id) == old_messages


def test_rollover_new_session_contains_only_system_and_snapshot(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    snapshot = ConversationSnapshot(
        snapshot_id="snapshot-1",
        snapshot_version="1.0",
        session_id=session_id,
        overall_task_summary="summary",
    )
    runtime.store.save_conversation_snapshot(snapshot)

    rollover = runtime.rollover_to_new_session(
        session_id=session_id,
        snapshot=snapshot,
        system_prompt_source={"role": "system", "content": "sys"},
    )

    assert rollover.new_messages is not None
    assert len(rollover.new_messages) == 2
    assert [message["role"] for message in rollover.new_messages] == ["system", "system"]
    assert rollover.new_messages[1]["content"].startswith("CONVERSATION SNAPSHOT")
    assert runtime.store.load_messages(rollover.new_session_id) == rollover.new_messages


def test_recover_context_works_after_session_rollover(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="call_1",
        tool_name="ReadFile",
        arguments='{"file_path":"old.py"}',
        output="historical content",
    )
    snapshot = ConversationSnapshot(
        snapshot_id="snapshot-1",
        snapshot_version="1.0",
        session_id=session_id,
        recoverable_context_refs=[output_id],
    )
    runtime.store.save_conversation_snapshot(snapshot)
    runtime.rollover_to_new_session(
        session_id=session_id,
        snapshot=snapshot,
        system_prompt_source={"role": "system", "content": "sys"},
    )
    tool = RecoverContext(runtime)

    result = asyncio.run(tool.execute(RecoverContextParams(context_id=output_id)))

    assert not result.is_error
    assert f'"owner_session_id": "{session_id}"' in result.output
    assert result.output.endswith("historical content")


def test_restore_session_returns_snapshot_not_messages(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    runtime.save_messages_now(
        session_id,
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "full old transcript secret"}],
    )
    snapshot = ConversationSnapshot(
        snapshot_id="snapshot-1",
        snapshot_version="1.0",
        session_id=session_id,
        overall_task_summary="summary only",
    )
    runtime.store.save_conversation_snapshot(snapshot)
    runtime.store.mark_session_historical(session_id, snapshot.snapshot_id, "summary only", [])
    tool = RestoreSession(runtime)

    result = asyncio.run(tool.execute(RestoreSessionParams(session_id=session_id)))
    payload = json.loads(result.output)

    assert not result.is_error
    assert payload["snapshot"]["snapshot_id"] == "snapshot-1"
    assert "full old transcript secret" not in result.output
    assert "full old session" in payload["notice"]
    assert "full old transcript secret" not in result.output


def test_restore_session_does_not_persist_merge(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    old_session_id = runtime.start_session("test")
    snapshot = ConversationSnapshot(
        snapshot_id="snapshot-1",
        snapshot_version="1.0",
        session_id=old_session_id,
        overall_task_summary="summary",
    )
    runtime.store.save_conversation_snapshot(snapshot)
    rollover = runtime.rollover_to_new_session(
        session_id=old_session_id,
        snapshot=snapshot,
        system_prompt_source={"role": "system", "content": "sys"},
    )
    assert rollover.new_messages is not None
    tool = RestoreSession(runtime)

    result = asyncio.run(tool.execute(RestoreSessionParams(session_id=old_session_id)))
    active_state = runtime.load_session(rollover.new_session_id)

    assert not result.is_error
    assert active_state is not None
    assert active_state.messages == rollover.new_messages


def test_prefix_cache_prompt_shape_stable_after_rollover():
    first = ConversationSnapshot(
        snapshot_id="snapshot-1",
        snapshot_version="1.0",
        session_id="session-1",
        overall_task_summary="first",
    )
    second = ConversationSnapshot(
        snapshot_id="snapshot-2",
        snapshot_version="1.0",
        session_id="session-2",
        previous_snapshot_id="snapshot-1",
        overall_task_summary="second",
        important_decisions=["decision"],
    )

    first_fields = [line.split(":", 1)[0] for line in format_snapshot_prompt(first).splitlines()[1:]]
    second_fields = [line.split(":", 1)[0] for line in format_snapshot_prompt(second).splitlines()[1:]]

    assert format_snapshot_prompt(first).splitlines()[0] == "CONVERSATION SNAPSHOT"
    assert first_fields == list(SNAPSHOT_FIELD_ORDER)
    assert second_fields == list(SNAPSHOT_FIELD_ORDER)


def test_snapshot_continuity_across_multiple_rollovers(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    first_session = runtime.start_session("test")
    first_snapshot = runtime.create_checkpoint(
        session_id=first_session,
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first goal"},
            {"role": "assistant", "content": "决定采用 checkpoint lifecycle"},
        ],
        runtime_state={"recoverable_context_refs": ["ctx-1"]},
        trigger_reason="hard_threshold",
        usage_ratio=0.9,
    )
    first_rollover = runtime.rollover_to_new_session(
        session_id=first_session,
        snapshot=first_snapshot,
        system_prompt_source={"role": "system", "content": "sys"},
    )
    assert first_rollover.new_messages is not None
    second_snapshot = runtime.create_checkpoint(
        session_id=first_rollover.new_session_id,
        messages=[
            *first_rollover.new_messages,
            {"role": "user", "content": "second goal"},
            {"role": "assistant", "content": "决定保留历史 session immutable"},
        ],
        runtime_state={"recoverable_context_refs": ["ctx-2"]},
        trigger_reason="hard_threshold",
        usage_ratio=0.9,
    )

    assert second_snapshot.previous_snapshot_id == first_snapshot.snapshot_id
    assert "first goal" in second_snapshot.user_intentions
    assert "second goal" in second_snapshot.user_intentions
    assert second_snapshot.recoverable_context_refs == ["ctx-1", "ctx-2"]


def test_recover_context_survives_multiple_rollovers(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    first_session = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=first_session,
        tool_call_id="call_1",
        tool_name="ReadFile",
        arguments='{"file_path":"first.py"}',
        output="first session retained output",
    )
    first_snapshot = runtime.create_checkpoint(
        session_id=first_session,
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first goal"},
            {"role": "tool", "tool_call_id": "call_1", "content": "preview", "metadata": {"output_id": output_id}},
        ],
        runtime_state={"recoverable_context_refs": [output_id]},
        trigger_reason="hard_threshold",
        usage_ratio=0.9,
    )
    first_rollover = runtime.rollover_to_new_session(
        session_id=first_session,
        snapshot=first_snapshot,
        system_prompt_source={"role": "system", "content": "sys"},
    )
    assert first_rollover.new_messages is not None
    second_snapshot = runtime.create_checkpoint(
        session_id=first_rollover.new_session_id,
        messages=[
            *first_rollover.new_messages,
            {"role": "user", "content": "second goal"},
            {"role": "assistant", "content": "continue"},
        ],
        runtime_state={},
        trigger_reason="hard_threshold",
        usage_ratio=0.9,
    )
    runtime.rollover_to_new_session(
        session_id=first_rollover.new_session_id,
        snapshot=second_snapshot,
        system_prompt_source=first_rollover.new_messages[0],
    )
    tool = RecoverContext(runtime)

    result = asyncio.run(tool.execute(RecoverContextParams(context_id=output_id)))

    assert not result.is_error
    assert result.output.endswith("first session retained output")


def test_recover_context_reports_missing_after_owner_session_delete(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="call_1",
        tool_name="ReadFile",
        arguments="{}",
        output="deleted with session",
    )
    runtime.clear_current_session_id()
    runtime.start_session("test")
    assert runtime.delete_session(session_id)
    tool = RecoverContext(runtime)

    result = asyncio.run(tool.execute(RecoverContextParams(context_id=output_id)))

    assert result.is_error
    assert "recoverable context not found" in result.output
