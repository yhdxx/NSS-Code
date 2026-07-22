from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mycodingagent.memory.contracts import ContextEpochControl
from mycodingagent.tool_runtime.base import Tool, ToolResult

if TYPE_CHECKING:
    from mycodingagent.memory import MemoryRuntime


MAX_BATCH_RECOVER_ITEMS = 8
MAX_BATCH_RECOVER_TOTAL_CHARS = 60000


class BatchRecoverContextItem(BaseModel):
    context_id: str = Field(description="Exact context_id from a visible recoverable reference or search result. Do not guess.")
    offset: int = Field(default=0, ge=0, description="Character offset to start reading from.")
    limit: int = Field(default=12000, ge=1, le=50000, description="Maximum number of characters to return for this context_id.")


class BatchRecoverContextParams(BaseModel):
    items: list[BatchRecoverContextItem] = Field(
        description=(
            "Stored context chunks to recover. Submit exact context_id values only. "
            f"The first {MAX_BATCH_RECOVER_ITEMS} items are processed per call; split larger batches into follow-up calls."
        ),
        min_length=1,
        max_length=50,
    )


class BatchRecoverContext(Tool):
    name = "BatchRecoverContext"
    description = (
        "Recover one or more stored context chunks by exact context_id. Use this only when "
        "your answer depends on historical or virtualized evidence that is not currently visible "
        "and each context_id is explicitly available from visible metadata or search results. "
        "Provide all known relevant context_id values in items. Do not use this for evidence "
        "already shown in the current conversation."
    )
    params_model = BatchRecoverContextParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, memory_runtime: MemoryRuntime) -> None:
        self._memory_runtime = memory_runtime

    async def execute(self, params: BatchRecoverContextParams) -> ToolResult:
        await self._memory_runtime.drain()
        processed_items = params.items[:MAX_BATCH_RECOVER_ITEMS]
        total_returned_chars = 0
        results: list[dict[str, Any]] = []
        for index, item in enumerate(processed_items):
            remaining_chars = MAX_BATCH_RECOVER_TOTAL_CHARS - total_returned_chars
            if remaining_chars <= 0:
                results.append(
                    {
                        "index": index,
                        "context_id": item.context_id,
                        "status": "skipped_batch_limit",
                        "error": "batch total returned character limit reached",
                    }
                )
                continue
            effective_limit = min(item.limit, remaining_chars)
            payload = recover_context_payload(
                self._memory_runtime,
                context_id=item.context_id,
                offset=item.offset,
                limit=effective_limit,
                requested_limit=item.limit,
            )
            payload["index"] = index
            if payload.get("status") == "ok":
                total_returned_chars += int(payload.get("returned_chars", 0))
                if effective_limit < item.limit and payload.get("has_more"):
                    payload["status"] = "truncated_by_batch_limit"
            results.append(payload)

        errors = [
            {
                "index": result.get("index"),
                "context_id": result.get("context_id"),
                "status": result.get("status"),
                "error": result.get("error", ""),
            }
            for result in results
            if result.get("status") not in {"ok", "truncated_by_batch_limit"}
        ]
        output = {
            "request_count": len(params.items),
            "processed_count": len(processed_items),
            "skipped_count": max(0, len(params.items) - len(processed_items)),
            "result_count": len(results),
            "total_returned_chars": total_returned_chars,
            "results": results,
            "errors": errors,
        }
        if len(params.items) > len(processed_items):
            output["limit_notice"] = (
                f"Only the first {MAX_BATCH_RECOVER_ITEMS} items were processed. "
                "Submit another BatchRecoverContext call for remaining context_ids if still needed."
            )
        return ToolResult(output=json.dumps(output, ensure_ascii=False, indent=2), is_error=False)


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
        "context. This does not return full historical tool outputs; use BatchRecoverContext only "
        "when exact stored output context_id values are visible."
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
    context_id: str = Field(default="", description="Recoverable context_id when summarizing a tool output.")
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
            "notice": (
                "The summary is available for virtualized or budget-compressed renders. "
                "Raw renders may continue to show the original current-turn content."
            ),
        }
        return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2))


class CommitWorkingContextParams(BaseModel):
    reason: str = Field(description="Why the current multi-turn task context is complete or should be archived.")
    summary: str = Field(description="Dense summary of completed work, decisions, results, and unfinished items.")
    retain_context_ids: list[str] = Field(
        default_factory=list,
        description="Visible context_id values that may still be needed after the working context is archived.",
    )
    active_files: list[str] = Field(
        default_factory=list,
        description="Important project files involved in this working context.",
    )
    next_context_hint: str = Field(
        default="",
        description="Optional guidance for the next working-context epoch.",
    )


class CommitWorkingContext(Tool):
    name = "CommitWorkingContext"
    description = (
        "Close the current multi-turn working-context epoch after the current assistant turn completes. "
        "Use this only when the current task is complete, the user explicitly closes or switches work, or "
        "the visible hot-context notice requests a commit. The model is responsible for semantic context "
        "switches; runtime only forces commits when the hot context exceeds its budget. This tool schedules "
        "archival and never hides messages during the current tool-call chain."
    )
    params_model = CommitWorkingContextParams
    category = "command"
    is_concurrency_safe = False

    def __init__(self, context_control: ContextEpochControl) -> None:
        self._context_control = context_control

    async def execute(self, params: CommitWorkingContextParams) -> ToolResult:
        try:
            state = self._context_control.request_context_epoch_commit(
                reason=params.reason,
                summary=params.summary,
                retain_context_ids=params.retain_context_ids,
                active_files=params.active_files,
                next_context_hint=params.next_context_hint,
                trigger="model",
            )
        except ValueError as exc:
            return ToolResult(output=f"Error: {exc}", is_error=True)
        payload = {
            "status": state.status.value,
            "epoch_id": state.epoch_id,
            "start_message_index": state.start_message_index,
            "trigger": state.trigger,
            "retain_context_ids": state.retain_context_ids,
            "active_files": state.active_files,
            "notice": "The working context will be archived only after the current assistant turn completes.",
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
                "Use BatchRecoverContext(items=[{context_id, offset, limit}]) for specific stored tool outputs."
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


def recover_context_payload(
    memory_runtime: MemoryRuntime,
    *,
    context_id: str,
    offset: int,
    limit: int,
    requested_limit: int | None = None,
) -> dict[str, Any]:
    context_id = context_id.strip()
    if not context_id:
        return {
            "context_id": context_id,
            "status": "invalid_request",
            "error": "context_id is required",
        }
    metadata = memory_runtime.get_context_metadata(context_id)
    if metadata is not None:
        partial = memory_runtime.load_partial_context(context_id, offset=offset, limit=limit)
        if partial is None:
            return {
                "context_id": context_id,
                "status": "not_found",
                "error": "recoverable context not found",
            }
        chunk, next_offset = partial
        start = min(max(0, offset), metadata.content_length)
        return {
            "context_id": metadata.id,
            "status": "ok",
            "owner_session_id": metadata.session_id,
            "tool_call_id": metadata.tool_call_id,
            "tool_name": metadata.tool_name,
            "call_summary": metadata.short_summary,
            "content_type": metadata.content_type.value,
            "content_length": metadata.content_length,
            "reproducible": metadata.reproducible,
            "offset": start,
            "requested_limit": requested_limit if requested_limit is not None else limit,
            "returned_chars": len(chunk),
            "next_offset": next_offset,
            "has_more": next_offset is not None,
            "content": chunk,
        }

    record = memory_runtime.get_tool_output(context_id)
    if record is None:
        return {
            "context_id": context_id,
            "status": "not_found",
            "error": "recoverable context not found",
        }

    output = record.output_text
    start = min(max(0, offset), len(output))
    end = min(start + limit, len(output))
    chunk = output[start:end]
    has_more = end < len(output)
    return {
        "context_id": record.output_id,
        "status": "ok",
        "owner_session_id": record.session_id,
        "tool_call_id": record.tool_call_id,
        "tool_name": record.tool_name,
        "content_length": record.output_size,
        "reproducible": record.reproducible,
        "offset": start,
        "requested_limit": requested_limit if requested_limit is not None else limit,
        "returned_chars": len(chunk),
        "next_offset": end if has_more else None,
        "has_more": has_more,
        "content": chunk,
    }


def truncate_one_line(text: str, *, max_chars: int) -> str:
    one_line = " ".join(text.strip().split())
    if len(one_line) <= max_chars:
        return one_line
    return one_line[: max_chars - 1] + "…"
