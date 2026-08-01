from __future__ import annotations

import sqlite3

from mycodingagent.memory.message_filters import remove_trailing_incomplete_tool_call
from mycodingagent.sqlite_utils import ClosingSQLiteConnection


def _assistant(*ids: str) -> dict:
    return {
        "role": "assistant",
        "tool_calls": [{"id": value, "type": "function", "function": {"name": "ReadFile", "arguments": "{}"}} for value in ids],
    }


def test_removes_tool_call_without_results():
    messages = [{"role": "user", "content": "read"}, _assistant("a")]
    assert remove_trailing_incomplete_tool_call(messages)
    assert messages == [{"role": "user", "content": "read"}]


def test_removes_partially_completed_multi_call_batch_and_results():
    messages = [
        {"role": "user", "content": "read"},
        _assistant("a", "b"),
        {"role": "tool", "tool_call_id": "a", "content": "ok"},
    ]
    assert remove_trailing_incomplete_tool_call(messages)
    assert len(messages) == 1


def test_keeps_complete_tool_call_batch():
    messages = [
        _assistant("a", "b"),
        {"role": "tool", "tool_call_id": "a", "content": "ok"},
        {"role": "tool", "tool_call_id": "b", "content": "ok"},
    ]
    assert not remove_trailing_incomplete_tool_call(messages)
    assert len(messages) == 3


def test_does_not_touch_normal_assistant_tail():
    messages = [_assistant("a"), {"role": "assistant", "content": "done"}]
    assert not remove_trailing_incomplete_tool_call(messages)
    assert len(messages) == 2


def test_removes_incomplete_call_before_interruption_marker():
    messages = [
        {"role": "user", "content": "read"},
        _assistant("a"),
        {"role": "assistant", "content": "interrupted", "metadata": {"interrupted": True}},
    ]
    assert remove_trailing_incomplete_tool_call(messages)
    assert messages == [{"role": "user", "content": "read"}]


def test_closing_connection_closes_after_commit_and_rollback(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    with sqlite3.connect(db_path, factory=ClosingSQLiteConnection) as conn:
        conn.execute("CREATE TABLE values_table (value INTEGER)")
        assert not conn.in_transaction
    try:
        conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        pass
    else:
        raise AssertionError("connection remained open after context exit")

    try:
        with sqlite3.connect(db_path, factory=ClosingSQLiteConnection) as conn:
            conn.execute("INSERT INTO values_table VALUES (1)")
            raise RuntimeError("rollback")
    except RuntimeError:
        pass
    try:
        conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        pass
    else:
        raise AssertionError("connection remained open after rollback")
