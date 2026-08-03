from __future__ import annotations

import json

from pydantic import BaseModel, Field

from mycodingagent.code_intelligence.project_graph_runtime import ProjectGraphRuntime
from mycodingagent.tool_runtime.base import Tool, ToolResult
from mycodingagent.work_mode import WorkMode


class ProjectGraphParams(BaseModel):
    module: str = Field(default="", description="模块名称、模块 ID 或相对目录；为空表示整个项目")
    depth: int = Field(default=3, ge=1, le=3, description="模块展开深度，runtime 最多允许 3 层")
    bootstrap: bool = Field(default=False, description="是否返回启动导航用三层 bootstrap 摘要")


class ProjectDescriptionItem(BaseModel):
    target: str = Field(description="模块或最小单位 ID；名称仅在唯一时可用")
    description: str = Field(description="新的简短功能描述；为空会恢复为暂未描述")
    content_hash: str = Field(description="读取图谱时返回的目标 content_hash")


class ProjectDescriptionParams(BaseModel):
    target: str = Field(default="", description="单个模块或最小单位 ID；批量更新时留空")
    description: str = Field(default="", description="单个目标的新简短功能描述")
    content_hash: str = Field(default="", description="单个目标读取图谱时返回的 content_hash")
    updates: list[ProjectDescriptionItem] = Field(
        default_factory=list,
        description="批量 description 更新；优先使用该字段一次提交多个已理解目标",
    )


class _ProjectGraphTool(Tool):
    category = "read"
    is_concurrency_safe = True

    def __init__(self, runtime: ProjectGraphRuntime) -> None:
        self._runtime = runtime

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
        return self._runtime.current_mode is WorkMode.CODE


class ProjectArchitectureTool(_ProjectGraphTool):
    name = "ProjectArchitecture"
    description = "获取项目或指定模块的模块架构图，最多展开三层，包含模块 ID、名称、路径、description、hash 和导航统计。"
    params_model = ProjectGraphParams

    async def execute(self, params: ProjectGraphParams) -> ToolResult:
        if not self._allowed():
            return self._mode_error()
        payload = await self._runtime.architecture(
            params.module,
            depth=params.depth,
            bootstrap=params.bootstrap,
        )
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
        payload = await self._runtime.dependency_graph(params.module)
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), is_error="error_code" in payload)


class UpdateProjectDescriptionTool(_ProjectGraphTool):
    name = "UpdateProjectDescription"
    description = "使用 content_hash 乐观锁更新模块或最小单位的功能 description；支持 updates 批量一次提交多个目标。"
    params_model = ProjectDescriptionParams

    async def execute(self, params: ProjectDescriptionParams) -> ToolResult:
        if not self._allowed():
            return self._mode_error()
        if params.updates:
            payload = await self._runtime.update_descriptions(
                [item.model_dump() for item in params.updates],
            )
        else:
            payload = await self._runtime.update_description(
                params.target,
                params.description,
                params.content_hash,
            )
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), is_error="error_code" in payload)
