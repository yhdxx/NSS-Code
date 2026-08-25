from __future__ import annotations

import json

from pydantic import BaseModel, Field

from mycodingagent.code_intelligence.task_graph import PathTaskGraphRuntime
from mycodingagent.tool_runtime.base import Tool, ToolResult


class CreateTaskGraphParams(BaseModel):
    paths: list[str] = Field(description="当前任务涉及的工作区文件或目录路径")
    plan_id: str = Field(default="", description="可选 Plan ID，仅作引用")
    plan_step_id: str = Field(default="", description="可选 Plan 步骤 ID，仅作引用")


class TaskGraphNodeUpdate(BaseModel):
    node_id: str = Field(default="", description="任务图节点 ID；也可使用 path 定位")
    path: str = Field(default="", description="任务图中的相对路径；也可使用 node_id 定位")
    work_status: str | None = Field(default=None, description="工作状态：pending 或 modified")
    test_status: str | None = Field(default=None, description="测试状态：untested、failed 或 passed")


class UpdateTaskGraphParams(BaseModel):
    task_graph_id: str = Field(description="CreateTaskGraph 返回的任务图 ID")
    updates: list[TaskGraphNodeUpdate] = Field(default_factory=list, description="要更新的节点状态")
    task_status: str = Field(default="", description="可选任务状态：active、completed、interrupted、superseded")
    note: str = Field(default="", description="可选任务备注")


class _TaskGraphTool(Tool):
    category = "state"
    is_concurrency_safe = False

    def __init__(self, runtime: PathTaskGraphRuntime) -> None:
        self._runtime = runtime


class CreateTaskGraphTool(_TaskGraphTool):
    name = "CreateTaskGraph"
    description = (
        "创建当前任务涉及的纯路径范围图。节点只记录目录/文件层次，以及 Agent 提交的 "
        "pending/modified 工作状态和 untested/failed/passed 测试状态；不解析或验证源码。"
    )
    params_model = CreateTaskGraphParams

    async def execute(self, params: CreateTaskGraphParams) -> ToolResult:
        payload = await self._runtime.create(
            params.paths,
            plan_id=params.plan_id,
            plan_step_id=params.plan_step_id,
        )
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), is_error="error_code" in payload)


class UpdateTaskGraphTool(_TaskGraphTool):
    name = "UpdateTaskGraph"
    description = (
        "更新任务图节点状态。工作状态只表示 pending/modified，测试状态只表示 "
        "untested/failed/passed；runtime 不据此判断代码正确性。"
    )
    params_model = UpdateTaskGraphParams

    async def execute(self, params: UpdateTaskGraphParams) -> ToolResult:
        payload = await self._runtime.update(
            params.task_graph_id,
            [item.model_dump(exclude_none=True) for item in params.updates],
            task_status=params.task_status,
            note=params.note,
        )
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), is_error="error_code" in payload)
