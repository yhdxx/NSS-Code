from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from mycodingagent.code_intelligence.contracts import CodeIndexService, LSPService
from mycodingagent.tool_runtime.base import Tool, ToolResult


class CodeIndexQuery(BaseModel):
    operation: Literal["outline", "symbols", "definition_candidates", "callers", "callees", "impact"]
    analysis_intent: Literal["locate", "structure", "call_graph", "impact_analysis", "semantic_verification"] = "locate"
    path: str = ""
    query: str = ""
    language: str = ""
    depth: int = Field(default=1, ge=1, le=3)
    include_tests: bool = True
    limit: int = Field(default=50, ge=1, le=200)


class CodeIndexParams(CodeIndexQuery):
    operation: Literal["outline", "symbols", "definition_candidates", "callers", "callees", "impact", "batch"]
    queries: list[CodeIndexQuery] = Field(default_factory=list, max_length=20)


class LSPParams(BaseModel):
    operation: Literal["definition", "references", "hover", "diagnostics"]
    path: str
    line: int = Field(default=1, ge=1)
    column: int = Field(default=0, ge=0)


class CodeIndexTool(Tool):
    name = "code_index"
    description = (
        "Primary tool for code-symbol discovery and change-impact analysis. Prefer one impact or batch "
        "call before Grep when locating definitions, listing an outline, or finding callers/callees. Use Grep "
        "afterward only for imports, strings, configuration, documentation, or dynamic references "
        "that a syntax index may not capture."
    )
    params_model = CodeIndexParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, service: CodeIndexService) -> None:
        self._service = service

    async def execute(self, params: CodeIndexParams) -> ToolResult:
        payload = await asyncio.to_thread(
            self._service.query,
            params.operation,
            path=params.path,
            query=params.query,
            language=params.language,
            depth=params.depth,
            include_tests=params.include_tests,
            limit=params.limit,
            analysis_intent=params.analysis_intent,
            queries=[item.model_dump() for item in params.queries],
        )
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), is_error="error" in payload)


class LSPTool(Tool):
    name = "lsp"
    description = (
        "Verify exact semantic definitions, references, types, and diagnostics with a language server. "
        "Use after code_index has located the relevant file and position. If the language server is "
        "unavailable, continue with code_index, Grep, and ReadFile."
    )
    params_model = LSPParams
    category = "read"
    is_concurrency_safe = False

    def __init__(self, service: LSPService) -> None:
        self._service = service

    async def execute(self, params: LSPParams) -> ToolResult:
        payload = await self._service.query(
            params.operation,
            path=params.path,
            line=params.line,
            column=params.column,
        )
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), is_error="error" in payload)
