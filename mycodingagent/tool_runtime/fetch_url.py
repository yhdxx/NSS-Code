from __future__ import annotations

import json

from pydantic import BaseModel, Field

from mycodingagent.tool_runtime.base import Tool, ToolResult
from mycodingagent.web_fetch_runtime import WebFetchRuntime, WebFetchRuntimeError


class FetchUrlParams(BaseModel):
    url: str = Field(min_length=1, max_length=4096, description="要读取的 HTTP/HTTPS URL")
    max_chars: int = Field(default=12000, ge=100, le=50000)


class FetchUrl(Tool):
    name = "FetchUrl"
    description = "读取网页的静态文本、HTML 或 JSON；动态网页和交互操作使用 browser_* 工具。"
    params_model = FetchUrlParams
    category = "read"

    def __init__(self, runtime: WebFetchRuntime) -> None:
        self._runtime = runtime

    async def execute(self, params: FetchUrlParams) -> ToolResult:
        try:
            payload = await self._runtime.fetch_url(params.url, max_chars=params.max_chars)
        except WebFetchRuntimeError as exc:
            return ToolResult(json.dumps(exc.to_payload(), ensure_ascii=False), is_error=True)
        return ToolResult(json.dumps(payload, ensure_ascii=False))
