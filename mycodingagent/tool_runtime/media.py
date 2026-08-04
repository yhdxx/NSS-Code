from __future__ import annotations

import json

from pydantic import BaseModel, Field

from mycodingagent.media_runtime import MediaModelRuntime, MediaRuntimeError
from mycodingagent.tool_runtime.base import Tool, ToolResult


class TranscribeAudioParams(BaseModel):
    source: str = Field(
        min_length=1,
        max_length=4096,
        description="工作区内的音频文件路径，或无需认证的公网 HTTP/HTTPS URL",
    )


class AnalyzeImageParams(BaseModel):
    sources: list[str] = Field(
        min_length=1,
        max_length=8,
        description="1 到 8 个工作区图片路径或无需认证的公网 HTTP/HTTPS URL；顺序即图片编号",
    )
    query: str = Field(
        min_length=1,
        max_length=4000,
        description="需要模型针对单图回答的问题，或针对多图完成的比较任务",
    )


class TranscribeAudio(Tool):
    name = "TranscribeAudio"
    description = (
        "提取音频中的语音文本。只执行语音转文字，不做摘要、翻译或音频编辑；"
        "source 可为工作区文件或公网 HTTP/HTTPS URL。"
    )
    params_model = TranscribeAudioParams
    category = "read"

    def __init__(self, runtime: MediaModelRuntime) -> None:
        self._runtime = runtime

    async def execute(self, params: TranscribeAudioParams) -> ToolResult:
        try:
            payload = await self._runtime.transcribe_audio(params.source)
        except MediaRuntimeError as exc:
            return ToolResult(str(exc), is_error=True)
        return ToolResult(json.dumps(payload, ensure_ascii=False))


class AnalyzeImage(Tool):
    name = "AnalyzeImage"
    description = (
        "根据明确 query 分析一张图片或比较多张图片并返回文本结论。sources 的顺序对应图片 1、图片 2 等编号；"
        "不要用它读取纯文本文件。"
    )
    params_model = AnalyzeImageParams
    category = "read"

    def __init__(self, runtime: MediaModelRuntime) -> None:
        self._runtime = runtime

    async def execute(self, params: AnalyzeImageParams) -> ToolResult:
        try:
            payload = await self._runtime.analyze_images(params.sources, params.query)
        except MediaRuntimeError as exc:
            return ToolResult(str(exc), is_error=True)
        return ToolResult(json.dumps(payload, ensure_ascii=False))
