from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from mycodingagent.code_intelligence.contracts import CodeIndexService, LSPService
from mycodingagent.tool_runtime.base import Tool, ToolResult


class CodeIndexQuery(BaseModel):
    operation: Literal["overview", "outline", "symbols", "definition_candidates", "callers", "callees", "impact"] = Field(
        description="目录结构用 overview，单文件结构用 outline；符号、调用图和影响分析使用其余对应操作"
    )
    analysis_intent: Literal["locate", "structure", "call_graph", "impact_analysis", "semantic_verification"] = Field(
        default="locate", description="本次结构查询的分析目的"
    )
    path: str = Field(
        default="", description="仅使用相对路径或 /workspace；overview 接受目录，outline 接受源码文件"
    )
    query: str = Field(
        default="", description="除 overview 和 outline 外均为必填的非空符号名"
    )
    language: str = Field(default="", description="可选语言过滤条件")
    depth: int = Field(default=1, ge=1, le=3)
    include_tests: bool = True
    limit: int = Field(default=50, ge=1, le=200)


class CodeIndexParams(CodeIndexQuery):
    operation: Literal["overview", "outline", "symbols", "definition_candidates", "callers", "callees", "impact", "batch"] = Field(
        description="目录结构用 overview，单文件结构用 outline；多个结构查询用 batch"
    )
    queries: list[CodeIndexQuery] = Field(
        default_factory=list, max_length=20, description="仅在 batch 时填写，最多 20 个非 batch 子查询"
    )


class LSPParams(BaseModel):
    operation: Literal["definition", "references", "hover", "diagnostics"] = Field(
        description="只在需要精确定义、引用、类型或诊断时调用"
    )
    path: str = Field(description="code_index 已定位的相对路径或 /workspace 源码文件路径")
    line: int = Field(default=1, ge=1)
    column: int = Field(default=0, ge=0)


class CodeIndexTool(Tool):
    name = "code_index"
    description = (
        "用于工作区概览、代码符号发现和修改影响分析的主要工具。项目或目录结构使用 overview，单个文件结构"
        "使用 outline，符号影响使用 impact 或 batch。索引错误包含 suggested_call 时应先按建议重试；之后仅用 "
        "Grep 补充语法索引无法覆盖的 import、字符串、配置、文档或动态引用。"
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
