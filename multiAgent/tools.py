from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from mycodingagent.tool_runtime.base import Tool, ToolResult

from multiAgent.models import AgentRole, RunStatus, StepStatus, executable_steps
from multiAgent.store import MultiAgentStore
from multiAgent.validators import validate_failed_steps, validate_plan_payload, validate_step_exists


class SubmitPlanParams(BaseModel):
    run_id: str = Field(description="Current multi-agent run_id.")
    title: str = Field(description="Short plan title.")
    summary: str = Field(description="Brief plan summary.")
    steps: list[dict[str, Any]] = Field(description="Recursive structured plan steps.")


class SubmitPlan(Tool):
    name = "SubmitPlan"
    description = "Submit the structured plan. Use this instead of relying on markdown formatting."
    params_model = SubmitPlanParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: SubmitPlanParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        result = validate_plan_payload(title=params.title, summary=params.summary, steps=params.steps)
        if not result.ok:
            run.add_event("plan_validation_failed", errors=result.errors)
            self._store.save_run(run)
            return _json({"status": "invalid_plan", "errors": result.errors})
        run.title = params.title.strip()
        run.plan_summary = params.summary.strip()
        run.submitted_plan = result.plan
        run.status = RunStatus.PLAN_REVIEW
        run.add_event("plan_submitted", step_count=len(result.plan))
        self._store.save_run(run)
        return _json({"status": "ok", "next": "plan_review"})


class ApprovePlanParams(BaseModel):
    run_id: str
    reason: str


class ApprovePlan(Tool):
    name = "ApprovePlan"
    description = "Approve the submitted structured plan after review."
    params_model = ApprovePlanParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: ApprovePlanParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        if not run.submitted_plan:
            return _json_error("missing_plan", "no submitted plan is available")
        run.approved_plan = run.submitted_plan
        run.status = RunStatus.EXECUTING
        run.review_result = {"plan_review": "approved", "reason": params.reason}
        for step in executable_steps(run.approved_plan):
            run.step_status.setdefault(step.step_id, StepStatus.PENDING)
        run.add_event("plan_approved", reason=params.reason)
        self._store.save_run(run)
        return _json({"status": "ok", "next": "execute"})


class RejectPlanParams(BaseModel):
    run_id: str
    issues: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)


class RejectPlan(Tool):
    name = "RejectPlan"
    description = "Reject the submitted plan and send concrete revision requirements back to plan."
    params_model = RejectPlanParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: RejectPlanParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        payload = {"issues": params.issues, "required_changes": params.required_changes}
        run.plan_rejections.append(payload)
        run.submitted_plan = []
        run.status = RunStatus.PLANNING
        run.add_event("plan_rejected", **payload)
        self._store.save_run(run)
        return _json({"status": "ok", "next": "plan", **payload})


class SubmitSubAgentStepParams(BaseModel):
    run_id: str
    step_id: str
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    evidence: str = ""


class SubmitSubAgentStep(Tool):
    name = "SubmitSubAgentStep"
    description = "Submit completion evidence for the current execute step."
    params_model = SubmitSubAgentStepParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: SubmitSubAgentStepParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        if params.step_id != run.current_step_id:
            return _json_error("wrong_step", f"current step is {run.current_step_id}, got {params.step_id}")
        if not validate_step_exists(run.approved_plan, params.step_id):
            return _json_error("unknown_step", f"unknown step_id: {params.step_id}")
        run.step_status[params.step_id] = StepStatus.COMPLETED
        run.step_submissions[params.step_id] = {
            "summary": params.summary,
            "changed_files": params.changed_files,
            "evidence": params.evidence,
        }
        run.add_event("step_submitted", step_id=params.step_id)
        self._store.save_run(run)
        return _json({"status": "ok", "step_id": params.step_id})


class ApproveTestParams(BaseModel):
    run_id: str
    evidence: str


class ApproveTest(Tool):
    name = "ApproveTest"
    description = "Approve test results for the completed execution."
    params_model = ApproveTestParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: ApproveTestParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        run.test_result = {"status": "approved", "evidence": params.evidence}
        run.status = RunStatus.EXECUTE_REVIEW
        run.add_event("test_approved")
        self._store.save_run(run)
        return _json({"status": "ok", "next": "execute_review"})


class ReportTestFailureParams(BaseModel):
    run_id: str
    failed_steps: list[str] = Field(default_factory=list)
    evidence: str
    required_fixes: list[str] = Field(default_factory=list)


class ReportTestFailure(Tool):
    name = "ReportTestFailure"
    description = "Report failed tests and identify the plan steps that need execute fixes."
    params_model = ReportTestFailureParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: ReportTestFailureParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        if not params.failed_steps:
            return _json_error("missing_failed_steps", "failed_steps must identify at least one affected step")
        invalid = validate_failed_steps(run.approved_plan, params.failed_steps)
        if invalid:
            return _json_error("unknown_step", f"unknown failed_steps: {', '.join(invalid)}")
        for step_id in params.failed_steps:
            run.step_status[step_id] = StepStatus.NEEDS_FIX
        run.test_result = {
            "status": "failed",
            "failed_steps": params.failed_steps,
            "evidence": params.evidence,
            "required_fixes": params.required_fixes,
        }
        run.status = RunStatus.EXECUTING
        run.add_event("test_failed", failed_steps=params.failed_steps)
        self._store.save_run(run)
        return _json({"status": "ok", "next": "execute", "failed_steps": params.failed_steps})


class ApproveExecutionParams(BaseModel):
    run_id: str
    summary: str


class ApproveExecution(Tool):
    name = "ApproveExecution"
    description = "Approve final execution quality and complete the multi-agent run."
    params_model = ApproveExecutionParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: ApproveExecutionParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        run.review_result = {"status": "approved", "summary": params.summary}
        run.status = RunStatus.COMPLETED
        run.add_event("execution_approved")
        self._store.save_run(run)
        return _json({"status": "ok", "next": "completed"})


class RejectExecutionParams(BaseModel):
    run_id: str
    issues: list[str] = Field(default_factory=list)
    required_fixes: list[str] = Field(default_factory=list)
    failed_steps: list[str] = Field(default_factory=list)


class RejectExecution(Tool):
    name = "RejectExecution"
    description = "Reject execution quality and send concrete fixes back to execute."
    params_model = RejectExecutionParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: RejectExecutionParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        failed_steps = params.failed_steps or [step.step_id for step in executable_steps(run.approved_plan)]
        invalid = validate_failed_steps(run.approved_plan, failed_steps)
        if invalid:
            return _json_error("unknown_step", f"unknown failed_steps: {', '.join(invalid)}")
        for step_id in failed_steps:
            run.step_status[step_id] = StepStatus.NEEDS_FIX
        run.review_result = {
            "status": "rejected",
            "issues": params.issues,
            "required_fixes": params.required_fixes,
            "failed_steps": failed_steps,
        }
        run.status = RunStatus.EXECUTING
        run.add_event("execution_rejected", failed_steps=failed_steps)
        self._store.save_run(run)
        return _json({"status": "ok", "next": "execute", "failed_steps": failed_steps})


class InspectSubAgentWorkParams(BaseModel):
    run_id: str = Field(description="Exact multi-agent run_id to inspect.")
    agent: str = Field(description="Sub-agent name: plan, plan_review, execute, test, or execute_review.")
    step_id: str = Field(default="", description="Optional step_id filter for execute work.")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=12000, ge=1, le=50000)


class InspectSubAgentWork(Tool):
    name = "InspectSubAgentWork"
    description = "Inspect stored sub-agent work for a multi-agent run by run_id and agent."
    params_model = InspectSubAgentWorkParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: InspectSubAgentWorkParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        try:
            role = AgentRole(params.agent)
        except ValueError:
            return _json_error("invalid_agent", f"invalid agent: {params.agent}")
        content = _render_agent_work(run, role, params.step_id)
        chunk = content[params.offset : params.offset + params.limit]
        next_offset = params.offset + len(chunk)
        return _json(
            {
                "run_id": run.run_id,
                "agent": role.value,
                "step_id": params.step_id,
                "content": chunk,
                "next_offset": next_offset if next_offset < len(content) else None,
                "has_more": next_offset < len(content),
            }
        )


def control_tools_for_role(store: MultiAgentStore, role: AgentRole) -> list[Tool]:
    if role == AgentRole.PLAN:
        return [SubmitPlan(store)]
    if role == AgentRole.PLAN_REVIEW:
        return [ApprovePlan(store), RejectPlan(store)]
    if role == AgentRole.EXECUTE:
        return [SubmitSubAgentStep(store)]
    if role == AgentRole.TEST:
        return [ApproveTest(store), ReportTestFailure(store)]
    if role == AgentRole.EXECUTE_REVIEW:
        return [ApproveExecution(store), RejectExecution(store)]
    return []


def _render_agent_work(run: Any, role: AgentRole, step_id: str = "") -> str:
    parts: list[str] = []
    if role == AgentRole.EXECUTE and step_id:
        submission = run.step_submissions.get(step_id)
        if submission:
            parts.append(f"Step {step_id} submission:\n{json.dumps(submission, ensure_ascii=False, indent=2)}")
    final_answer = run.subagent_final_answers.get(role.value, "")
    if final_answer:
        parts.append(f"Final answer:\n{final_answer}")
    messages = run.subagent_messages.get(role.value, [])
    rendered_messages: list[str] = []
    for message in messages:
        text = json.dumps(message, ensure_ascii=False, default=str)
        if step_id and step_id not in text:
            continue
        rendered_messages.append(text)
    if rendered_messages:
        parts.append("Messages:\n" + "\n".join(rendered_messages))
    return "\n\n".join(parts)


def _json(payload: dict[str, Any]) -> ToolResult:
    return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2))


def _json_error(code: str, message: str) -> ToolResult:
    return ToolResult(
        output=json.dumps({"status": "error", "error": code, "message": message}, ensure_ascii=False, indent=2),
        is_error=True,
    )
