import asyncio

from mycodingagent.code_intelligence.task_graph import PathTaskGraphRuntime
from mycodingagent.memory.runtime import strip_completed_task_graph_messages
from mycodingagent.memory.stores import SQLiteMemoryStore


def test_path_task_graph_builds_directory_tree_and_tracks_agent_states(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    store = SQLiteMemoryStore(tmp_path / "state" / "sessions.sqlite3")
    store.ensure_session(session_id="session-1", model="test")
    runtime = PathTaskGraphRuntime(tmp_path, store=store, session_id_provider=lambda: "session-1")

    async def exercise():
        graph = await runtime.create(["src/main.py"])
        paths = {node["path"] for node in graph["nodes"]}
        assert paths == {"src", "src/main.py"}
        assert all(node["work_status"] == "pending" for node in graph["nodes"])
        assert all(node["test_status"] == "untested" for node in graph["nodes"])
        updated = await runtime.update(
            graph["task_graph_id"],
            [{"path": "src/main.py", "work_status": "modified", "test_status": "passed"}],
        )
        node = next(item for item in updated["nodes"] if item["path"] == "src/main.py")
        assert node["work_status"] == "modified"
        assert node["test_status"] == "passed"
        assert "completed" not in node.values()

    asyncio.run(exercise())
    assert store.load_active_task_graph("session-1")["task_graph_id"]


def test_completed_task_messages_are_hidden_only_from_model_projection():
    class Boundary:
        def context_boundary(self):
            return {"task_graph_id": "tg", "status": "completed"}

    messages = [
        {"role": "user", "content": "before"},
        {"role": "assistant", "content": "work", "metadata": {"task_graph_id": "tg"}},
        {"role": "tool", "content": "result", "metadata": {"task_graph_id": "tg"}},
        {"role": "assistant", "content": "final"},
    ]
    visible = strip_completed_task_graph_messages(messages, Boundary())
    assert [item["content"] for item in visible] == ["before", "final"]
    assert len(messages) == 4


def test_completed_task_hides_untagged_tool_results_with_tagged_assistant_batch():
    class Boundary:
        def context_boundary(self):
            return {"task_graph_id": "tg", "status": "completed"}

    messages = [
        {"role": "user", "content": "finish"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "update",
                    "type": "function",
                    "function": {"name": "UpdateTaskGraph", "arguments": "{}"},
                },
                {
                    "id": "plan",
                    "type": "function",
                    "function": {"name": "update_plan_step", "arguments": "{}"},
                },
            ],
            "metadata": {"task_graph_id": "tg"},
        },
        {"role": "tool", "tool_call_id": "update", "content": "ok"},
        {"role": "tool", "tool_call_id": "plan", "content": "ok"},
        {"role": "assistant", "content": "done"},
    ]

    visible = strip_completed_task_graph_messages(messages, Boundary())

    assert [(item["role"], item.get("content")) for item in visible] == [
        ("user", "finish"),
        ("assistant", "done"),
    ]
