from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from mycodingagent.code_intelligence.contracts import CodeIndexService, LSPService
from mycodingagent.tool_runtime.base import Tool, ToolResult


class CodeIndexParams(BaseModel):
    operation: Literal["outline", "symbols", "definition_candidates", "callers", "callees"]
    path: str = ""
    query: str = ""
    limit: int = Field(default=50, ge=1, le=200)


class LSPParams(BaseModel):
    operation: Literal["definition", "references", "hover", "diagnostics"]
    path: str
    line: int = Field(default=1, ge=1)
    column: int = Field(default=0, ge=0)


class CodeIndexTool(Tool):
    name = "code_index"
    description = "Query the workspace symbol index for outlines, definitions, callers, and callees."
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
            limit=params.limit,
        )
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), is_error="error" in payload)


class LSPTool(Tool):
    name = "lsp"
    description = "Query a language server for definitions, references, hover information, or diagnostics."
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
