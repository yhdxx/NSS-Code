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
        "用于代码符号发现和修改影响分析的主要工具。定位定义、查看文件结构或查找调用方/被调用方时，"
        "应在 Grep 前优先调用一次 impact 或 batch。之后仅使用 Grep 补充查找语法索引可能无法覆盖的 "
        "import、字符串、配置、文档或动态引用。"
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
        "使用语言服务器复核精确语义定义、引用、类型和诊断。应在 code_index 定位相关文件和位置后使用。"
        "语言服务器不可用时，继续使用 code_index、Grep 和 ReadFile。"
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
