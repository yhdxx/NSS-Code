from __future__ import annotations

import hashlib
import json
from typing import Any

from mycodingagent.memory.models import SessionState
from mycodingagent.tool_runtime import ToolRegistry


def session_source_hash(messages: list[dict[str, Any]]) -> str:
    payload = json.dumps(_storage_messages(messages), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_storage_payload(
    *,
    session_state: SessionState,
    tool_registry: ToolRegistry | None,
    existing_memories: list[dict[str, Any]],
    extraction_id: str,
    existing_global_memories: list[dict[str, Any]] | None = None,
    existing_workflow_staging_memories: list[dict[str, Any]] | None = None,
    existing_workspace_memories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    global_memories = existing_global_memories if existing_global_memories is not None else []
    workflow_memories = existing_workflow_staging_memories if existing_workflow_staging_memories is not None else []
    workspace_memories = (
        existing_workspace_memories if existing_workspace_memories is not None else existing_memories
    )
    return {
        "extraction_id": extraction_id,
        "session": {
            "session_id": session_state.session_id,
            "workspace_root": session_state.workspace_root,
            "workspace_label": session_state.workspace_label,
            "workspace_fingerprint": session_state.workspace_fingerprint,
            "messages": _storage_messages(session_state.messages),
        },
        "tool_catalog": tool_catalog(tool_registry),
        "existing_long_term_memories": existing_memories,
        "existing_global_memories": global_memories,
        "existing_workflow_staging_memories": workflow_memories,
        "existing_workspace_memories": workspace_memories,
        "instructions": {
            "tool_outputs_omitted": True,
            "submit_tool": "SubmitLongTermMemoryPatch",
        },
    }


def recent_user_assistant_messages(messages: list[dict[str, Any]], *, max_turns: int) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role", ""))
        if role not in {"user", "assistant"}:
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        result.append({"role": role, "content": content})
    return result[-max(1, max_turns * 2) :]


def tool_catalog(tool_registry: ToolRegistry | None) -> list[dict[str, str]]:
    if tool_registry is None:
        return []
    return [
        {"name": tool.name, "description": tool.description}
        for tool in tool_registry.list_tools()
    ]


def _storage_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        role = str(message.get("role", ""))
        if role == "system":
            continue
        if role == "tool":
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            content = str(message.get("content", ""))
            rendered.append(
                {
                    "index": index,
                    "role": "tool",
                    "tool_call_id": message.get("tool_call_id", ""),
                    "result_status": _tool_result_status(content, metadata),
                    "is_error": _tool_result_is_error(content, metadata),
                    "output_size": len(content),
                    "output_omitted": True,
                    "metadata": {
                        key: value
                        for key, value in metadata.items()
                        if key in {"tool_name", "intent", "mcp_server", "mcp_tool", "operation", "name"}
                    },
                }
            )
            continue
        item: dict[str, Any] = {"index": index, "role": role}
        if "content" in message:
            item["content"] = message.get("content")
        if role == "assistant" and message.get("tool_calls"):
            item["tool_calls"] = [_tool_call_payload(call) for call in message.get("tool_calls", [])]
        rendered.append(item)
    return rendered


def _tool_call_payload(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    raw_arguments = str(function.get("arguments", ""))
    try:
        parsed_args = json.loads(raw_arguments) if raw_arguments else {}
    except json.JSONDecodeError:
        parsed_args = {}
    parsed_args = parsed_args if isinstance(parsed_args, dict) else {}
    return {
        "id": call.get("id", ""),
        "tool_name": function.get("name", ""),
        "arguments": parsed_args if parsed_args else raw_arguments,
        "intent": parsed_args.get("intent", ""),
    }


def _tool_result_status(content: str, metadata: dict[str, Any]) -> str:
    if _tool_result_is_error(content, metadata):
        return "error"
    return "success"


def _tool_result_is_error(content: str, metadata: dict[str, Any]) -> bool:
    if metadata.get("is_error"):
        return True
    return content.startswith(("Error:", "Tool execution error:", "错误：", "工具执行错误："))
