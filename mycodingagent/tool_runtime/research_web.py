from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel, Field

from mycodingagent.research_runtime import ResearchRuntime, ResearchRuntimeError
from mycodingagent.tool_runtime.base import Tool, ToolResult


class ResearchWebParams(BaseModel):
    instruction: str = Field(
        min_length=1,
        max_length=2000,
        description="要交给隔离研究子智能体完成的具体文本研究任务",
    )
    preferred_sources: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="可选的优先网站域名或来源名称",
    )
    max_sources: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="可选的最大来源数量",
    )


class ResearchWeb(Tool):
    name = "ResearchWeb"
    description = (
        "由隔离、无状态的研究子智能体搜索和读取网页，并只返回带来源 URL 的文本总结。"
        "该工具只能返回文本，不能检索、查看、分析或返回图片。"
        "如需寻找图片，可让它定位包含目标图片的网站并返回网页 URL，"
        "然后使用 browser_* 工具访问该网站并下载图片。"
    )
    params_model = ResearchWebParams
    category = "read"

    def __init__(self, runtime: ResearchRuntime) -> None:
        self._runtime = runtime
        self._cancel_event: asyncio.Event | None = None

    def bind_cancel_event(self, cancel_event: asyncio.Event | None) -> None:
        self._cancel_event = cancel_event

    async def execute(self, params: ResearchWebParams) -> ToolResult:
        try:
            result = await self._runtime.research(
                params.instruction,
                preferred_sources=params.preferred_sources,
                max_sources=params.max_sources,
                cancel_event=self._cancel_event,
            )
        except ResearchRuntimeError as exc:
            return ToolResult(json.dumps(exc.to_payload(), ensure_ascii=False), is_error=True)
        payload = dict(result.payload)
        payload["rounds_used"] = result.rounds_used
        return ToolResult(json.dumps(payload, ensure_ascii=False))
