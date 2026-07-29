from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI

from mycodingagent.configuration import CONFIG
from mycodingagent.llm_runtime.client import PendingToolCall, format_openai_tools, stream_one_round
from mycodingagent.long_term_memory.models import LongTermMemoryContext, LongTermMemoryItem, MemoryScope, MemoryType
from mycodingagent.long_term_memory.tools import SearchWorkspaceProjectFacts, SubmitLongTermMemoryQueryResult


PROMPT_PATH = Path(__file__).resolve().parents[2] / "multiAgent" / "prompts" / "long_term_memory_query" / "SYSTEM.md"


class LongTermMemoryQueryModel:
    def __init__(self, *, api_client: AsyncOpenAI, model: str) -> None:
        self.api_client = api_client
        self.model = model

    async def select(
        self,
        *,
        current_query: str,
        recent_messages: list[dict[str, str]],
        version_id: str,
        items: list[LongTermMemoryItem],
        workspace: dict[str, str],
        project_fact_search: dict[str, Any] | None = None,
    ) -> LongTermMemoryContext | None:
        query_id = uuid4().hex
        collector: dict[str, Any] = {}
        submit_tool = SubmitLongTermMemoryQueryResult(query_id=query_id, collector=collector)
        search_tool = None
        if project_fact_search is not None:
            search_tool = SearchWorkspaceProjectFacts(
                store=project_fact_search["store"],
                user_id=str(project_fact_search["user_id"]),
                current_workspace_fingerprint=str(project_fact_search["current_workspace_fingerprint"]),
            )
        payload = {
            "query_id": query_id,
            "current_user_query": current_query,
            "recent_conversation": recent_messages,
            "workspace": workspace,
            "available_memories": [_item_for_query(item) for item in items],
            "limits": {
                "memories": CONFIG.long_term_memory.max_memories,
                "workflow_candidates": CONFIG.long_term_memory.max_workflow_candidates,
                "skill_candidates": CONFIG.long_term_memory.max_skill_candidates,
            },
        }
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _read_prompt(PROMPT_PATH)},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2, default=str)},
        ]
        tool_objects = [submit_tool, *([search_tool] if search_tool is not None else [])]
        tools = format_openai_tools([_openai_schema(tool) for tool in tool_objects])
        available_items = list(items)
        for _ in range(3):
            assistant_text, tool_calls, _usage = await stream_one_round(
                self.api_client,
                self.model,
                messages,
                tools,
                display=False,
                output_label="long_term_memory_query",
            )
            messages.append(_assistant_message(assistant_text, tool_calls))
            if not tool_calls:
                continue
            for index, call in enumerate(tool_calls):
                call_id = call.tool_id or f"ltm_query_call_{index}"
                if call.tool_name == submit_tool.name:
                    output = await _execute_submit_tool(submit_tool, call)
                elif search_tool is not None and call.tool_name == search_tool.name:
                    output = await _execute_search_tool(search_tool, call)
                    available_items.extend(_items_from_project_fact_search_output(output))
                else:
                    output = f"Error: query model may only call allowed long-term memory query tools."
                messages.append({"role": "tool", "tool_call_id": call_id, "content": output})
            if collector.get("payload") is not None:
                return _context_from_selection(
                    version_id=version_id,
                    query_id=query_id,
                    items=available_items,
                    payload=dict(collector["payload"]),
                )
        return None


def _context_from_selection(
    *,
    version_id: str,
    query_id: str,
    items: list[LongTermMemoryItem],
    payload: dict[str, Any],
) -> LongTermMemoryContext:
    by_uid = {item.memory_uid: item for item in items}
    memories = _selected_items(payload.get("memories", []), by_uid, disallow_candidate=True)
    workflows = _selected_items(
        payload.get("workflow_candidates", []),
        by_uid,
        required_type=MemoryType.WORKFLOW_CANDIDATE,
    )
    skills = _selected_items(
        payload.get("skill_candidates", []),
        by_uid,
        required_type=MemoryType.SKILL_CANDIDATE,
    )
    max_memories = CONFIG.long_term_memory.max_memories
    max_workflows = CONFIG.long_term_memory.max_workflow_candidates
    max_skills = CONFIG.long_term_memory.max_skill_candidates
    if len(memories) > max_memories or len(workflows) > max_workflows or len(skills) > max_skills:
        raise ValueError("long-term memory query result exceeded configured limits")
    return LongTermMemoryContext(
        version_id=version_id,
        query_id=query_id,
        memories=memories,
        workflow_candidates=workflows,
        skill_candidates=skills,
    )


def _selected_items(
    raw_items: Any,
    by_uid: dict[str, LongTermMemoryItem],
    *,
    required_type: MemoryType | None = None,
    disallow_candidate: bool = False,
) -> list[LongTermMemoryItem]:
    if not isinstance(raw_items, list):
        raise ValueError("selection fields must be arrays")
    selected: list[LongTermMemoryItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ValueError("selection item must be an object")
        memory_uid = str(raw.get("memory_uid", ""))
        item = by_uid.get(memory_uid)
        if item is None:
            raise ValueError(f"unknown memory_uid: {memory_uid}")
        if required_type is not None and item.memory_type != required_type:
            raise ValueError(f"memory_uid {memory_uid} has wrong type: {item.memory_type.value}")
        if disallow_candidate and item.memory_type in {MemoryType.WORKFLOW_CANDIDATE, MemoryType.SKILL_CANDIDATE}:
            raise ValueError(f"candidate memory_uid cannot be returned in memories: {memory_uid}")
        selected.append(item)
    return selected


def _item_for_query(item: LongTermMemoryItem) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "memory_uid": item.memory_uid,
        "type": item.memory_type.value,
        "scope": item.scope.value,
        "confidence": item.confidence,
        "metadata": {
            key: value
            for key, value in item.metadata.items()
            if key
            in {
                "namespace",
                "origin_workspace_fingerprint",
                "origin_workspace_label",
                "queried_workspaces",
                "used_workspaces",
                "unused_queried_workspaces",
                "exposure_count",
                "success_count",
                "lifecycle_status",
            }
        },
    }
    if item.memory_type in {MemoryType.WORKFLOW_CANDIDATE, MemoryType.SKILL_CANDIDATE}:
        workflow = item.metadata.get("workflow")
        if not isinstance(workflow, dict):
            raise ValueError(f"workflow memory missing structured metadata: {item.memory_uid}")
        when_not_use = [
            str(value).strip()
            for value in list(workflow.get("when_not_use", []) or [])
            if str(value).strip()
        ]
        if len(when_not_use) > 3:
            raise ValueError(f"workflow memory has too many when_not_use entries: {item.memory_uid}")
        payload.update(
            {
                "name": str(workflow.get("name", "")).strip(),
                "description": str(workflow.get("description", "")).strip(),
                "when_to_use": str(workflow.get("when_to_use", "")).strip(),
                "when_not_use": when_not_use,
                "content": item.content,
            }
        )
        if not payload["name"] or not payload["description"] or not payload["when_to_use"] or not item.content.strip():
            raise ValueError(f"workflow memory has invalid structured metadata: {item.memory_uid}")
    else:
        payload["content"] = item.content
    return payload


async def _execute_submit_tool(tool: SubmitLongTermMemoryQueryResult, call: PendingToolCall) -> str:
    try:
        params = tool.params_model.model_validate_json(call.arguments or "{}")
        result = await tool.execute(params)
    except Exception as exc:
        return f"Tool execution error: {exc}"
    return result.output


async def _execute_search_tool(tool: SearchWorkspaceProjectFacts, call: PendingToolCall) -> str:
    try:
        params = tool.params_model.model_validate_json(call.arguments or "{}")
        result = await tool.execute(params)
    except Exception as exc:
        return f"Tool execution error: {exc}"
    return result.output


def _items_from_project_fact_search_output(output: str) -> list[LongTermMemoryItem]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return []
    items: list[LongTermMemoryItem] = []
    for match in payload.get("matches", []):
        if not isinstance(match, dict):
            continue
        workspace_label = str(match.get("workspace_label", ""))
        workspace_fingerprint = str(match.get("workspace_fingerprint", ""))
        for fact in match.get("facts", []):
            if not isinstance(fact, dict):
                continue
            items.append(
                LongTermMemoryItem(
                    memory_uid=str(fact.get("memory_uid", "")),
                    version_id="project_fact_search",
                    memory_type=MemoryType.PROJECT_FACT,
                    scope=MemoryScope.PROJECT,
                    content=str(fact.get("content", "")),
                    confidence=float(fact.get("confidence", 0.0) or 0.0),
                    evidence=[],
                    metadata={
                        "namespace": workspace_fingerprint,
                        "workspace_label": workspace_label,
                        "workspace_fingerprint": workspace_fingerprint,
                        "source": "SearchWorkspaceProjectFacts",
                    },
                )
            )
    return items


def _assistant_message(assistant_text: str, tool_calls: list[PendingToolCall]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant"}
    if assistant_text or not tool_calls:
        message["content"] = assistant_text
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": call.tool_id or f"tool_call_{index}",
                "type": "function",
                "function": {"name": call.tool_name, "arguments": call.arguments},
            }
            for index, call in enumerate(tool_calls)
        ]
    return message


def _read_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return (
            "Select only directly relevant long-term memories for the current query. "
            "Call SubmitLongTermMemoryQueryResult with the selected items."
        )


def _openai_schema(tool: SubmitLongTermMemoryQueryResult) -> dict[str, Any]:
    schema = tool.get_schema()
    return {
        "name": schema["name"],
        "description": schema["description"],
        "parameters": schema["input_schema"],
    }
