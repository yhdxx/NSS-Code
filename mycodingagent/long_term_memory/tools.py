from __future__ import annotations

import json
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from mycodingagent.long_term_memory.models import MemoryScope, MemoryType
from mycodingagent.long_term_memory.store import SQLiteLongTermMemoryStore
from mycodingagent.tool_runtime.base import Tool, ToolResult


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
        "Submit the complete structured long-term memory patch. "
        "Use this tool instead of writing JSON in normal text."
    )
    params_model = SubmitLongTermMemoryPatchParams
    category = "read"

    def __init__(self, *, extraction_id: str, collector: dict[str, Any]) -> None:
        self._extraction_id = extraction_id
        self._collector = collector

    def get_schema(self) -> dict[str, Any]:
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }

    async def execute(self, params: SubmitLongTermMemoryPatchParams) -> ToolResult:
        if params.extraction_id != self._extraction_id:
            return _json_error("wrong_extraction_id", "extraction_id does not match the current extraction.")
        payload = params.model_dump()
        self._collector["payload"] = payload
        return _json({"status": "ok", "accepted": True})


class SearchWorkspaceProjectFactsParams(BaseModel):
    query: str = Field(description="Project name, workspace label, path fragment, or keyword from the user query.")
    limit: int = Field(default=5, ge=1, le=20)


class SearchWorkspaceProjectFacts(Tool):
    name = "SearchWorkspaceProjectFacts"
    description = (
        "Search abstract project facts from other workspaces only when the user explicitly asks about "
        "another project or historical workspace. Returns project_fact memories only."
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
        "Submit the selected long-term memory items for the current query. "
        "Use memories for user/profile/project/decision items, workflow_candidates for workflow candidates, "
        "and skill_candidates for skill candidates."
    )
    params_model = SubmitLongTermMemoryQueryResultParams
    category = "read"

    def __init__(self, *, query_id: str, collector: dict[str, Any]) -> None:
        self._query_id = query_id
        self._collector = collector

    def get_schema(self) -> dict[str, Any]:
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }

    async def execute(self, params: SubmitLongTermMemoryQueryResultParams) -> ToolResult:
        if params.query_id != self._query_id:
            return _json_error("wrong_query_id", "query_id does not match the current query.")
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
