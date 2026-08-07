from __future__ import annotations

import json
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from mycodingagent.long_term_memory.models import MemoryScope, MemoryType
from mycodingagent.long_term_memory.store import SQLiteLongTermMemoryStore
from mycodingagent.tool_runtime.base import Tool, ToolResult
from mycodingagent.tool_contracts import apply_tool_intent_schema


MemoryTypeLiteral = Literal["user_profile", "user_preference", "project_fact", "decision"]
WorkflowMemoryTypeLiteral = Literal["workflow_candidate", "skill_candidate"]
MemoryScopeLiteral = Literal["user", "workspace", "project"]


class BucketMemoryItemPayload(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkflowMemoryPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    when_to_use: str = Field(min_length=1, max_length=1000)
    when_not_use: List[str] = Field(default_factory=list, max_length=3)
    content: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UpdateMemoryItemPayload(BaseModel):
    memory_uid: str = Field(min_length=1)
    memory_type: MemoryTypeLiteral
    scope: MemoryScopeLiteral
    content: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UpdateWorkflowMemoryItemPayload(BaseModel):
    memory_uid: str = Field(min_length=1)
    memory_type: WorkflowMemoryTypeLiteral
    scope: MemoryScopeLiteral
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    when_to_use: str = Field(min_length=1, max_length=1000)
    when_not_use: List[str] = Field(default_factory=list, max_length=3)
    content: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetireMemoryItemPayload(BaseModel):
    memory_uid: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000)
    evidence: List[str] = Field(default_factory=list)


class SubmitLongTermMemoryPatchParams(BaseModel):
    extraction_id: str = Field(min_length=1)
    user_profiles: List[BucketMemoryItemPayload] = Field(default_factory=list)
    user_preferences: List[BucketMemoryItemPayload] = Field(default_factory=list)
    project_facts: List[BucketMemoryItemPayload] = Field(default_factory=list)
    workflows: List[WorkflowMemoryPayload] = Field(default_factory=list)
    skill_candidates: List[WorkflowMemoryPayload] = Field(default_factory=list)
    update_items: List[UpdateMemoryItemPayload] = Field(default_factory=list)
    update_workflows: List[UpdateWorkflowMemoryItemPayload] = Field(default_factory=list)
    update_skill_candidates: List[UpdateWorkflowMemoryItemPayload] = Field(default_factory=list)
    retire_items: List[RetireMemoryItemPayload] = Field(default_factory=list)


class SubmitLongTermMemoryPatch(Tool):
    name = "SubmitLongTermMemoryPatch"
    description = (
        "提交完整的结构化长期记忆补丁。使用本工具，不要在普通文本中输出 JSON。"
    )
    params_model = SubmitLongTermMemoryPatchParams
    category = "read"

    def __init__(self, *, extraction_id: str, collector: dict[str, Any]) -> None:
        self._extraction_id = extraction_id
        self._collector = collector

    def get_schema(self) -> dict[str, Any]:
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        apply_tool_intent_schema(schema)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }

    async def execute(self, params: SubmitLongTermMemoryPatchParams) -> ToolResult:
        if params.extraction_id != self._extraction_id:
            return _json_error("wrong_extraction_id", "extraction_id 与当前提取任务不匹配。")
        payload = params.model_dump()
        self._collector["payload"] = payload
        return _json({"status": "ok", "accepted": True})


class SearchWorkspaceProjectFactsParams(BaseModel):
    query: str = Field(description="用户请求中的项目名称、工作区标签、路径片段或关键词")
    limit: int = Field(default=5, ge=1, le=20)


class SearchWorkspaceProjectFacts(Tool):
    name = "SearchWorkspaceProjectFacts"
    description = (
        "仅当用户明确询问另一个项目或历史工作区时，搜索其他工作区的抽象项目事实。"
        "只返回 project_fact 记忆。"
    )
    params_model = SearchWorkspaceProjectFactsParams
    category = "read"

    def __init__(self, *, store: SQLiteLongTermMemoryStore, user_id: str, current_workspace_fingerprint: str) -> None:
        self._store = store
        self._user_id = user_id
        self._current_workspace_fingerprint = current_workspace_fingerprint

    async def execute(self, params: SearchWorkspaceProjectFactsParams) -> ToolResult:
        matches = self._store.search_project_facts(
            user_id=self._user_id,
            query=params.query,
            exclude_workspace_fingerprint=self._current_workspace_fingerprint,
            limit=params.limit,
        )
        return _json({"matches": matches})


class MemorySelectionPayload(BaseModel):
    memory_uid: str = Field(min_length=1)
    reason: str = Field(default="", max_length=1000)


class SubmitLongTermMemoryQueryResultParams(BaseModel):
    query_id: str = Field(min_length=1)
    memories: List[MemorySelectionPayload] = Field(default_factory=list)
    workflow_candidates: List[MemorySelectionPayload] = Field(default_factory=list)
    skill_candidates: List[MemorySelectionPayload] = Field(default_factory=list)


class SubmitLongTermMemoryQueryResult(Tool):
    name = "SubmitLongTermMemoryQueryResult"
    description = (
        "提交为当前查询选中的长期记忆项。用户、Profile、项目和决策项放入 memories，"
        "工作流候选放入 workflow_candidates，Skill 候选放入 skill_candidates。"
    )
    params_model = SubmitLongTermMemoryQueryResultParams
    category = "read"

    def __init__(self, *, query_id: str, collector: dict[str, Any]) -> None:
        self._query_id = query_id
        self._collector = collector

    def get_schema(self) -> dict[str, Any]:
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        apply_tool_intent_schema(schema)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }

    async def execute(self, params: SubmitLongTermMemoryQueryResultParams) -> ToolResult:
        if params.query_id != self._query_id:
            return _json_error("wrong_query_id", "query_id 与当前查询不匹配。")
        payload = params.model_dump()
        self._collector["payload"] = payload
        return _json({"status": "ok", "accepted": True})


def validate_memory_type(value: str) -> MemoryType:
    return MemoryType(value)


def validate_memory_scope(value: str) -> MemoryScope:
    return MemoryScope(value)


def _json(payload: dict[str, Any]) -> ToolResult:
    return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2))


def _json_error(code: str, message: str) -> ToolResult:
    return ToolResult(
        output=json.dumps({"status": "error", "error": code, "message": message}, ensure_ascii=False, indent=2),
        is_error=True,
    )
