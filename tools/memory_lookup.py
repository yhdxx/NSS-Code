from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from memory import MemoryRuntime


class GetStoredToolOutputParams(BaseModel):
    output_id: str = Field(description="Exact output_id/context_id from a visible recoverable reference or search result. Do not guess.")
    offset: int = Field(default=0, ge=0, description="Character offset to start reading from.")
    limit: int = Field(default=12000, ge=1, le=50000, description="Maximum number of characters to return.")


class GetStoredToolOutput(Tool):
    name = "GetStoredToolOutput"
    description = (
        "Read full or partial stored tool output by exact output_id. Use only when the needed "
        "evidence is not visible in the current working context and a concrete output_id/context_id "
        "is already visible from a recoverable reference or search result. Do not use this for "
        "tool outputs already visible in the current conversation, and do not invent ids from "
        "tool names, offsets, or arguments."
    )
    params_model = GetStoredToolOutputParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, memory_runtime: MemoryRuntime) -> None:
        self._memory_runtime = memory_runtime

    async def execute(self, params: GetStoredToolOutputParams) -> ToolResult:
        await self._memory_runtime.drain()
        return recover_context_output(
            self._memory_runtime,
            context_id=params.output_id,
            offset=params.offset,
            limit=params.limit,
        )


class RecoverContextParams(BaseModel):
    context_id: str = Field(description="Exact context_id from a visible recoverable reference or search result. Do not guess.")
    offset: int = Field(default=0, ge=0, description="Character offset to start reading from.")
    limit: int = Field(default=12000, ge=1, le=50000, description="Maximum number of characters to return.")


class RecoverContext(Tool):
    name = "RecoverContext"
    description = (
        "Recover full or partial stored context by exact context_id. Use only when your answer "
        "depends on historical or virtualized evidence that is not currently visible and the "
        "context_id is explicitly available. Do not use this for evidence already shown in the "
        "current conversation. Prefer partial recovery with offset and limit when the prompt "
        "budget is tight."
    )
    params_model = RecoverContextParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, memory_runtime: MemoryRuntime) -> None:
        self._memory_runtime = memory_runtime

    async def execute(self, params: RecoverContextParams) -> ToolResult:
        await self._memory_runtime.drain()
        return recover_context_output(
            self._memory_runtime,
            context_id=params.context_id,
            offset=params.offset,
            limit=params.limit,
        )


class SearchRecoverableContextParams(BaseModel):
    query: str = Field(default="", description="Keywords for hidden historical/virtualized context metadata. Do not search for content already visible.")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of metadata objects to return.")


class SearchRecoverableContext(Tool):
    name = "SearchRecoverableContext"
    description = (
        "Search stored recoverable context metadata by topic, file path, command, error text, "
        "keyword, or decision. Use only when required evidence is missing from the current visible "
        "conversation and may exist in historical or virtualized context, but you do not yet know "
        "the relevant context_id. Do not use this to retrieve or restate a tool result that is "
        "already visible in the current turn or recent conversation."
    )
    params_model = SearchRecoverableContextParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, memory_runtime: MemoryRuntime) -> None:
        self._memory_runtime = memory_runtime

    async def execute(self, params: SearchRecoverableContextParams) -> ToolResult:
        session_id = self._memory_runtime.get_current_session_id()
        if not session_id:
            return ToolResult(output="Error: no active memory session.", is_error=True)
        await self._memory_runtime.drain()
        contexts = self._memory_runtime.search_context_metadata(session_id, params.query, limit=params.limit)
        payload = {
            "session_id": session_id,
            "query": params.query,
            "match_count": len(contexts),
            "contexts": [context.to_dict() for context in contexts],
        }
        return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2))


class SearchSessionHistoryParams(BaseModel):
    query: str = Field(description="Keywords to search prior conversation turns that are not visible enough in the current context.")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of matching messages to return.")
    include_system: bool = Field(default=False, description="Whether to include system messages in search results.")


class SearchSessionHistory(Tool):
    name = "SearchSessionHistory"
    description = (
        "Search prior conversation turns. Use this only when a needed prior user request, "
        "assistant decision, constraint, or reference is not visible enough in the current working "
        "context. This does not return full historical tool outputs; use RecoverContext only when "
        "an exact stored output is hidden and a concrete context_id is available."
    )
    params_model = SearchSessionHistoryParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, memory_runtime: MemoryRuntime, *, preview_chars: int = 1200) -> None:
        self._memory_runtime = memory_runtime
        self._preview_chars = preview_chars

    async def execute(self, params: SearchSessionHistoryParams) -> ToolResult:
        session_id = self._memory_runtime.get_current_session_id()
        if not session_id:
            return ToolResult(output="Error: no active memory session.", is_error=True)
        await self._memory_runtime.drain()

        query = " ".join(params.query.split())
        if not query:
            return ToolResult(output="Error: query is empty.", is_error=True)

        state = self._memory_runtime.load_session(session_id)
        if state is None:
            return ToolResult(output=f"Error: active memory session not found: {session_id}", is_error=True)

        query_lower = query.lower()
        results: list[dict[str, Any]] = []
        for turn in state.historical_turns:
            searchable = "\n".join(
                [
                    turn.user_content,
                    turn.assistant_content,
                    json.dumps([asdict(item) for item in turn.tool_metadata], ensure_ascii=False, default=str),
                ]
            )
            if query_lower not in searchable.lower():
                continue
            results.append(
                {
                    "turn_id": turn.turn_id,
                    "turn_index": turn.turn_index,
                    "user_preview": truncate_one_line(turn.user_content, max_chars=self._preview_chars),
                    "assistant_preview": truncate_one_line(turn.assistant_content, max_chars=self._preview_chars),
                    "tool_metadata": [asdict(item) for item in turn.tool_metadata],
                }
            )
            if len(results) >= params.limit:
                break
        if not results:
            for index, message in enumerate(state.messages):
                role = str(message.get("role", ""))
                if role == "system" and not params.include_system:
                    continue
                text = message_to_search_text(message)
                if query_lower not in text.lower():
                    continue
                results.append(
                    {
                        "message_index": index,
                        "role": role,
                        "preview": truncate_one_line(text, max_chars=self._preview_chars),
                    }
                )
                if len(results) >= params.limit:
                    break

        payload = {
            "session_id": session_id,
            "query": query,
            "match_count": len(results),
            "results": results,
        }
        return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2))


class GetRecentConversationTurnsParams(BaseModel):
    limit: int = Field(default=5, ge=1, le=30, description="Maximum number of recent historical turns to return.")


class GetRecentConversationTurns(Tool):
    name = "GetRecentConversationTurns"
    description = (
        "Inspect recent conversation structure and turn summaries. Use this only when the current "
        "visible context is insufficient to understand recent task flow, prior decisions, or which "
        "historical hidden outputs may matter. Do not use it when the relevant recent tool output "
        "or answer is already visible."
    )
    params_model = GetRecentConversationTurnsParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, memory_runtime: MemoryRuntime) -> None:
        self._memory_runtime = memory_runtime

    async def execute(self, params: GetRecentConversationTurnsParams) -> ToolResult:
        session_id = self._memory_runtime.get_current_session_id()
        if not session_id:
            return ToolResult(output="Error: no active memory session.", is_error=True)
        await self._memory_runtime.drain()
        turns = self._memory_runtime.store.load_historical_turns(session_id, limit=params.limit)
        payload = {
            "session_id": session_id,
            "turn_count": len(turns),
            "turns": [
                {
                    "turn_id": turn.turn_id,
                    "turn_index": turn.turn_index,
                    "user_content": turn.user_content,
                    "assistant_content": turn.assistant_content,
                    "tool_metadata": [asdict(item) for item in turn.tool_metadata],
                }
                for turn in turns
            ],
        }
        return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2))


class SummarizeCurrentTurnMessageParams(BaseModel):
    message_id: str = Field(default="", description="tool_call_id or current-turn message id to replace with a summary.")
    context_id: str = Field(default="", description="Recoverable context_id/output_id when summarizing a tool output.")
    summary: str = Field(description="Dense replacement summary for the current-turn message.")
    reason: str = Field(description="Why this summary is necessary. Required for revisions.")
    focus: str = Field(default="", description="Optional focus area, such as errors, file list, or final facts.")


class SummarizeCurrentTurnMessage(Tool):
    name = "SummarizeCurrentTurnMessage"
    description = (
        "Replace a large current-turn message/tool output with a compact summary while keeping a recovery reference. "
        "Use only when the context budget is tight. Revisions are allowed only when the previous summary is wrong "
        "or new important information must be incorporated; repeated identical summaries are rejected."
    )
    params_model = SummarizeCurrentTurnMessageParams
    category = "read"
    is_concurrency_safe = False

    def __init__(self, memory_runtime: MemoryRuntime) -> None:
        self._memory_runtime = memory_runtime

    async def execute(self, params: SummarizeCurrentTurnMessageParams) -> ToolResult:
        try:
            metadata = self._memory_runtime.summarize_current_turn_message(
                message_id=params.message_id,
                context_id=params.context_id,
                summary=params.summary,
                reason=params.reason,
                focus=params.focus,
            )
        except ValueError as exc:
            return ToolResult(output=f"Error: {exc}", is_error=True)
        payload = {
            "status": "ok",
            "metadata": asdict(metadata),
            "notice": "The current-turn message will be replaced by this summary on the next model call.",
        }
        return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2))


class RestoreSessionParams(BaseModel):
    session_id: str = Field(description="Historical session id whose checkpoint snapshot should be restored.")


class RestoreSession(Tool):
    name = "RestoreSession"
    description = (
        "Read the latest checkpoint snapshot for a historical session. "
        "This returns snapshot state only, not full old session messages."
    )
    params_model = RestoreSessionParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, memory_runtime: MemoryRuntime) -> None:
        self._memory_runtime = memory_runtime

    async def execute(self, params: RestoreSessionParams) -> ToolResult:
        await self._memory_runtime.drain()
        snapshot = self._memory_runtime.restore_historical_session_snapshot(params.session_id)
        if snapshot is None:
            return ToolResult(output=f"Error: historical session snapshot not found: {params.session_id}", is_error=True)
        payload = {
            "session_id": params.session_id,
            "snapshot": asdict(snapshot),
            "notice": (
                "Snapshot restored as temporary working context only; full old session_messages were not restored. "
                "Use RecoverContext(context_id, offset, limit) for specific stored tool outputs."
            ),
        }
        return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2))


def message_to_search_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        text = content
    else:
        text = json.dumps(content, ensure_ascii=False, default=str)
    tool_calls = message.get("tool_calls")
    if tool_calls:
        text += "\n" + json.dumps(tool_calls, ensure_ascii=False, default=str)
    return text


def recover_context_output(
    memory_runtime: MemoryRuntime,
    *,
    context_id: str,
    offset: int,
    limit: int,
) -> ToolResult:
    metadata = memory_runtime.get_context_metadata(context_id)
    if metadata is not None:
        partial = memory_runtime.load_partial_context(context_id, offset=offset, limit=limit)
        if partial is None:
            return ToolResult(output=f"Error: recoverable context not found: {context_id}", is_error=True)
        chunk, next_offset = partial
        header = {
            "context_id": metadata.id,
            "owner_session_id": metadata.session_id,
            "tool_call_id": metadata.tool_call_id,
            "tool_name": metadata.tool_name,
            "storage_key": metadata.storage_key,
            "short_summary": metadata.short_summary,
            "content_type": metadata.content_type.value,
            "content_length": metadata.content_length,
            "token_count": metadata.token_count,
            "reproducible": metadata.reproducible,
            "offset": offset,
            "returned_chars": len(chunk),
            "next_offset": next_offset,
            "has_more": next_offset is not None,
        }
        return ToolResult(output=json.dumps(header, ensure_ascii=False, indent=2) + "\n\n" + chunk)

    record = memory_runtime.get_tool_output(context_id)
    if record is None:
        return ToolResult(output=f"Error: recoverable context not found: {context_id}", is_error=True)

    output = record.output_text
    start = min(offset, len(output))
    end = min(start + limit, len(output))
    chunk = output[start:end]
    has_more = end < len(output)
    header = {
        "output_id": record.output_id,
        "context_id": record.output_id,
        "owner_session_id": record.session_id,
        "tool_call_id": record.tool_call_id,
        "tool_name": record.tool_name,
        "arguments_json": record.arguments_json,
        "output_size": record.output_size,
        "reproducible": record.reproducible,
        "offset": start,
        "returned_chars": len(chunk),
        "next_offset": end if has_more else None,
        "has_more": has_more,
    }
    return ToolResult(output=json.dumps(header, ensure_ascii=False, indent=2) + "\n\n" + chunk)


def truncate_one_line(text: str, *, max_chars: int) -> str:
    one_line = " ".join(text.strip().split())
    if len(one_line) <= max_chars:
        return one_line
    return one_line[: max_chars - 1] + "…"
