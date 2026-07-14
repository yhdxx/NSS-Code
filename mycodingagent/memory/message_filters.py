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
