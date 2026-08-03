from __future__ import annotations

import json

from pydantic import BaseModel, Field

from mycodingagent.plan_runtime.manager import PlanRuntime
from mycodingagent.plan_runtime.models import PlanStepStatus
from mycodingagent.tool_runtime.base import Tool, ToolResult


class PlanStepInput(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class CreatePlanParams(BaseModel):
    objective: str = Field(min_length=1, max_length=1000)
    steps: list[PlanStepInput] = Field(min_length=1, max_length=50)


class CreatePlan(Tool):
    name = "create_plan"
    description = "提交一个等待用户审批的实施计划。该工具只创建提案，不执行计划。"
    params_model = CreatePlanParams
    category = "command"

    def __init__(self, runtime: PlanRuntime) -> None:
        self._runtime = runtime

    async def execute(self, params: CreatePlanParams) -> ToolResult:
        plan = self._runtime.create_proposal(
            params.objective,
            [step.text for step in params.steps],
        )
        return ToolResult(
            json.dumps(
                {
                    "status": "awaiting_user_decision",
                    "plan_id": plan.id,
                    "objective": plan.objective,
                    "steps": [{"id": step.id, "text": step.text} for step in plan.steps],
                },
                ensure_ascii=False,
            )
        )


class UpdatePlanStepParams(BaseModel):
    plan_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    status: PlanStepStatus
    note: str = Field(default="", max_length=1000)


class UpdatePlanStep(Tool):
    name = "update_plan_step"
    description = "提交一个已批准计划步骤的执行进度；不能修改计划目标、步骤文本或顺序。"
    params_model = UpdatePlanStepParams
    category = "command"

    def __init__(self, runtime: PlanRuntime) -> None:
        self._runtime = runtime

    async def execute(self, params: UpdatePlanStepParams) -> ToolResult:
        if params.status is PlanStepStatus.PENDING:
            return ToolResult("update_plan_step 不接受 pending 状态", is_error=True)
        plan = self._runtime.update_step(
            plan_id=params.plan_id,
            step_id=params.step_id,
            status=params.status,
            note=params.note,
        )
        return ToolResult(
            json.dumps(
                {
                    "plan_id": plan.id,
                    "plan_status": plan.status.value,
                    "objective": plan.objective,
                    "steps": [
                        {
                            "id": step.id,
                            "text": step.text,
                            "status": step.status.value,
                            "note": step.note,
                        }
                        for step in plan.steps
                    ],
                },
                ensure_ascii=False,
            )
        )
