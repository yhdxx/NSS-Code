from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import BaseModel, Field

from mycodingagent.code_intelligence.project_graph import ProjectGraphService
from mycodingagent.tool_runtime.base import Tool, ToolResult


class UnavailableProjectGraphService:
    """Schema-only backend used when an embedding does not configure project graphs."""

    @staticmethod
    def work_mode_provider() -> str:
        return "general"


class ProjectGraphParams(BaseModel):
    module: str = Field(default="", description="模块名称、模块 ID 或相对目录；为空表示整个项目")


class ProjectDescriptionParams(BaseModel):
    target: str = Field(description="模块或最小单位 ID；名称仅在唯一时可用")
    description: str = Field(description="新的简短功能描述；为空会恢复为暂未描述")
    content_hash: str = Field(description="读取图谱时返回的目标 content_hash")


class _ProjectGraphTool(Tool):
    category = "read"
    is_concurrency_safe = True

    def __init__(self, service: ProjectGraphService) -> None:
        self._service = service

    def _mode_error(self) -> ToolResult:
        return ToolResult(
            json.dumps(
                {
                    "error_code": "code_mode_required",
                    "error": "当前 work_mode=general；请先输入精确命令 /mode 并选择 Code 模式。",
                },
                ensure_ascii=False,
            ),
            is_error=True,
        )

    def _allowed(self) -> bool:
        return self._service.work_mode_provider() == "code"


class ProjectArchitectureTool(_ProjectGraphTool):
    name = "ProjectArchitecture"
    description = "获取项目或指定模块的完整架构图，包含模块 ID、名称、路径、description、hash 和子模块。"
    params_model = ProjectGraphParams

    async def execute(self, params: ProjectGraphParams) -> ToolResult:
        if not self._allowed():
            return self._mode_error()
        payload = await asyncio.to_thread(self._service.architecture, params.module)
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), is_error="error_code" in payload)


class UnitDependencyGraphTool(_ProjectGraphTool):
    name = "UnitDependencyGraph"
    description = "获取模块架构、模块内最小单位及其 description、调用和依赖关系。"
    params_model = ProjectGraphParams

    async def execute(self, params: ProjectGraphParams) -> ToolResult:
        if not self._allowed():
            return self._mode_error()
        if not params.module.strip():
            return ToolResult(json.dumps({"error_code": "module_required", "error": "必须指定模块名称或 ID"}, ensure_ascii=False), is_error=True)
        payload = await asyncio.to_thread(self._service.dependency_graph, params.module)
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), is_error="error_code" in payload)


class UpdateProjectDescriptionTool(_ProjectGraphTool):
    name = "UpdateProjectDescription"
    description = "使用 content_hash 乐观锁更新模块或最小单位的功能 description。"
    params_model = ProjectDescriptionParams

    async def execute(self, params: ProjectDescriptionParams) -> ToolResult:
        if not self._allowed():
            return self._mode_error()
        payload = await asyncio.to_thread(
            self._service.update_description,
            params.target,
            params.description,
            params.content_hash,
        )
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), is_error="error_code" in payload)
