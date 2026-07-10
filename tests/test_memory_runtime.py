from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import sqlite3
import sys
import types
from types import SimpleNamespace
from time import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import openai  # noqa: F401
except ModuleNotFoundError:
    openai_stub = types.ModuleType("openai")
    openai_stub.AsyncOpenAI = object
    openai_stub.APIConnectionError = Exception
    openai_stub.APIError = Exception
    openai_stub.APITimeoutError = Exception
    sys.modules["openai"] = openai_stub

from mycodingagent.llm_runtime import client as agent_client
from mycodingagent.configuration import CONFIG
from mycodingagent.memory import (
    ContextEpochStatus,
    ConversationSnapshot,
    MemoryRuntime,
    SQLiteMemoryStore,
    SnapshotDelta,
)
from mycodingagent.memory.budget import BudgetStage, PromptBudgetSnapshot
from mycodingagent.memory.checkpoint import SNAPSHOT_FIELD_ORDER, TurnState, format_snapshot_prompt
from mycodingagent.memory.compressor import ContextCompressor, is_reproducible_tool
from mycodingagent.memory.runtime import ContextMode, estimate_raw_uncached_tokens, format_compression_report
from mycodingagent.memory.stores import session_preview
from mycodingagent.memory.message_filters import is_skill_related_tool, persistent_assistant_tool_message
from mycodingagent.memory.session_switch import has_conversation_content, save_current_session_if_needed
from mycodingagent.skill_runtime.session_skill_cache import SessionSkillCache
from mycodingagent.llm_runtime.context import (
    PromptRenderer,
    RuntimeContextBuilder,
    extract_user_request_from_rendered_prompt,
    is_rendered_runtime_prompt,
)
from mycodingagent.tool_runtime import create_default_registry
from mycodingagent.tool_runtime.memory_lookup import (
    CommitWorkingContext,
    CommitWorkingContextParams,
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
from mycodingagent.tool_runtime.memory_lookup import GetRecentConversationTurns


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


def test_workspace_changes_render_inside_current_user_runtime_context():
    tracker = WorkspaceTrackerStub(["app.py"], omitted=2)

    runtime_context = RuntimeContextBuilder(workspace_tracker=tracker).build()
    rendered = PromptRenderer.render_current_user_message(runtime_context, "work")

    assert rendered.role == "user"
    assert is_rendered_runtime_prompt(rendered.content)
    assert extract_user_request_from_rendered_prompt(rendered.content) == "work"
    assert runtime_context.workspace_changes.paths == ("app.py",)
    assert runtime_context.workspace_changes.omitted == 2
    assert '"workspace_changes"' in rendered.runtime_context_json
    assert '"app.py"' in rendered.runtime_context_json


def test_temporary_system_messages_are_disabled():
    rendered = agent_client.build_turn_temporary_system_messages(None)

    assert rendered == []


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
                return "", [agent_client.PendingToolCall("call_1", "FakeTool", "{}")], None
            return "done", [], None

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
        assert messages_seen[0][1]["role"] == "user"
        assert is_rendered_runtime_prompt(messages_seen[0][1]["content"])
        assert extract_user_request_from_rendered_prompt(messages_seen[0][1]["content"]) == "do work"
        assert "changed.py" in messages_seen[0][1]["content"]
        assert messages_seen[1][-1]["role"] == "tool"
        assert messages_seen[1][1]["content"] == messages_seen[0][1]["content"]
        assert "changed.py" in messages_seen[1][1]["content"]
        assert not any(
            message.get("role") == "system"
            and (
                "环境通知" in message.get("content", "")
                or "Historical tool outputs may have been virtualized" in message.get("content", "")
            )
            for message in updated
        )
        assert not any(is_rendered_runtime_prompt(str(message.get("content", ""))) for message in updated)
        assert updated == history

    asyncio.run(scenario())


def test_fixed_system_prompt_contains_work_context_sufficiency_protocol(monkeypatch):
    async def scenario():
        seen_messages = []

        async def fake_stream_one_round(_client, _model, messages, tools):
            seen_messages.append(copy.deepcopy(messages))
            return "done", [], None

        monkeypatch.setattr(agent_client, "stream_one_round", fake_stream_one_round)

        _text, updated = await agent_client.ask_deepseek(
            client=object(),
            prompt="hello",
            registry=object(),
            tools=[],
            messages=None,
        )

        system_prompt = seen_messages[0][0]["content"]
        assert "Work Context Sufficiency Protocol" in system_prompt
        assert "Before producing the final answer, evaluate whether the current Working Context is sufficient" in system_prompt
        assert "Evidence First Rule" in system_prompt
        assert "never infer facts that could be verified by available historical context" in system_prompt
        assert "Do not follow a fixed recovery sequence" in system_prompt
        assert "GetRecentConversationTurns\n" not in system_prompt
        assert "SearchSessionHistory\n" not in system_prompt
        assert updated[0]["content"] == system_prompt

    asyncio.run(scenario())


def test_recovery_tool_descriptions_emphasize_evidence_without_fixed_order():
    descriptions = {
        "GetStoredToolOutput": GetStoredToolOutput.description,
        "RecoverContext": RecoverContext.description,
        "SearchRecoverableContext": SearchRecoverableContext.description,
        "SearchSessionHistory": SearchSessionHistory.description,
        "GetRecentConversationTurns": GetRecentConversationTurns.description,
    }

    assert "Do not use this for tool outputs already visible" in descriptions["GetStoredToolOutput"]
    assert "Do not use this for evidence already shown" in descriptions["RecoverContext"]
    assert "you do not yet know the relevant context_id" in descriptions["SearchRecoverableContext"]
    assert "needed prior user request" in descriptions["SearchSessionHistory"]
    assert "recent task flow" in descriptions["GetRecentConversationTurns"]
    assert "already visible" in descriptions["SearchRecoverableContext"]
    assert "current visible context is insufficient" in descriptions["GetRecentConversationTurns"]
    combined = "\n".join(descriptions.values())
    assert "GetRecentConversationTurns -> SearchSessionHistory" not in combined
    assert "SearchSessionHistory -> SearchRecoverableContext" not in combined


def test_recovery_protocol_forbids_recovering_visible_context(monkeypatch):
    async def scenario():
        seen_messages = []

        async def fake_stream_one_round(_client, _model, messages, _tools):
            seen_messages.append(messages)
            return "ok", [], None

        monkeypatch.setattr(agent_client, "stream_one_round", fake_stream_one_round)

        history = [{"role": "user", "content": "visible tool result"}]
        await agent_client.ask_deepseek(
            client=object(),
            prompt="repeat visible result",
            registry=object(),
            tools=[],
            messages=None,
        )

        system_prompt = seen_messages[0][0]["content"]
        assert "answer from the visible context directly" in system_prompt
        assert "do not call GetStoredToolOutput" in system_prompt
        assert "Never invent output_id/context_id values" in system_prompt

    asyncio.run(scenario())


def test_ask_deepseek_allows_multi_step_recovery_loop(monkeypatch):
    async def scenario():
        tool_calls_seen = []

        async def fake_stream_one_round(_client, _model, messages, tools):
            if len(tool_calls_seen) == 0:
                return "", [agent_client.PendingToolCall("call_1", "SearchRecoverableContext", '{"query":"build failure"}')], None
            if len(tool_calls_seen) == 1:
                assert messages[-1]["role"] == "tool"
                assert "ctx_1" in messages[-1]["content"]
                return "", [agent_client.PendingToolCall("call_2", "RecoverContext", '{"context_id":"ctx_1"}')], None
            assert messages[-1]["role"] == "tool"
            assert "exact recovered evidence" in messages[-1]["content"]
            return "final answer from evidence", [], None

        async def fake_execute_local_tool(registry, tool_name, raw_args, skill_runtime):
            tool_calls_seen.append(tool_name)
            if tool_name == "SearchRecoverableContext":
                return '{"contexts":[{"context_id":"ctx_1","summary":"build failure"}]}'
            if tool_name == "RecoverContext":
                return "exact recovered evidence"
            return "unexpected"

        monkeypatch.setattr(agent_client, "stream_one_round", fake_stream_one_round)
        monkeypatch.setattr(agent_client, "execute_local_tool", fake_execute_local_tool)

        text, _updated = await agent_client.ask_deepseek(
            client=object(),
            prompt="why did the build fail?",
            registry=object(),
            tools=[],
            messages=[{"role": "system", "content": "fixed"}],
        )

        assert tool_calls_seen == ["SearchRecoverableContext", "RecoverContext"]
        assert text == "final answer from evidence"

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


def test_token_usage_persists_and_loads_with_session(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")

    first = runtime.record_token_usage(
        session_id=session_id,
        prompt_tokens=100,
        prompt_cache_hit_tokens=40,
        prompt_cache_miss_tokens=60,
        completion_tokens=7,
        total_tokens=107,
        model="test",
        prompt_hash="prompt-a",
        tools_hash="tools-a",
    )
    second = runtime.record_token_usage(
        session_id=session_id,
        prompt_tokens=20,
        prompt_cache_hit_tokens=5,
        prompt_cache_miss_tokens=15,
        completion_tokens=3,
        total_tokens=23,
        model="test",
        prompt_hash="prompt-b",
        tools_hash="tools-a",
    )
    restored = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3")).load_session(session_id)

    assert first.request_count == 1
    assert second.request_count == 2
    assert restored is not None
    assert restored.token_usage.request_count == 2
    assert restored.token_usage.prompt_tokens == 120
    assert restored.token_usage.prompt_cache_hit_tokens == 45
    assert restored.token_usage.prompt_cache_miss_tokens == 75
    assert restored.token_usage.completion_tokens == 10
    assert restored.token_usage.total_tokens == 130


def test_ask_deepseek_records_token_usage_and_prints_summaries(monkeypatch, tmp_path, capsys):
    async def scenario():
        runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))

        async def fake_stream_one_round(_client, _model, messages, tools):
            return (
                "done",
                [],
                SimpleNamespace(
                    prompt_tokens=100,
                    prompt_cache_hit_tokens=70,
                    prompt_cache_miss_tokens=30,
                    completion_tokens=8,
                    total_tokens=108,
                ),
            )

        monkeypatch.setattr(agent_client, "stream_one_round", fake_stream_one_round)
        monkeypatch.setattr(agent_client, "DEBUG", False)

        text, _updated = await agent_client.ask_deepseek(
            client=object(),
            prompt="hello",
            registry=object(),
            tools=[],
            messages=[{"role": "system", "content": "fixed"}],
            memory_runtime=runtime,
        )
        session_id = runtime.get_current_session_id()
        assert session_id is not None
        restored = runtime.load_session(session_id)
        await runtime.close()
        return text, restored

    text, restored = asyncio.run(scenario())
    output = capsys.readouterr().out

    assert text == "done"
    assert "[PromptDebug]" not in output
    assert "=================" in output
    assert "[Token] 输入 100 (缓存命中 70, 未命中 30) | 输出 8 | 总计 108" in output
    assert "[Token][本轮] 请求 1 | 输入 100 (缓存命中 70, 未命中 30) | 输出 8 | 总计 108" in output
    assert "[Token][会话] 请求 1 | 输入 100 (缓存命中 70, 未命中 30) | 输出 8 | 总计 108" in output
    assert restored is not None
    assert restored.token_usage.request_count == 1
    assert restored.token_usage.prompt_cache_hit_tokens == 70
    assert restored.token_usage.prompt_cache_miss_tokens == 30


def test_token_output_flags_control_terminal_lines(monkeypatch, tmp_path, capsys):
    async def run_case(name: str, *, step_token: bool, round_token: bool, conversation_token: bool):
        runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / f"{name}.sqlite3"))

        async def fake_stream_one_round(_client, _model, messages, tools):
            return (
                "done",
                [],
                SimpleNamespace(
                    prompt_tokens=100,
                    prompt_cache_hit_tokens=70,
                    prompt_cache_miss_tokens=30,
                    completion_tokens=8,
                    total_tokens=108,
                ),
            )

        monkeypatch.setattr(agent_client, "stream_one_round", fake_stream_one_round)
        monkeypatch.setattr(agent_client, "DEBUG", False)
        monkeypatch.setattr(agent_client, "STEP_TOKEN", step_token)
        monkeypatch.setattr(agent_client, "ROUND_TOKEN", round_token)
        monkeypatch.setattr(agent_client, "CONVERSATION_TOKEN", conversation_token)

        text, _updated = await agent_client.ask_deepseek(
            client=object(),
            prompt="hello",
            registry=object(),
            tools=[],
            messages=[{"role": "system", "content": "fixed"}],
            memory_runtime=runtime,
        )
        session_id = runtime.get_current_session_id()
        assert session_id is not None
        restored = runtime.load_session(session_id)
        await runtime.close()
        return text, restored

    cases = [
        ("no_step", False, True, True, False, True, True),
        ("no_round", True, False, True, True, False, True),
        ("no_conversation", True, True, False, True, True, False),
    ]
    for name, step_token, round_token, conversation_token, expect_step, expect_round, expect_conversation in cases:
        text, restored = asyncio.run(
            run_case(
                name,
                step_token=step_token,
                round_token=round_token,
                conversation_token=conversation_token,
            )
        )
        output = capsys.readouterr().out

        assert text == "done"
        assert ("[Token] 输入 100 (缓存命中 70, 未命中 30) | 输出 8 | 总计 108" in output) is expect_step
        assert (
            "[Token][本轮] 请求 1 | 输入 100 (缓存命中 70, 未命中 30) | 输出 8 | 总计 108" in output
        ) is expect_round
        assert (
            "[Token][会话] 请求 1 | 输入 100 (缓存命中 70, 未命中 30) | 输出 8 | 总计 108" in output
        ) is expect_conversation
        assert restored is not None
        assert restored.token_usage.request_count == 1
        assert restored.token_usage.prompt_cache_hit_tokens == 70
        assert restored.token_usage.prompt_cache_miss_tokens == 30


def test_debug_true_prints_prompt_debug(monkeypatch, capsys):
    async def scenario():
        async def fake_stream_one_round(_client, _model, messages, tools):
            return "done", [], None

        monkeypatch.setattr(agent_client, "stream_one_round", fake_stream_one_round)
        monkeypatch.setattr(agent_client, "DEBUG", True)

        return await agent_client.ask_deepseek(
            client=object(),
            prompt="hello",
            registry=object(),
            tools=[],
            messages=[{"role": "system", "content": "fixed"}],
        )

    text, _updated = asyncio.run(scenario())
    output = capsys.readouterr().out

    assert text == "done"
    assert "[PromptDebug]" in output
    assert "fixed_system_tokens≈" in output
    assert "temporary_system_tokens≈" in output
    assert "historical_messages_tokens≈" in output
    assert "runtime_context_tokens≈" in output
    assert "rendered_prompt_tokens≈" in output
    assert "stored_user_prompt_tokens≈" in output
    assert "current_turn_tokens≈" in output
    assert "tools_tokens≈" in output
    assert "first_changed_section=" in output


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


def test_fork_session_copies_messages_and_switches_current_session(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    source_session_id = runtime.start_session("test")
    messages = [{"role": "user", "content": "fork me"}, {"role": "assistant", "content": "done"}]
    runtime.save_messages_now(source_session_id, messages)

    fork_session_id = runtime.fork_session(source_session_id, model="fork-model")

    assert fork_session_id is not None
    assert fork_session_id != source_session_id
    assert runtime.get_current_session_id() == fork_session_id
    source_state = runtime.store.load_session(source_session_id)
    fork_state = runtime.store.load_session(fork_session_id)
    assert source_state is not None
    assert fork_state is not None
    assert source_state.messages == messages
    assert fork_state.messages == messages
    assert runtime.store.list_sessions(limit=10)[0].session_id == fork_session_id


def test_fork_session_uses_override_messages_and_copies_snapshots(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    source_session_id = runtime.start_session("test")
    runtime.save_messages_now(source_session_id, [{"role": "user", "content": "stored"}])
    runtime.store.save_lrfu_snapshot(session_id=source_session_id, lrfu={"skills": {"python": {"uses": 2}}})
    runtime.store.save_file_state_snapshot(
        session_id=source_session_id,
        file_state={"files": [{"path": "a.py", "content": "old", "mtime_ns": 1}]},
    )
    override_messages = [{"role": "user", "content": "live current"}]

    fork_session_id = runtime.fork_session(source_session_id, messages=override_messages)

    assert fork_session_id is not None
    fork_state = runtime.store.load_session(fork_session_id)
    assert fork_state is not None
    assert fork_state.messages == override_messages
    assert fork_state.latest_lrfu == {"skills": {"python": {"uses": 2}}}
    assert fork_state.latest_file_state == {"files": [{"path": "a.py", "content": "old", "mtime_ns": 1}]}


def test_clear_flow_saves_current_session_and_starts_new_empty_session(tmp_path):
    async def scenario():
        runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
        current_session_id = runtime.start_session("test")
        messages = [{"role": "user", "content": "current work"}, {"role": "assistant", "content": "done"}]
        await runtime.drain()

        saved_id = save_current_session_if_needed(
            memory_runtime=runtime,
            messages=messages,
            skill_runtime=None,
        )
        await runtime.drain()
        runtime.clear_current_session_id()
        new_session_id = runtime.start_session("test")
        await runtime.drain()

        saved_state = runtime.store.load_session(current_session_id)
        new_state = runtime.store.load_session(new_session_id)
        await runtime.close()

        assert saved_id == current_session_id
        assert new_session_id != current_session_id
        assert saved_state is not None
        assert saved_state.messages == messages
        assert new_state is not None
        assert new_state.messages == []

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
        "CommitWorkingContext",
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
    assert runtime.context_mode(session_id) == ContextMode.RAW


def test_raw_mode_large_tool_output_uses_preview_without_virtualizing_session(tmp_path):
    compressor = ContextCompressor(context_window=20_000)
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

    assert runtime.context_mode(session_id) == ContextMode.RAW
    assert "[Recoverable context stored]" in prompt_content
    assert f"context_id: {output_id}" in prompt_content
    assert "RecoverContext(context_id, offset, limit)" in prompt_content
    assert "GetStoredToolOutput(output_id, offset, limit)" in prompt_content
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
    runtime.force_context_virtualized(session_id)

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


def test_short_session_keeps_raw_historical_tool_output(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="read_call",
        tool_name="ReadFile",
        arguments='{"file_path":"app.py"}',
        output="print('inline')",
    )
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "inspect app"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "read_call",
                    "type": "function",
                    "function": {"name": "ReadFile", "arguments": '{"file_path":"app.py"}'},
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "read_call",
            "content": "print('inline')",
            "metadata": {"output_id": output_id, "tool_name": "ReadFile"},
        },
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "next"},
    ]

    rendered = runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=messages,
        tools=[],
        current_prompt="next",
        current_turn_start=len(messages) - 1,
    )

    assert runtime.context_mode(session_id) == ContextMode.RAW
    assert rendered[3]["content"] == "print('inline')"
    assert "Historical tool output virtualized" not in "\n".join(str(message.get("content", "")) for message in rendered)
    assert "metadata" not in rendered[3]


def test_context_switches_to_virtualized_when_raw_miss_cost_is_higher(tmp_path):
    compressor = ContextCompressor(context_window=1200)
    runtime = MemoryRuntime(
        store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        compressor=compressor,
    )
    session_id = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="read_call",
        tool_name="ReadFile",
        arguments='{"file_path":"large.py"}',
        output="z" * 6000,
    )
    stable_prefix = [{"role": "system", "content": "system"}]
    previous = [
        *stable_prefix,
        {"role": "user", "content": "inspect large"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "read_call",
                    "type": "function",
                    "function": {"name": "ReadFile", "arguments": '{"file_path":"large.py"}'},
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "read_call",
            "content": "z" * 6000,
            "metadata": {"output_id": output_id, "tool_name": "ReadFile"},
        },
        {"role": "assistant", "content": "done"},
    ]
    current = [
        *stable_prefix,
        {"role": "user", "content": "inspect large changed"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "read_call",
                    "type": "function",
                    "function": {"name": "ReadFile", "arguments": '{"file_path":"large.py"}'},
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "read_call",
            "content": "z" * 6000,
            "metadata": {"output_id": output_id, "tool_name": "ReadFile"},
        },
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "next"},
    ]
    runtime._last_raw_rendered_messages[session_id] = previous

    rendered = runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=current,
        tools=[],
        current_prompt="next",
        current_turn_start=len(current) - 1,
    )

    assert runtime.context_mode(session_id) == ContextMode.VIRTUALIZED
    assert "Historical tool output virtualized" in rendered[3]["content"]
    assert output_id in rendered[3]["content"]


def test_virtualized_tool_metadata_prefers_model_intent(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="read_call",
        tool_name="ReadFile",
        arguments='{"file_path":"app.py","intent":"读取入口文件"}',
        output="print('inline')",
        metadata={"intent": "读取入口文件", "mcp_server": "fake"},
    )
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "inspect app"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "read_call",
                    "type": "function",
                    "function": {
                        "name": "ReadFile",
                        "arguments": '{"file_path":"app.py","intent":"读取入口文件"}',
                    },
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "read_call",
            "content": "print('inline')",
            "metadata": {
                "output_id": output_id,
                "tool_name": "ReadFile",
                "intent": "读取入口文件",
                "mcp_server": "fake",
            },
        },
        {"role": "assistant", "content": "done"},
    ]
    runtime.save_messages_now(session_id, messages)
    runtime.force_context_virtualized(session_id)

    rendered = runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=[*messages, {"role": "user", "content": "next"}],
        tools=[],
        current_prompt="next",
        current_turn_start=len(messages),
    )

    tool_content = rendered[3]["content"]
    assert "Historical tool output virtualized" in tool_content
    assert '"intent": "读取入口文件"' in tool_content
    assert '"mcp_server": "fake"' in tool_content


def test_context_switch_prints_mode_transition_notice(tmp_path, capsys):
    compressor = ContextCompressor(context_window=1200)
    runtime = MemoryRuntime(
        store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        compressor=compressor,
    )
    session_id = runtime.start_session("test")
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="read_call",
        tool_name="ReadFile",
        arguments='{"file_path":"large.py"}',
        output="z" * 6000,
    )
    previous = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "inspect large"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "read_call",
                    "type": "function",
                    "function": {"name": "ReadFile", "arguments": '{"file_path":"large.py"}'},
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "read_call",
            "content": "z" * 6000,
            "metadata": {"output_id": output_id, "tool_name": "ReadFile"},
        },
        {"role": "assistant", "content": "done"},
    ]
    current = [
        {**previous[0]},
        {"role": "user", "content": "inspect large changed"},
        copy.deepcopy(previous[2]),
        copy.deepcopy(previous[3]),
        copy.deepcopy(previous[4]),
        {"role": "user", "content": "next"},
    ]
    runtime._last_raw_rendered_messages[session_id] = previous

    runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=current,
        tools=[],
        current_prompt="next",
        current_turn_start=len(current) - 1,
    )

    output = capsys.readouterr().out
    assert "[CONTEXT MODE SWITCH]" in output
    assert "mode_transition: raw -> virtualized" in output
    assert "switched: true" in output


def test_context_virtualized_mode_is_one_way(tmp_path):
    compressor = ContextCompressor(context_window=900)
    runtime = MemoryRuntime(
        store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        compressor=compressor,
    )
    session_id = runtime.start_session("test")
    runtime.force_context_virtualized(session_id)

    rendered = runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "small"},
        ],
        tools=[],
        current_prompt="small",
        current_turn_start=1,
    )

    assert runtime.context_mode(session_id) == ContextMode.VIRTUALIZED
    assert rendered[0]["role"] == "system"


def test_raw_uncached_tokens_start_at_first_changed_message():
    previous = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "same"},
        {"role": "assistant", "content": "old"},
    ]
    current = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "same"},
        {"role": "assistant", "content": "new"},
        {"role": "user", "content": "tail"},
    ]

    assert estimate_raw_uncached_tokens(previous, current) == estimate_raw_uncached_tokens(None, current[2:])


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
    assert "ENGINEERING STATE" not in "\n".join(str(message.get("content", "")) for message in compressed)
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


def test_virtualized_session_keeps_multi_turn_working_context_raw_until_commit(tmp_path):
    runtime = MemoryRuntime(
        store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        compressor=ContextCompressor(context_window=100_000),
    )
    session_id = runtime.start_session("test")
    runtime.force_context_virtualized(session_id)
    output_id = runtime.save_tool_output(
        session_id=session_id,
        tool_call_id="read_call",
        tool_name="ReadFile",
        arguments='{"file_path":"app.py"}',
        output="important implementation details",
    )
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "query1 inspect implementation"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "read_call",
                    "type": "function",
                    "function": {"name": "ReadFile", "arguments": '{"file_path":"app.py"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "read_call",
            "content": "important implementation details",
            "metadata": {"output_id": output_id, "tool_name": "ReadFile"},
        },
        {"role": "assistant", "content": "query1 answer"},
    ]

    first = runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=messages,
        tools=[],
        current_prompt="query1 inspect implementation",
        current_turn_start=1,
    )
    assert next(message for message in first if message.get("role") == "tool")["content"] == (
        "important implementation details"
    )

    messages.extend(
        [
            {"role": "user", "content": "query2 modify that implementation"},
            {"role": "assistant", "content": "query2 completed"},
        ]
    )
    second = runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=messages,
        tools=[],
        current_prompt="query2 modify that implementation",
        current_turn_start=5,
    )
    assert next(message for message in second if message.get("role") == "tool")["content"] == (
        "important implementation details"
    )

    runtime.request_context_epoch_commit(
        reason="implementation task complete",
        summary="Inspected and modified app.py.",
        retain_context_ids=[output_id],
        active_files=["app.py"],
    )
    next_epoch = runtime.finalize_pending_context_epoch(session_id=session_id, messages=messages)
    assert next_epoch is not None
    messages.append({"role": "user", "content": "query3 unrelated topic"})

    third = runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=messages,
        tools=[],
        current_prompt="query3 unrelated topic",
        current_turn_start=len(messages) - 1,
    )
    historical_tool = next(message for message in third if message.get("role") == "tool")
    assert "Historical tool output virtualized" in historical_tool["content"]
    assert output_id in historical_tool["content"]


def test_commit_working_context_tool_is_deferred_and_idempotent(tmp_path):
    runtime = MemoryRuntime(store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    session_id = runtime.start_session("test")
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "complete task"},
        {"role": "assistant", "content": "done"},
    ]
    runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=messages,
        tools=[],
        current_prompt="complete task",
        current_turn_start=1,
    )
    tool = CommitWorkingContext(runtime)
    params = CommitWorkingContextParams(
        reason="task complete",
        summary="Completed the task and verified the result.",
        active_files=["app.py", "app.py"],
    )

    first = asyncio.run(tool.execute(params))
    second = asyncio.run(tool.execute(params))

    assert not first.is_error
    assert not second.is_error
    pending = runtime.get_active_context_epoch(session_id)
    assert pending is not None
    assert pending.status == ContextEpochStatus.PENDING_COMMIT
    assert pending.active_files == ["app.py"]
    assert pending.end_message_index is None

    runtime.finalize_pending_context_epoch(session_id=session_id, messages=messages)
    epochs = runtime.store.load_context_epochs(session_id)
    assert [epoch.status for epoch in epochs] == [
        ContextEpochStatus.COMMITTED,
        ContextEpochStatus.ACTIVE,
    ]
    assert epochs[0].end_message_index == len(messages)
    assert epochs[1].start_message_index == len(messages)
    assert runtime.context_mode(session_id) == ContextMode.VIRTUALIZED

    restored_runtime = MemoryRuntime(store=runtime.store)
    restored_state = restored_runtime.load_session(session_id)
    assert restored_state is not None
    assert restored_runtime.context_mode(session_id) == ContextMode.VIRTUALIZED
    assert restored_state.context_epoch is not None
    assert restored_state.context_epoch.epoch_id == epochs[1].epoch_id


def test_hot_context_threshold_schedules_runtime_commit(tmp_path):
    runtime = MemoryRuntime(
        store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        compressor=ContextCompressor(context_window=1_000),
    )
    session_id = runtime.start_session("test")
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "x" * 1_700},
        {"role": "assistant", "content": "done"},
    ]

    rendered = runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=messages,
        tools=[],
        current_prompt="large task",
        current_turn_start=1,
    )

    assert any("HOT WORKING CONTEXT NOTICE" in str(message.get("content", "")) for message in rendered)
    pending = runtime.get_active_context_epoch(session_id)
    assert pending is not None
    assert pending.status == ContextEpochStatus.PENDING_COMMIT
    assert pending.trigger == "runtime"


def test_hot_context_warning_does_not_schedule_commit(tmp_path):
    runtime = MemoryRuntime(
        store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        compressor=ContextCompressor(context_window=1_000),
    )
    session_id = runtime.start_session("test")
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "x" * 1_200},
        {"role": "assistant", "content": "done"},
    ]

    rendered = runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=messages,
        tools=[],
        current_prompt="warning task",
        current_turn_start=1,
    )

    assert any("HOT WORKING CONTEXT NOTICE" in str(message.get("content", "")) for message in rendered)
    state = runtime.get_active_context_epoch(session_id)
    assert state is not None
    assert state.status == ContextEpochStatus.ACTIVE
    snapshot = runtime.hot_context_budget_snapshot(session_id=session_id, messages=messages, current_turn_start=1)
    assert snapshot.warning
    assert not snapshot.force_commit


def test_pending_context_epoch_is_finalized_on_safe_session_resume(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    runtime = MemoryRuntime(store=store)
    session_id = runtime.start_session("test")
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "finish work"},
        {"role": "assistant", "content": "completed"},
    ]
    runtime.prepare_messages_for_model(
        session_id=session_id,
        messages=messages,
        tools=[],
        current_prompt="finish work",
        current_turn_start=1,
    )
    runtime.request_context_epoch_commit(
        reason="task complete",
        summary="Finished and verified the task.",
    )
    runtime.save_messages_now(session_id, messages)

    restored_runtime = MemoryRuntime(store=store)
    restored_state = restored_runtime.load_session(session_id)

    assert restored_state is not None
    assert restored_state.context_epoch is not None
    assert restored_state.context_epoch.status == ContextEpochStatus.ACTIVE
    assert restored_state.context_epoch.start_message_index == len(messages)
    assert restored_runtime.context_mode(session_id) == ContextMode.VIRTUALIZED
    assert [epoch.status for epoch in store.load_context_epochs(session_id)] == [
        ContextEpochStatus.COMMITTED,
        ContextEpochStatus.ACTIVE,
    ]


def test_legacy_session_migration_keeps_last_complete_turn_hot(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    session_id = "legacy-session"
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "first task"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "last task"},
        {"role": "assistant", "content": "last answer"},
    ]
    store.ensure_session(session_id=session_id, model="test")
    store.save_messages(session_id=session_id, messages=messages)
    runtime = MemoryRuntime(store=store)

    state = runtime.load_session(session_id)

    assert state is not None
    epoch = runtime.get_active_context_epoch(session_id)
    assert epoch is not None
    assert epoch.start_message_index == 3
    restored = MemoryRuntime(store=store).load_session(session_id)
    assert restored is not None
    assert restored.context_epoch is not None
    assert restored.context_epoch.epoch_id == epoch.epoch_id
