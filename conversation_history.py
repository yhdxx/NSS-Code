from __future__ import annotations

import json


def render_conversation_history(messages: list[dict], *, max_chars_per_message: int = 2000) -> None:
    visible_messages = [
        format_history_message(message, max_chars_per_message=max_chars_per_message)
        for message in messages
    ]
    visible_messages = [message for message in visible_messages if message]
    print("========== 已恢复历史对话 ==========", flush=True)
    if not visible_messages:
        print("(暂无可展示历史消息)", flush=True)
    else:
        print("\n\n".join(visible_messages), flush=True)
    print("==================================", flush=True)


def format_history_message(message: dict, *, max_chars_per_message: int = 2000) -> str:
    role = message.get("role", "")
    if role == "system":
        return ""
    if role == "user":
        return "User: " + truncate_history_text(message_content_to_text(message.get("content", "")), max_chars_per_message)
    if role == "assistant":
        content = message_content_to_text(message.get("content", ""))
        if content:
            return "Assistant: " + truncate_history_text(content, max_chars_per_message)
        tool_names = [
            call.get("function", {}).get("name", "")
            for call in message.get("tool_calls", [])
            if call.get("function", {}).get("name")
        ]
        if tool_names:
            return "Assistant: [调用工具] " + ", ".join(tool_names)
        return ""
    if role == "tool":
        tool_name = message.get("metadata", {}).get("tool_name", "tool")
        return f"Tool: [{tool_name}] 输出已恢复到上下文"
    return f"{role or 'Message'}: " + truncate_history_text(message_content_to_text(message.get("content", "")), max_chars_per_message)


def message_content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def truncate_history_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"
