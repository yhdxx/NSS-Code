from __future__ import annotations

import json

from pydantic import BaseModel, Field

from mycodingagent.search_runtime import SearchRuntime, SearchRuntimeError
from mycodingagent.tool_runtime.base import Tool, ToolResult


class SearchWebParams(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="需要搜索的关键词或问题")
    categories: list[str] = Field(default_factory=lambda: ["general"], max_length=8)
    language: str = Field(default="", max_length=32)
    time_range: str = Field(default="", max_length=16, description="day、month、year 或留空")
    max_results: int = Field(default=8, ge=1, le=20)


class FetchUrlParams(BaseModel):
    url: str = Field(min_length=1, max_length=4096, description="要读取的公网 HTTP/HTTPS URL")
    max_chars: int = Field(default=12000, ge=100, le=50000)


class SearchWeb(Tool):
    name = "SearchWeb"
    description = "通过 Runtime 托管的 SearXNG 为研究子智能体查找文本网页来源。"
    params_model = SearchWebParams
    category = "read"

    def __init__(self, runtime: SearchRuntime) -> None:
        self._runtime = runtime

    async def execute(self, params: SearchWebParams) -> ToolResult:
        try:
            payload = await self._runtime.search(
                params.query,
                categories=params.categories,
                language=params.language,
                time_range=params.time_range,
                max_results=params.max_results,
            )
        except SearchRuntimeError as exc:
            return ToolResult(json.dumps(exc.to_payload(), ensure_ascii=False), is_error=True)
        return ToolResult(json.dumps(payload, ensure_ascii=False))


class FetchUrl(Tool):
    name = "FetchUrl"
    description = "读取公网网页的静态文本、HTML 或 JSON；动态网页和交互操作使用 browser_* 工具。"
    params_model = FetchUrlParams
    category = "read"

    def __init__(self, runtime: SearchRuntime) -> None:
        self._runtime = runtime

    async def execute(self, params: FetchUrlParams) -> ToolResult:
        try:
            payload = await self._runtime.fetch_url(params.url, max_chars=params.max_chars)
        except SearchRuntimeError as exc:
            return ToolResult(json.dumps(exc.to_payload(), ensure_ascii=False), is_error=True)
        return ToolResult(json.dumps(payload, ensure_ascii=False))
