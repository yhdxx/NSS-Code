from __future__ import annotations

import json

from mycodingagent.terminal_ui.output import (
    render_assistant_markdown,
    render_assistant_text,
    render_tool_calls,
    render_tool_result_preview,
)


def render_conversation_history(messages: list[dict], *, max_chars_per_message: int = 2000) -> None:
    print("========== 已恢复历史对话 ==========", flush=True)
    rendered_any = False
    call_id_to_tool_name: dict[str, str] = {}
    for message in messages:
        role = message.get("role", "")
        if role == "system":
            continue
        rendered_any = True
        if role == "user":
            render_assistant_text(
                truncate_history_text(message_content_to_text(message.get("content", "")), max_chars_per_message),
                label="User",
            )
            continue
        if role == "assistant":
            content = message_content_to_text(message.get("content", ""))
            if content:
                render_assistant_markdown(
                    truncate_history_text(content, max_chars_per_message),
                    label="Assistant",
                )
            tool_calls = list(message.get("tool_calls", []) or [])
            if tool_calls:
                for call in tool_calls:
                    call_id = str(call.get("id") or "")
                    tool_name = str(call.get("function", {}).get("name") or "")
                    if call_id and tool_name:
                        call_id_to_tool_name[call_id] = tool_name
                render_tool_calls(tool_calls)
            continue
        if role == "tool":
            tool_name = str(message.get("metadata", {}).get("tool_name") or "")
            tool_name = tool_name or call_id_to_tool_name.get(str(message.get("tool_call_id") or ""), "tool")
            render_tool_result_preview(
                tool_name=tool_name,
                content=truncate_history_text(
                    message_content_to_text(message.get("content", "")),
                    max_chars_per_message,
                ),
                is_error=bool(message.get("metadata", {}).get("is_error")),
            )
            continue
        render_assistant_text(
            truncate_history_text(message_content_to_text(message.get("content", "")), max_chars_per_message),
            label=role or "Message",
        )
    if not rendered_any:
        print("(暂无可展示历史消息)", flush=True)
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
        content = truncate_history_text(message_content_to_text(message.get("content", "")), max_chars_per_message)
        return f"Tool: [{tool_name}] " + (content or "（无输出）")
    return f"{role or 'Message'}: " + truncate_history_text(message_content_to_text(message.get("content", "")), max_chars_per_message)


def message_content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def truncate_history_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"
