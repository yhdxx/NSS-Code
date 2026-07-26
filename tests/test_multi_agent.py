from __future__ import annotations

import asyncio
import json

from multiAgent.context import build_role_context, run_summary_for_main_context
from multiAgent.models import AgentRole, MultiAgentRun, RunStatus
from multiAgent.store import MultiAgentStore
from multiAgent.tool_policy import schemas_for_role
from multiAgent.tools import (
    ApprovePlan,
    ApprovePlanParams,
    InspectSubAgentWork,
    InspectSubAgentWorkParams,
    SubmitPlan,
    SubmitPlanParams,
    SubmitSubAgentStep,
    SubmitSubAgentStepParams,
)
from multiAgent.validators import validate_plan_payload
from mycodingagent.tool_runtime import ToolRegistry
from mycodingagent.tool_runtime.base import Tool, ToolResult
from pydantic import BaseModel, Field


VALID_STEPS = [
    {
        "step_id": "1",
        "title": "Create models",
        "goal": "Add data models.",
        "acceptance": "Models serialize correctly.",
        "files": ["multiAgent/models.py"],
        "children": [
            {
                "step_id": "1.1",
                "title": "Plan node",
                "goal": "Represent recursive plan steps.",
                "acceptance": "PlanNode round-trips through dicts.",
                "files": ["multiAgent/models.py"],
                "children": [],
            }
        ],
    }
]


def test_submit_plan_validation_accepts_recursive_contiguous_steps():
    result = validate_plan_payload(title="Plan", summary="Do work", steps=VALID_STEPS)

    assert result.ok
    assert result.plan[0].children[0].step_id == "1.1"


def test_submit_plan_validation_rejects_non_contiguous_steps():
    bad_steps = [{**VALID_STEPS[0], "step_id": "2"}]

    result = validate_plan_payload(title="Plan", summary="Do work", steps=bad_steps)

    assert not result.ok
    assert any("step_id must be 1" in error for error in result.errors)


def test_submit_and_approve_plan_freezes_approved_plan(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="original user request")
    store.save_run(run)

    submit = SubmitPlan(store)
    approve = ApprovePlan(store)
    submit_result = asyncio.run(
        submit.execute(
            SubmitPlanParams(
                run_id=run.run_id,
                title="Plan",
                summary="Do work",
                steps=VALID_STEPS,
            )
        )
    )
    approve_result = asyncio.run(
        approve.execute(ApprovePlanParams(run_id=run.run_id, reason="complete and testable"))
    )

    assert json.loads(submit_result.output)["status"] == "ok"
    assert json.loads(approve_result.output)["next"] == "execute"
    approved = store.load_run(run.run_id)
    assert approved is not None
    assert approved.status == RunStatus.EXECUTING
    assert approved.approved_plan[0].step_id == "1"


def test_execute_context_omits_original_user_request(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="SECRET ORIGINAL REQUEST")
    store.save_run(run)
    asyncio.run(
        SubmitPlan(store).execute(
            SubmitPlanParams(run_id=run.run_id, title="Plan", summary="Do work", steps=VALID_STEPS)
        )
    )
    asyncio.run(ApprovePlan(store).execute(ApprovePlanParams(run_id=run.run_id, reason="ok")))
    approved = store.load_run(run.run_id)
    assert approved is not None
    approved.current_step_id = "1.1"

    context = build_role_context(role=AgentRole.EXECUTE, run=approved, main_messages=[])

    assert "SECRET ORIGINAL REQUEST" not in context
    assert "approved_plan" in context
    assert "current_step_id" in context


class DummyParams(BaseModel):
    value: str = Field(description="value")


class DummyWriteTool(Tool):
    name = "WriteFile"
    description = "write"
    params_model = DummyParams
    category = "write"

    async def execute(self, params: DummyParams) -> ToolResult:
        return ToolResult(output=params.value)


class DummyReadTool(Tool):
    name = "ReadFile"
    description = "read"
    params_model = DummyParams
    category = "read"

    async def execute(self, params: DummyParams) -> ToolResult:
        return ToolResult(output=params.value)


def test_read_only_agents_do_not_receive_write_tools(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    registry = ToolRegistry()
    registry.register(DummyReadTool())
    registry.register(DummyWriteTool())

    names = {schema["name"] for schema in schemas_for_role(role=AgentRole.PLAN_REVIEW, registry=registry, store=store)}

    assert "ReadFile" in names
    assert "WriteFile" not in names
    assert {"ApprovePlan", "RejectPlan"}.issubset(names)


def test_execute_schemas_require_step_id(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    registry = ToolRegistry()
    registry.register(DummyReadTool())

    read_schema = next(
        schema for schema in schemas_for_role(role=AgentRole.EXECUTE, registry=registry, store=store)
        if schema["name"] == "ReadFile"
    )

    assert "step_id" in read_schema["parameters"]["required"]
    assert "step_id" in read_schema["parameters"]["properties"]


def test_submit_step_rejects_wrong_current_step(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="task")
    run.current_step_id = "1.1"
    store.save_run(run)

    result = asyncio.run(
        SubmitSubAgentStep(store).execute(
            SubmitSubAgentStepParams(
                run_id=run.run_id,
                step_id="1.2",
                summary="done",
                changed_files=[],
                evidence="evidence",
            )
        )
    )

    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert payload["error"] == "wrong_step"


def test_inspect_subagent_work_returns_minimal_paginated_payload(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="task")
    run.subagent_final_answers[AgentRole.EXECUTE.value] = "abcdef"
    store.save_run(run)

    result = asyncio.run(
        InspectSubAgentWork(store).execute(
            InspectSubAgentWorkParams(run_id=run.run_id, agent="execute", offset=0, limit=5)
        )
    )

    payload = json.loads(result.output)
    assert set(payload) == {"run_id", "agent", "step_id", "content", "next_offset", "has_more"}
    assert payload["content"]
    assert payload["has_more"] is True


def test_main_result_summary_does_not_include_full_approved_plan(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="task")
    store.save_run(run)
    asyncio.run(
        SubmitPlan(store).execute(
            SubmitPlanParams(run_id=run.run_id, title="Plan", summary="Compact summary", steps=VALID_STEPS)
        )
    )
    asyncio.run(ApprovePlan(store).execute(ApprovePlanParams(run_id=run.run_id, reason="ok")))
    approved = store.load_run(run.run_id)
    assert approved is not None

    summary = json.loads(run_summary_for_main_context(approved))

    assert summary["plan_summary"] == "Compact summary"
    assert "approved_plan" not in summary
