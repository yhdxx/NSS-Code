from __future__ import annotations

from typing import Any

from mycodingagent.memory import MemoryRuntime


def has_conversation_content(messages: list[dict]) -> bool:
    return any(
        message.get("role") != "system"
        and bool(message.get("content") or message.get("tool_calls"))
        for message in messages
    )


def save_current_session_if_needed(
    *,
    memory_runtime: MemoryRuntime,
    messages: list[dict],
    skill_runtime: Any | None,
    file_state_cache: Any | None = None,
) -> str:
    if not has_conversation_content(messages):
        return ""
    session_id = memory_runtime.get_current_session_id() or memory_runtime.start_session()
    memory_runtime.save_messages(session_id, messages)
    memory_runtime.save_lrfu_snapshot(session_id, skill_runtime)
    memory_runtime.save_file_state_snapshot(session_id, file_state_cache)
    return session_id
