from __future__ import annotations

import json
import sqlite3

from multiAgent.models import MultiAgentRun, RunStatus
from multiAgent.store import MultiAgentStore
from mycodingagent.commands import CommandContext
from mycodingagent.commands.handlers import build_command_registry
from mycodingagent.dashboard.server import DashboardDataProvider
from mycodingagent.memory import SQLiteMemoryStore, TokenUsageRecord
from mycodingagent.skill_runtime.user_skill_cache import UserSkillCache


def test_dashboard_state_reads_runtime_tables(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("print('hello')\n", encoding="utf-8")

    memory_db = tmp_path / "sessions.sqlite3"
    memory_store = SQLiteMemoryStore(memory_db)
    memory_store.ensure_session(
        session_id="s1",
        model="test-model",
        workspace_root=str(workspace),
        workspace_label="workspace",
    )
    memory_store.save_messages(
        session_id="s1",
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    )
    memory_store.save_token_usage(
        TokenUsageRecord(
            usage_id="u1",
            session_id="s1",
            request_index=1,
            prompt_tokens=10,
            completion_tokens=3,
            total_tokens=13,
            model="test-model",
            prompt_hash="abc",
            tools_hash="def",
            metadata={"runtime_context_hash": "ctx"},
        )
    )
    memory_store.save_model_context(
        context_id="ctx1",
        session_id="s1",
        request_index=1,
        model_messages=[{"role": "user", "content": "<RUNTIME_CONTEXT>{}</RUNTIME_CONTEXT>"}],
        tools=[{"type": "function", "function": {"name": "ReadFile", "description": "read", "parameters": {}}}],
        rendered_prompt="<RUNTIME_CONTEXT>{}</RUNTIME_CONTEXT>",
        prompt_hash="model-prompt",
        tools_hash="model-tools",
        metadata={"message_count": 1, "tool_count": 1},
    )
    with sqlite3.connect(memory_db) as conn:
        conn.execute(
            """
            INSERT INTO session_context_snapshots(
                snapshot_id, session_id, compressed_messages_json, summary_text, pressure_ratio, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("snap1", "s1", json.dumps([{"role": "user", "content": "rendered"}]), "summary", 0.2, 1.0),
        )

    multi_db = tmp_path / "multi_agent.sqlite3"
    multi_store = MultiAgentStore(multi_db)
    run = MultiAgentRun.create(task="build ui")
    run.status = RunStatus.COMPLETED
    run.scheduled_tasks["task1"] = {"status": "passed", "summary": "done"}
    run.subagent_messages["plan"] = [{"role": "assistant", "content": "plan"}]
    multi_store.save_run(run)

    lrfu_db = tmp_path / "user_skill_lrfu.sqlite3"
    cache = UserSkillCache(lrfu_db)
    cache.start_session(user_id="u", session_id="s1")
    cache.record_skill_call(user_id="u", session_id="s1", skill_name="skill_frontend", session_skill_call_round=1)
    cache.commit_session(user_id="u", session_id="s1")

    provider = DashboardDataProvider(
        memory_db=memory_db,
        multi_agent_db=multi_db,
        skill_lrfu_db=lrfu_db,
        workspace_root=workspace,
    )
    state = provider.state(session_id="s1")

    assert state["selected_session_id"] == "s1"
    assert len(state["messages"]) == 3
    first_user_turn = next(turn for turn in state["turns"] if turn["user"] is not None)
    assert first_user_turn["user"]["content"] == "hello"
    assert state["model_context"]["kind"] == "persisted_model_request"
    assert state["model_context"]["latest_messages"][0]["content"] == "<RUNTIME_CONTEXT>{}</RUNTIME_CONTEXT>"
    assert state["model_context"]["requests"][0]["tools"][0]["function"]["name"] == "ReadFile"
    assert state["token_usage"][0]["metadata_json"]["runtime_context_hash"] == "ctx"
    assert state["multi_agent_runs"][0]["scheduled_tasks"]["task1"]["status"] == "passed"
    assert state["lrfu"]["user_skill_lrfu"][0]["skill_name"] == "skill_frontend"
    assert state["project"]["files"][0]["path"] == "app.py"


def test_dashboard_file_payload_is_workspace_scoped(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "ok.txt").write_text("ok", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    provider = DashboardDataProvider(
        memory_db=tmp_path / "missing_sessions.sqlite3",
        multi_agent_db=tmp_path / "missing_multi.sqlite3",
        skill_lrfu_db=tmp_path / "missing_lrfu.sqlite3",
        workspace_root=workspace,
    )

    assert provider.file_payload("ok.txt")["content"] == "ok"
    assert provider.file_payload("../outside.txt")["error"] == "file_not_found_or_outside_workspace"


def test_dashboard_command_starts_server(monkeypatch, tmp_path, capsys):
    import mycodingagent.commands.handlers as handlers

    class FakeMemoryRuntime:
        workspace_root = str(tmp_path)

    class FakeServer:
        def serve_forever(self):
            return None

    calls = {}

    def fake_build_server(**kwargs):
        calls.update(kwargs)
        return FakeServer()

    monkeypatch.setattr("mycodingagent.dashboard.server.build_server", fake_build_server)
    monkeypatch.setattr(handlers, "_dashboard_server", None)
    monkeypatch.setattr(handlers, "_dashboard_thread", None)

    registry = build_command_registry()
    result = __import__("asyncio").run(
        registry.execute(
            "/dashboard --host 127.0.0.1 --port 9876",
            CommandContext(memory_runtime=FakeMemoryRuntime(), skill_runtime=None, messages=[]),
        )
    )

    assert result.handled
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 9876
    assert calls["workspace_root"] == str(tmp_path)
    assert "运行时看板已启动：http://127.0.0.1:9876" in capsys.readouterr().out
