from __future__ import annotations

import json
from time import time
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from mycodingagent.tool_runtime.base import Tool, ToolResult

from mycodingagent.multi_agent.models import AgentRole, RunStatus, StepStatus, executable_steps
from mycodingagent.multi_agent.store import MultiAgentStore
from mycodingagent.multi_agent.validators import validate_failed_steps, validate_plan_payload, validate_step_exists


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
        run.status = RunStatus.SCHEDULING
        run.review_result = {"plan_review": "approved", "reason": params.reason}
        for step in executable_steps(run.approved_plan):
            run.step_status.setdefault(step.step_id, StepStatus.PENDING)
        run.add_event("plan_approved", reason=params.reason)
        self._store.save_run(run)
        return _json({"status": "ok", "next": "scheduling"})


class ScheduledTaskInput(BaseModel):
    task: str = Field(description="Concrete task for one execute sub-agent.", min_length=1)
    test_instruction: str = Field(description="Concrete test instruction for the paired task_test sub-agent.", min_length=1)
    target_files: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class DispatchTasksParams(BaseModel):
    run_id: str
    tasks: list[ScheduledTaskInput] = Field(
        description=(
            "Batch of execute/task_test task pairs to dispatch together. Independent tasks in this batch "
            "may run concurrently up to the runtime max_parallel_tasks limit."
        ),
        min_length=1,
    )


class DispatchTasks(Tool):
    name = "DispatchTasks"
    description = (
        "Dispatch a batch of complete, self-contained engineering tasks and wait for runtime to execute all dispatchable tasks. "
        "Each task should include its necessary read, write, and verification work rather than splitting those actions into separate tasks. "
        "The tool result is the aggregated pass/fail/blocked outcome after execute/task_test agents finish, not merely queued."
    )
    params_model = DispatchTasksParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: DispatchTasksParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        created: list[dict[str, Any]] = []
        for item in params.tasks:
            task_id = uuid4().hex
            run.scheduled_tasks[task_id] = {
                "task_id": task_id,
                "task": item.task,
                "test_instruction": item.test_instruction,
                "target_files": item.target_files,
                "depends_on": item.depends_on,
                "status": "queued",
                "summary": "",
                "changed_files": [],
                "reason": "",
                "conflicts": [],
                "attempts": 0,
                "test_attempts": 0,
                "created_at": time(),
                "updated_at": time(),
            }
            created.append({"task_id": task_id, "status": "queued"})
        run.add_event("tasks_dispatched", task_ids=[task["task_id"] for task in created])
        self._store.save_run(run)
        return _json({"status": "queued", "tasks": created})


class SubmitFinalTestParams(BaseModel):
    run_id: str
    summary: str


class SubmitFinalTest(Tool):
    name = "SubmitFinalTest"
    description = "Submit scheduling completion and request final whole-task validation after all dispatched tasks passed."
    params_model = SubmitFinalTestParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: SubmitFinalTestParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        unfinished = [
            {"task_id": task_id, "status": task.get("status")}
            for task_id, task in run.scheduled_tasks.items()
            if task.get("status") in {"queued", "running", "testing", "needs_fix"}
        ]
        failed_tasks = [
            {"task_id": task_id, "reason": task.get("reason", "")}
            for task_id, task in run.scheduled_tasks.items()
            if task.get("status") == "failed"
        ]
        if not run.scheduled_tasks:
            return _json_error("no_tasks", "scheduling cannot complete before dispatching at least one task")
        if unfinished:
            return _json({"status": "blocked", "unfinished_tasks": unfinished})
        run.status = RunStatus.FINAL_TESTING
        run.review_result = {
            "scheduling": "completed",
            "summary": params.summary,
            "failed_tasks_repaired_or_superseded": failed_tasks,
        }
        run.add_event("scheduling_completed", summary=params.summary)
        self._store.save_run(run)
        return _json({"status": "ok", "next": "final_test"})


class SubmitTaskExecutionParams(BaseModel):
    run_id: str
    task_id: str
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    evidence: str = ""


class SubmitTaskExecution(Tool):
    name = "SubmitTaskExecution"
    description = "Submit execution evidence for the current dispatched task."
    params_model = SubmitTaskExecutionParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: SubmitTaskExecutionParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        task = run.scheduled_tasks.get(params.task_id)
        if not task:
            return _json_error("task_not_found", f"task not found: {params.task_id}")
        if task.get("status") not in {"running", "needs_fix"}:
            return _json_error("wrong_task_status", f"task {params.task_id} is {task.get('status')}, expected running")
        task.update(
            {
                "status": "testing",
                "summary": params.summary,
                "changed_files": params.changed_files,
                "evidence": params.evidence,
                "updated_at": time(),
            }
        )
        run.step_submissions[params.task_id] = {
            "summary": params.summary,
            "changed_files": params.changed_files,
            "evidence": params.evidence,
        }
        run.add_event("task_execution_submitted", task_id=params.task_id)
        self._store.save_run(run)
        return _json({"status": "ok", "task_id": params.task_id, "next": "task_test"})


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
        _append_feedback_event(
            run,
            source_agent=AgentRole.PLAN_REVIEW,
            target_agent=AgentRole.PLAN,
            tool_name="RejectPlan",
            payload=payload,
        )
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
        _append_feedback_event(
            run,
            source_agent=AgentRole.TEST,
            target_agent=AgentRole.EXECUTE,
            tool_name="ReportTestFailure",
            payload=run.test_result,
        )
        run.status = RunStatus.EXECUTING
        run.add_event("test_failed", failed_steps=params.failed_steps)
        self._store.save_run(run)
        return _json({"status": "ok", "next": "execute", "failed_steps": params.failed_steps})


class ApproveTaskTestParams(BaseModel):
    run_id: str
    task_id: str
    evidence: str


class ApproveTaskTest(Tool):
    name = "ApproveTaskTest"
    description = "Approve the paired test for the current dispatched task."
    params_model = ApproveTaskTestParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: ApproveTaskTestParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        task = run.scheduled_tasks.get(params.task_id)
        if not task:
            return _json_error("task_not_found", f"task not found: {params.task_id}")
        task["status"] = "passed"
        task["test_evidence"] = params.evidence
        task["updated_at"] = time()
        run.add_event("task_test_approved", task_id=params.task_id)
        self._store.save_run(run)
        return _json({"status": "ok", "task_id": params.task_id})


class ReportTaskFailureParams(BaseModel):
    run_id: str
    task_id: str
    reason: str
    required_fixes: list[str] = Field(default_factory=list)


class ReportTaskFailure(Tool):
    name = "ReportTaskFailure"
    description = "Report test failure for the paired task and send fixes back to execute."
    params_model = ReportTaskFailureParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: ReportTaskFailureParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        task = run.scheduled_tasks.get(params.task_id)
        if not task:
            return _json_error("task_not_found", f"task not found: {params.task_id}")
        payload = {
            "status": "failed",
            "task_id": params.task_id,
            "reason": params.reason,
            "required_fixes": params.required_fixes,
        }
        task["status"] = "needs_fix"
        task["reason"] = params.reason
        task["required_fixes"] = params.required_fixes
        task["updated_at"] = time()
        _append_feedback_event(
            run,
            source_agent=AgentRole.TEST,
            target_agent=AgentRole.EXECUTE,
            tool_name="ReportTaskFailure",
            payload=payload,
        )
        run.add_event("task_test_failed", task_id=params.task_id, reason=params.reason)
        self._store.save_run(run)
        return _json({"status": "ok", "next": "execute", "task_id": params.task_id})


class ApproveFinalTestParams(BaseModel):
    run_id: str
    evidence: str


class ApproveFinalTest(Tool):
    name = "ApproveFinalTest"
    description = "Approve final end-to-end validation and complete the multi-agent run."
    params_model = ApproveFinalTestParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: ApproveFinalTestParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        run.test_result = {"status": "approved", "evidence": params.evidence}
        run.status = RunStatus.COMPLETED
        run.add_event("final_test_approved")
        self._store.save_run(run)
        return _json({"status": "ok", "next": "completed"})


class ReportFinalTestFailureParams(BaseModel):
    run_id: str
    reason: str
    failed_tasks: list[str] = Field(default_factory=list)
    required_fixes: list[str] = Field(default_factory=list)


class ReportFinalTestFailure(Tool):
    name = "ReportFinalTestFailure"
    description = "Report final validation failure and send concrete work back to scheduling."
    params_model = ReportFinalTestFailureParams
    category = "read"

    def __init__(self, store: MultiAgentStore) -> None:
        self._store = store

    async def execute(self, params: ReportFinalTestFailureParams) -> ToolResult:
        run = self._store.load_run(params.run_id)
        if run is None:
            return _json_error("run_not_found", f"run not found: {params.run_id}")
        payload = {
            "status": "failed",
            "reason": params.reason,
            "failed_tasks": params.failed_tasks,
            "required_fixes": params.required_fixes,
        }
        run.test_result = payload
        run.status = RunStatus.SCHEDULING
        _append_feedback_event(
            run,
            source_agent=AgentRole.FINAL_TEST,
            target_agent=AgentRole.SCHEDULING,
            tool_name="ReportFinalTestFailure",
            payload=payload,
        )
        run.add_event("final_test_failed", reason=params.reason, failed_tasks=params.failed_tasks)
        self._store.save_run(run)
        return _json({"status": "ok", "next": "scheduling"})


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
        _append_feedback_event(
            run,
            source_agent=AgentRole.EXECUTE_REVIEW,
            target_agent=AgentRole.EXECUTE,
            tool_name="RejectExecution",
            payload=run.review_result,
        )
        run.status = RunStatus.EXECUTING
        run.add_event("execution_rejected", failed_steps=failed_steps)
        self._store.save_run(run)
        return _json({"status": "ok", "next": "execute", "failed_steps": failed_steps})


def control_tools_for_role(store: MultiAgentStore, role: AgentRole) -> list[Tool]:
    if role == AgentRole.PLAN:
        return [SubmitPlan(store)]
    if role == AgentRole.PLAN_REVIEW:
        return [ApprovePlan(store), RejectPlan(store)]
    if role == AgentRole.SCHEDULING:
        return [DispatchTasks(store), SubmitFinalTest(store)]
    if role == AgentRole.EXECUTE:
        return [SubmitTaskExecution(store), SubmitSubAgentStep(store)]
    if role == AgentRole.TEST:
        return [ApproveTaskTest(store), ReportTaskFailure(store), ApproveTest(store), ReportTestFailure(store)]
    if role == AgentRole.FINAL_TEST:
        return [ApproveFinalTest(store), ReportFinalTestFailure(store)]
    if role == AgentRole.EXECUTE_REVIEW:
        return [ApproveExecution(store), RejectExecution(store)]
    return []


def _append_feedback_event(
    run: Any,
    *,
    source_agent: AgentRole,
    target_agent: AgentRole,
    tool_name: str,
    payload: dict[str, Any],
) -> None:
    event = {
        "event_id": uuid4().hex,
        "source_agent": source_agent.value,
        "tool_name": tool_name,
        "target_agent": target_agent.value,
        "payload": payload,
        "created_at": time(),
        "delivered": False,
    }
    run.feedback_events.setdefault(target_agent.value, []).append(event)


def _json(payload: dict[str, Any]) -> ToolResult:
    return ToolResult(output=json.dumps(payload, ensure_ascii=False, indent=2))


def _json_error(code: str, message: str) -> ToolResult:
    return ToolResult(
        output=json.dumps({"status": "error", "error": code, "message": message}, ensure_ascii=False, indent=2),
        is_error=True,
    )
