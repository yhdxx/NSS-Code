from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mycodingagent.memory.contracts import ContextEpochControl
from mycodingagent.tool_runtime.base import Tool, ToolResult

if TYPE_CHECKING:
    from mycodingagent.memory import MemoryRuntime


MAX_BATCH_RECOVER_ITEMS = 8
MAX_BATCH_RECOVER_TOTAL_CHARS = 60000


class BatchRecoverContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_id: str = Field(description="可见恢复引用或搜索结果中的准确 context_id，不得猜测")
    section: Literal["arguments", "output", "both"] = Field(
        default="both",
        description="恢复原始工具参数、原始工具输出或两者",
    )
    arguments_offset: int = Field(default=0, ge=0, description="原始工具参数的字符偏移量")
    arguments_limit: int = Field(default=12000, ge=1, le=50000, description="最多返回的参数字符数")
    output_offset: int = Field(default=0, ge=0, description="原始工具输出的字符偏移量")
    output_limit: int = Field(default=12000, ge=1, le=50000, description="最多返回的输出字符数")


class BatchRecoverContextParams(BaseModel):
    items: list[BatchRecoverContextItem] = Field(
        description=(
            "要恢复的已存储上下文块，只能提交准确的 context_id。"
            f"每次调用处理前 {MAX_BATCH_RECOVER_ITEMS} 项；更大的批次应拆分为后续调用。"
        ),
        min_length=1,
        max_length=50,
    )


class BatchRecoverContext(Tool):
    name = "BatchRecoverContext"
    description = (
        "根据准确的 context_id 恢复一个或多个已存储上下文块。仅当回答依赖当前不可见的历史或虚拟化证据，"
        "并且每个 context_id 都明确来自可见元数据或搜索结果时使用。将所有已知且相关的 context_id 放入 items。"
        "使用 section 选择 arguments、output 或 both，并分别用 arguments_offset/arguments_limit 与 "
        "output_offset/output_limit 分页；当前对话中已经显示的证据不要重复恢复。"
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
                        "error": "已达到 batch 返回字符总量上限",
                    }
                )
                continue
            payload = recover_context_payload(
                self._memory_runtime,
                context_id=item.context_id,
                section=item.section,
                arguments_offset=item.arguments_offset,
                arguments_limit=item.arguments_limit,
                output_offset=item.output_offset,
                output_limit=item.output_limit,
                total_limit=remaining_chars,
            )
            payload["index"] = index
            total_returned_chars += int(payload.pop("returned_chars", 0))
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
                f"本次只处理了前 {MAX_BATCH_RECOVER_ITEMS} 项。"
                "如果仍需要其余 context_id，请再次调用 BatchRecoverContext。"
            )
        return ToolResult(output=json.dumps(output, ensure_ascii=False, indent=2), is_error=False)


class SearchRecoverableContextParams(BaseModel):
    query: str = Field(default="", description="用于搜索隐藏历史或虚拟化上下文元数据的关键词；不要搜索已经可见的内容")
    limit: int = Field(default=10, ge=1, le=50, description="最多返回的元数据对象数量")


class SearchRecoverableContext(Tool):
    name = "SearchRecoverableContext"
    description = (
        "按主题、文件路径、命令、错误文本、关键词或决策搜索可恢复上下文元数据。仅当当前可见对话缺少必要证据，"
        "证据可能存在于历史或虚拟化上下文中，但尚不知道相关 context_id 时使用。"
        "不要用它重新获取或复述当前轮次或近期对话中已经可见的工具结果。"
    )
    params_model = SearchRecoverableContextParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, memory_runtime: MemoryRuntime) -> None:
        self._memory_runtime = memory_runtime

    async def execute(self, params: SearchRecoverableContextParams) -> ToolResult:
        session_id = self._memory_runtime.get_current_session_id()
        if not session_id:
            return ToolResult(output="错误：当前没有活动的记忆会话。", is_error=True)
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
    query: str = Field(description="用于搜索当前上下文中不可充分见的历史对话轮次的关键词")
    limit: int = Field(default=10, ge=1, le=50, description="最多返回的匹配消息数量")
    include_system: bool = Field(default=False, description="搜索结果是否包含 system 消息")


class SearchSessionHistory(Tool):
    name = "SearchSessionHistory"
    description = (
        "搜索历史对话轮次。仅当所需的历史用户请求、Assistant 决策、约束或引用在当前工作上下文中不可充分见时使用。"
        "本工具不会返回完整的历史工具输出；只有准确的已存储输出 context_id 可见时才使用 BatchRecoverContext。"
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
            return ToolResult(output="错误：当前没有活动的记忆会话。", is_error=True)
        await self._memory_runtime.drain()

        query = " ".join(params.query.split())
        if not query:
            return ToolResult(output="错误：query 为空。", is_error=True)

        state = self._memory_runtime.load_session(session_id)
        if state is None:
            return ToolResult(output=f"错误：未找到活动的记忆会话：{session_id}", is_error=True)

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
    limit: int = Field(default=5, ge=1, le=30, description="最多返回的近期历史轮次数量")


class GetRecentConversationTurns(Tool):
    name = "GetRecentConversationTurns"
    description = (
        "检查近期对话结构和轮次摘要。仅当当前可见上下文不足以理解近期任务流程、先前决策或哪些隐藏历史输出可能相关时使用。"
        "相关的近期工具输出或答案已经可见时不要使用。"
    )
    params_model = GetRecentConversationTurnsParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, memory_runtime: MemoryRuntime) -> None:
        self._memory_runtime = memory_runtime

    async def execute(self, params: GetRecentConversationTurnsParams) -> ToolResult:
        session_id = self._memory_runtime.get_current_session_id()
        if not session_id:
            return ToolResult(output="错误：当前没有活动的记忆会话。", is_error=True)
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
    message_id: str = Field(default="", description="要用摘要替换的 tool_call_id 或当前轮次消息 ID")
    context_id: str = Field(default="", description="摘要工具输出时对应的可恢复 context_id")
    summary: str = Field(description="当前轮次消息的紧凑替换摘要")
    reason: str = Field(description="需要该摘要的原因；修订摘要时必填")
    focus: str = Field(default="", description="可选关注点，例如错误、文件列表或最终事实")


class SummarizeCurrentTurnMessage(Tool):
    name = "SummarizeCurrentTurnMessage"
    description = (
        "使用紧凑摘要替换当前轮次中的大型消息或工具输出，同时保留恢复引用。仅在上下文预算紧张时使用。"
        "只有先前摘要错误或必须加入新的重要信息时才允许修订；重复的相同摘要会被拒绝。"
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
            return ToolResult(output=f"错误：{exc}", is_error=True)
        payload = {
            "status": "ok",
            "metadata": asdict(metadata),
            "notice": (
                "该摘要可用于虚拟化或预算压缩后的上下文渲染；RAW 模式仍可能显示当前轮次的原始内容。"
            ),
        }
        return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2))


class CommitWorkingContextParams(BaseModel):
    model_config = ConfigDict(extra="allow")

    reason: str = Field(description="为什么应在本轮结束后提交当前热工作上下文 epoch")
    commit_note: str = Field(default="", description="本次 epoch 提交的可选简短说明；不要在此总结完整任务历史")
    retain_context_ids: list[str] = Field(
        default_factory=list,
        description="当前热 epoch 转为冷上下文后仍可能需要的可见 context_id",
    )
    active_files: list[str] = Field(
        default_factory=list,
        description="当前工作上下文涉及的重要项目文件",
    )
    next_context_hint: str = Field(
        default="",
        description="下一个工作上下文 epoch 的可选指引",
    )


class CommitWorkingContext(Tool):
    name = "CommitWorkingContext"
    description = (
        "安排在当前 Assistant 轮次结束后提交热工作上下文 epoch。仅当当前任务完成、用户明确结束或切换工作，"
        "或者可见热上下文通知要求提交时使用。模型负责识别语义上下文切换；Runtime 只在热上下文超过预算时强制提交。"
        "本工具安排从热到冷的 epoch 轮换，不会在当前工具调用链中隐藏消息，也不是检查点或 rollover 摘要生成器。"
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
                summary=commit_context_note(params),
                retain_context_ids=params.retain_context_ids,
                active_files=params.active_files,
                next_context_hint=params.next_context_hint,
                trigger="model",
            )
        except ValueError as exc:
            return ToolResult(output=f"错误：{exc}", is_error=True)
        payload = {
            "status": state.status.value,
            "epoch_id": state.epoch_id,
            "start_message_index": state.start_message_index,
            "trigger": state.trigger,
            "retain_context_ids": state.retain_context_ids,
            "active_files": state.active_files,
            "notice": "只有当前 Assistant 轮次结束后，工作上下文才会归档。",
        }
        return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2))


def commit_context_note(params: CommitWorkingContextParams) -> str:
    note = params.commit_note.strip()
    if note:
        return note
    extra = getattr(params, "model_extra", None)
    legacy_summary = extra.get("summary") if isinstance(extra, dict) else None
    if isinstance(legacy_summary, str) and legacy_summary.strip():
        return legacy_summary.strip()
    reason = " ".join(params.reason.split())
    if reason:
        return f"模型请求提交工作上下文：{reason}"
    return "模型请求提交工作上下文。"


class RestoreSessionParams(BaseModel):
    session_id: str = Field(description="要恢复检查点快照的历史会话 ID")


class RestoreSession(Tool):
    name = "RestoreSession"
    description = (
        "读取历史会话的最新检查点快照。只返回快照状态，不返回完整的旧会话消息。"
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
            return ToolResult(output=f"错误：未找到历史会话快照：{params.session_id}", is_error=True)
        payload = {
            "session_id": params.session_id,
            "snapshot": asdict(snapshot),
            "notice": (
                "快照仅作为临时工作上下文恢复，未恢复完整的旧 session_messages。"
                "需要特定的已存储工具调用时，使用 BatchRecoverContext 并分别指定 arguments/output 分页参数。"
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
    section: Literal["arguments", "output", "both"],
    arguments_offset: int,
    arguments_limit: int,
    output_offset: int,
    output_limit: int,
    total_limit: int,
) -> dict[str, Any]:
    context_id = context_id.strip()
    if not context_id:
        return {
            "context_id": context_id,
            "status": "invalid_request",
            "error": "必须提供 context_id",
        }
    record = memory_runtime.get_tool_output(context_id)
    metadata = memory_runtime.get_context_metadata(context_id)
    fallback_output = memory_runtime.load_context(context_id) if record is None and metadata is not None else None
    if record is None and fallback_output is None:
        return {
            "context_id": context_id,
            "status": "not_found",
            "error": "未找到可恢复上下文",
            "returned_chars": 0,
        }

    owner_session_id = record.session_id if record is not None else metadata.session_id
    tool_call_id = record.tool_call_id if record is not None else metadata.tool_call_id
    tool_name = record.tool_name if record is not None else metadata.tool_name
    payload: dict[str, Any] = {
        "context_id": record.output_id if record is not None else metadata.id,
        "status": "ok",
        "owner_session_id": owner_session_id,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
    }
    remaining = max(0, total_limit)
    returned_chars = 0
    truncated_by_batch_limit = False
    available_sections = 0

    if section in {"arguments", "both"}:
        if record is None:
            payload["arguments"] = {
                "status": "unavailable",
                "error": "该 context_id 没有已存储的原始工具参数",
            }
        else:
            effective_limit = min(arguments_limit, remaining)
            arguments_payload = recover_text_section(
                record.arguments_json,
                offset=arguments_offset,
                limit=effective_limit,
                requested_limit=arguments_limit,
            )
            payload["arguments"] = arguments_payload
            returned = int(arguments_payload["returned_chars"])
            returned_chars += returned
            remaining -= returned
            available_sections += 1
            if effective_limit < arguments_limit and arguments_payload["has_more"]:
                truncated_by_batch_limit = True

    if section in {"output", "both"}:
        if record is not None:
            output_text = record.output_text
        else:
            output_text = fallback_output
        if output_text is None:
            payload["output"] = {
                "status": "unavailable",
                "error": "该 context_id 没有可恢复的工具输出",
            }
        else:
            effective_limit = min(output_limit, remaining)
            output_payload = recover_text_section(
                output_text,
                offset=output_offset,
                limit=effective_limit,
                requested_limit=output_limit,
            )
            payload["output"] = output_payload
            returned = int(output_payload["returned_chars"])
            returned_chars += returned
            remaining -= returned
            available_sections += 1
            if effective_limit < output_limit and output_payload["has_more"]:
                truncated_by_batch_limit = True

    if not available_sections:
        payload["status"] = "unavailable"
        payload["error"] = "请求的恢复部分不可用"
    elif truncated_by_batch_limit:
        payload["status"] = "truncated_by_batch_limit"
    payload["returned_chars"] = returned_chars
    return payload


def recover_text_section(
    text: str,
    *,
    offset: int,
    limit: int,
    requested_limit: int,
) -> dict[str, Any]:
    start = min(max(0, offset), len(text))
    end = min(start + max(0, limit), len(text))
    chunk = text[start:end]
    has_more = end < len(text)
    return {
        "status": "ok",
        "original_length": len(text),
        "chunk": chunk,
        "offset": start,
        "requested_limit": requested_limit,
        "returned_chars": len(chunk),
        "next_offset": end if has_more else None,
        "has_more": has_more,
    }


def truncate_one_line(text: str, *, max_chars: int) -> str:
    one_line = " ".join(text.strip().split())
    if len(one_line) <= max_chars:
        return one_line
    return one_line[: max_chars - 1] + "…"
