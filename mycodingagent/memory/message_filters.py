from __future__ import annotations

from typing import Any


SKILL_RELATED_TOOL_NAMES = {
    "search_tool",
    "Get_all_tool",
    "Get_tool_by_name",
    "search_skill_references",
    "Get_skill_reference",
    "invoke_skill",
}


def is_skill_related_tool(tool_name: str) -> bool:
    return tool_name.startswith("skill_") or tool_name in SKILL_RELATED_TOOL_NAMES


def persistent_assistant_tool_message(assistant_message: dict[str, Any]) -> dict[str, Any] | None:
    tool_calls = list(assistant_message.get("tool_calls", []))
    if not tool_calls:
        return None
    persistent_message: dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
    if assistant_message.get("content"):
        persistent_message["content"] = assistant_message["content"]
    return persistent_message


def remove_trailing_incomplete_tool_call(messages: list[dict[str, Any]]) -> bool:
    """Remove the last assistant tool-call batch when its tool results are incomplete.

    Interrupted turns can persist the assistant request before any (or all) tool
    results are written.  Removing that batch restores a valid model message
    protocol without fabricating tool output.  Only the final tool-call batch is
    considered; historical middle turns are left untouched.
    """
    if not messages:
        return False
    last_role = messages[-1].get("role")
    trailing_interrupt = False
    scan_end = len(messages)
    if (
        last_role == "assistant"
        and messages[-1].get("metadata", {}).get("interrupted") is True
    ):
        trailing_interrupt = True
        scan_end -= 1
        if scan_end == 0:
            return False
        last_role = messages[scan_end - 1].get("role")
    if last_role not in {"assistant", "tool"}:
        return False
    candidate_index = scan_end - 1
    if last_role == "tool":
        while candidate_index >= 0 and messages[candidate_index].get("role") == "tool":
            candidate_index -= 1
    if candidate_index < 0 or messages[candidate_index].get("role") != "assistant":
        return False
    if not messages[candidate_index].get("tool_calls"):
        return False

    assistant = messages[candidate_index]
    expected_ids = {
        str(call.get("id"))
        for call in assistant.get("tool_calls", [])
        if isinstance(call, dict) and call.get("id") is not None
    }
    result_ids: set[str] = set()
    end_index = candidate_index + 1
    while end_index < scan_end and messages[end_index].get("role") == "tool":
        tool_call_id = messages[end_index].get("tool_call_id")
        if tool_call_id is not None:
            result_ids.add(str(tool_call_id))
        end_index += 1

    if expected_ids and expected_ids.issubset(result_ids):
        return False

    if trailing_interrupt:
        end_index = len(messages)
    del messages[candidate_index:end_index]
    return True
