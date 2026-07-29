from __future__ import annotations

import asyncio
import json

from multiAgent.context import (
    build_or_resume_subagent_messages,
    build_role_context,
    load_system_prompt,
    run_summary_for_main_context,
)
from multiAgent.models import AgentRole, MultiAgentRun, RunStatus, StepStatus
from multiAgent.orchestrator import MultiAgentOrchestrator
from multiAgent.store import MultiAgentStore
from multiAgent.tool_policy import schemas_for_role
from multiAgent.tools import (
    ApprovePlan,
    ApprovePlanParams,
    RejectExecution,
    RejectExecutionParams,
    RejectPlan,
    RejectPlanParams,
    ReportTestFailure,
    ReportTestFailureParams,
    SubmitFinalTest,
    SubmitFinalTestParams,
    SubmitPlan,
    SubmitPlanParams,
    SubmitSubAgentStep,
    SubmitSubAgentStepParams,
)
from multiAgent.validators import validate_plan_payload
from mycodingagent.llm_runtime.client import PendingToolCall
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
    assert json.loads(approve_result.output)["next"] == "scheduling"
    approved = store.load_run(run.run_id)
    assert approved is not None
    assert approved.status == RunStatus.SCHEDULING
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


def test_execute_context_includes_round_budget(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="task")
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
    approved.subagent_round_limits[AgentRole.EXECUTE.value] = 30
    approved.subagent_rounds_used[AgentRole.EXECUTE.value] = 26
    approved.subagent_tool_calls_used[AgentRole.EXECUTE.value] = 42

    context = json.loads(build_role_context(role=AgentRole.EXECUTE, run=approved, main_messages=[]))

    assert context["agent_round_limit"] == 30
    assert context["agent_rounds_used"] == 26
    assert context["agent_rounds_remaining"] == 4
    assert context["tool_calls_used_in_step"] == 42
    assert "SubmitTaskExecution" in context["round_budget_warning"]


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


def test_execute_schemas_require_task_id(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    registry = ToolRegistry()
    registry.register(DummyReadTool())

    read_schema = next(
        schema for schema in schemas_for_role(role=AgentRole.EXECUTE, registry=registry, store=store)
        if schema["name"] == "ReadFile"
    )

    assert "task_id" in read_schema["parameters"]["required"]
    assert "task_id" in read_schema["parameters"]["properties"]


def test_scheduling_schema_only_exposes_batch_dispatch_and_final_test(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    registry = ToolRegistry()
    registry.register(DummyReadTool())
    registry.register(DummyWriteTool())

    names = {schema["name"] for schema in schemas_for_role(role=AgentRole.SCHEDULING, registry=registry, store=store)}

    assert "ReadFile" in names
    assert "WriteFile" not in names
    assert {"DispatchTasks", "SubmitFinalTest"}.issubset(names)
    assert "DispatchTask" not in names
    assert "CheckTask" not in names
    assert "CompleteScheduling" not in names
    dispatch_schema = next(schema for schema in schemas_for_role(role=AgentRole.SCHEDULING, registry=registry, store=store) if schema["name"] == "DispatchTasks")
    assert "self-contained engineering tasks" in dispatch_schema["description"]
    assert "pass/fail/blocked" in dispatch_schema["description"]


def test_submit_final_test_allows_repaired_failed_history(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="task")
    run.status = RunStatus.SCHEDULING
    run.scheduled_tasks = {
        "failed_old": {"status": "failed", "reason": "original attempt failed"},
        "repair": {"status": "passed", "summary": "repair verified"},
    }
    store.save_run(run)

    result = asyncio.run(
        SubmitFinalTest(store).execute(
            SubmitFinalTestParams(run_id=run.run_id, summary="Repair task passed; ready for final validation.")
        )
    )

    payload = json.loads(result.output)
    updated = store.load_run(run.run_id)
    assert updated is not None
    assert payload["next"] == "final_test"
    assert updated.status == RunStatus.FINAL_TESTING
    assert updated.review_result["failed_tasks_repaired_or_superseded"] == [
        {"task_id": "failed_old", "reason": "original attempt failed"}
    ]


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
    assert "inspect_tool" not in summary


def test_multi_agent_is_not_exposed_as_main_model_tool(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    registry = ToolRegistry()
    registry.register(DummyReadTool())
    registry.register(DummyWriteTool())

    main_names = {schema["name"] for schema in registry.get_all_schemas("openai")}
    assert "DelegateToMultiAgent" not in main_names
    assert "InspectSubAgentWork" not in main_names

    for role in AgentRole:
        role_names = {schema["name"] for schema in schemas_for_role(role=role, registry=registry, store=store)}
        assert "DelegateToMultiAgent" not in role_names
        assert "InspectSubAgentWork" not in role_names


def test_reject_plan_feedback_is_delivered_to_resumed_plan_context(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="task")
    run.subagent_messages[AgentRole.PLAN.value] = [
        {"role": "system", "content": "plan system"},
        {"role": "user", "content": "initial plan context"},
        {"role": "assistant", "content": "old plan answer"},
    ]
    store.save_run(run)

    asyncio.run(
        RejectPlan(store).execute(
            RejectPlanParams(
                run_id=run.run_id,
                issues=["missing tests"],
                required_changes=["add test step"],
            )
        )
    )
    rejected = store.load_run(run.run_id)
    assert rejected is not None
    assert rejected.feedback_events[AgentRole.PLAN.value][0]["delivered"] is False

    messages, updated = build_or_resume_subagent_messages(
        role=AgentRole.PLAN,
        run=rejected,
        main_messages=[],
    )

    assert messages[0]["content"] == "plan system"
    assert messages[2]["content"] == "old plan answer"
    assert messages[-2]["tool_calls"][0]["function"]["name"] == "RejectPlan"
    assert messages[-1]["role"] == "tool"
    assert messages[-1]["tool_call_id"].startswith("feedback_")
    assert "missing tests" in messages[-1]["content"]
    assert updated.feedback_events[AgentRole.PLAN.value][0]["delivered"] is True


def test_feedback_delivery_is_not_repeated(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="task")
    run.subagent_messages[AgentRole.PLAN.value] = [{"role": "assistant", "content": "old"}]
    store.save_run(run)
    asyncio.run(
        RejectPlan(store).execute(
            RejectPlanParams(run_id=run.run_id, issues=["bad"], required_changes=["fix"])
        )
    )
    rejected = store.load_run(run.run_id)
    assert rejected is not None

    first_messages, updated = build_or_resume_subagent_messages(
        role=AgentRole.PLAN,
        run=rejected,
        main_messages=[],
    )
    second_messages, _ = build_or_resume_subagent_messages(
        role=AgentRole.PLAN,
        run=updated,
        main_messages=[],
    )

    assert sum("RejectPlan" in json.dumps(message, ensure_ascii=False) for message in first_messages) == 1
    assert sum("RejectPlan" in json.dumps(message, ensure_ascii=False) for message in second_messages) == 0


def test_report_test_failure_feedback_targets_execute(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="task")
    run.approved_plan = validate_plan_payload(title="Plan", summary="s", steps=VALID_STEPS).plan
    run.step_status = {"1.1": StepStatus.COMPLETED}
    run.subagent_messages[AgentRole.EXECUTE.value] = [{"role": "assistant", "content": "execute history"}]
    store.save_run(run)

    asyncio.run(
        ReportTestFailure(store).execute(
            ReportTestFailureParams(
                run_id=run.run_id,
                failed_steps=["1.1"],
                evidence="pytest failed",
                required_fixes=["fix assertion"],
            )
        )
    )
    failed = store.load_run(run.run_id)
    assert failed is not None

    messages, updated = build_or_resume_subagent_messages(
        role=AgentRole.EXECUTE,
        run=failed,
        main_messages=[],
    )

    assert messages[-2]["tool_calls"][0]["function"]["name"] == "ReportTestFailure"
    assert "pytest failed" in messages[-1]["content"]
    assert updated.feedback_events[AgentRole.EXECUTE.value][0]["delivered"] is True


def test_reject_execution_feedback_targets_execute(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="task")
    run.approved_plan = validate_plan_payload(title="Plan", summary="s", steps=VALID_STEPS).plan
    run.step_status = {"1.1": StepStatus.COMPLETED}
    run.subagent_messages[AgentRole.EXECUTE.value] = [{"role": "assistant", "content": "execute history"}]
    store.save_run(run)

    asyncio.run(
        RejectExecution(store).execute(
            RejectExecutionParams(
                run_id=run.run_id,
                issues=["quality issue"],
                required_fixes=["simplify flow"],
                failed_steps=["1.1"],
            )
        )
    )
    rejected = store.load_run(run.run_id)
    assert rejected is not None

    messages, updated = build_or_resume_subagent_messages(
        role=AgentRole.EXECUTE,
        run=rejected,
        main_messages=[],
    )

    assert messages[-2]["tool_calls"][0]["function"]["name"] == "RejectExecution"
    assert "quality issue" in messages[-1]["content"]
    assert updated.feedback_events[AgentRole.EXECUTE.value][0]["delivered"] is True


def test_fresh_subagent_context_when_no_history(tmp_path):
    run = MultiAgentRun.create(task="task")

    messages, updated = build_or_resume_subagent_messages(
        role=AgentRole.PLAN,
        run=run,
        main_messages=[],
    )

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert updated.feedback_events == {}


def test_execute_round_limit_failure_is_diagnostic(tmp_path, monkeypatch):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    registry = ToolRegistry()
    registry.register(DummyReadTool())
    run = MultiAgentRun.create(task="task")
    store.save_run(run)
    asyncio.run(
        SubmitPlan(store).execute(
            SubmitPlanParams(run_id=run.run_id, title="Plan", summary="Do work", steps=VALID_STEPS)
        )
    )
    asyncio.run(ApprovePlan(store).execute(ApprovePlanParams(run_id=run.run_id, reason="ok")))
    approved = store.load_run(run.run_id)
    assert approved is not None
    approved.status = RunStatus.EXECUTING
    store.save_run(approved)

    call_index = 0

    async def fake_stream_one_round(*args, **kwargs):
        nonlocal call_index
        call_index += 1
        return (
            "",
            [
                PendingToolCall(
                    tool_id=f"call_{call_index}",
                    tool_name="ReadFile",
                    arguments=json.dumps(
                        {"value": "read", "step_id": "1.1", "intent": "consume a round without submitting"}
                    ),
                )
            ],
            None,
        )

    monkeypatch.setattr("multiAgent.orchestrator.agent_round_limit", lambda: 2)
    monkeypatch.setattr("multiAgent.orchestrator.stream_one_round", fake_stream_one_round)

    orchestrator = MultiAgentOrchestrator(
        store=store,
        registry=registry,
        api_client=object(),
        memory_runtime=None,
    )
    result = asyncio.run(orchestrator.run(run_id=run.run_id, main_messages=[]))

    assert result.status == RunStatus.FAILED
    assert result.error == "execute exceeded agent tool rounds before submitting step: 1.1"
    assert result.subagent_exit_reasons[AgentRole.EXECUTE.value] == "max_agent_tool_rounds_exceeded"
    assert any(event["kind"] == "agent_round_limit_reached" for event in result.events)
    assert any(event["kind"] == "execute_step_attempt_failed" for event in result.events)


def test_scheduled_tasks_are_processed_in_parallel_batches(tmp_path):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="task")
    run.status = RunStatus.SCHEDULING
    for index in range(3):
        task_id = f"task_{index}"
        run.scheduled_tasks[task_id] = {
            "task_id": task_id,
            "task": f"task {index}",
            "test_instruction": f"test {index}",
            "status": "queued",
            "depends_on": [],
        }
    store.save_run(run)

    orchestrator = MultiAgentOrchestrator(
        store=store,
        registry=ToolRegistry(),
        api_client=object(),
        memory_runtime=None,
    )
    running = 0
    max_seen = 0

    async def fake_run_task(*, run_id, task_id, main_messages):
        nonlocal running, max_seen
        running += 1
        max_seen = max(max_seen, running)
        await asyncio.sleep(0.01)
        current = store.load_run(run_id)
        assert current is not None
        current.scheduled_tasks[task_id]["status"] = "passed"
        store.save_run(current)
        running -= 1

    orchestrator._run_task = fake_run_task  # type: ignore[method-assign]

    asyncio.run(orchestrator._process_scheduled_tasks(run, [], batch_task_ids=set(run.scheduled_tasks)))

    finished = store.load_run(run.run_id)
    assert finished is not None
    assert {task["status"] for task in finished.scheduled_tasks.values()} == {"passed"}
    assert max_seen > 1


def test_task_test_no_decision_gets_one_forced_retry_then_can_pass(tmp_path, monkeypatch):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    registry = ToolRegistry()
    registry.register(DummyReadTool())
    run = MultiAgentRun.create(task="task")
    run.status = RunStatus.SCHEDULING
    run.scheduled_tasks["task_1"] = {
        "task_id": "task_1",
        "task": "fix one thing",
        "test_instruction": "verify one thing",
        "status": "queued",
        "depends_on": [],
    }
    store.save_run(run)
    calls = []

    async def fake_stream_one_round(*args, **kwargs):
        label = kwargs["output_label"]
        calls.append(label)
        if label == AgentRole.EXECUTE.value:
            return (
                "",
                [
                    PendingToolCall(
                        tool_id="execute_submit",
                        tool_name="SubmitTaskExecution",
                        arguments=json.dumps(
                            {
                                "run_id": run.run_id,
                                "task_id": "task_1",
                                "summary": "done",
                                "changed_files": [],
                                "evidence": "done",
                            }
                        ),
                    )
                ],
                None,
            )
        if calls.count(AgentRole.TEST.value) == 1:
            return (
                "",
                [
                    PendingToolCall(
                        tool_id="test_read",
                        tool_name="ReadFile",
                        arguments=json.dumps({"value": "verification output"}),
                    )
                ],
                None,
            )
        if calls.count(AgentRole.TEST.value) == 2:
            return ("Looks good but I forgot to submit.", [], None)
        return (
            "",
            [
                PendingToolCall(
                    tool_id="test_approve",
                    tool_name="ApproveTaskTest",
                    arguments=json.dumps(
                        {
                            "run_id": run.run_id,
                            "task_id": "task_1",
                            "evidence": "verified after runtime reminder",
                        }
                    ),
                )
            ],
            None,
        )

    monkeypatch.setattr("multiAgent.orchestrator.stream_one_round", fake_stream_one_round)
    orchestrator = MultiAgentOrchestrator(
        store=store,
        registry=registry,
        api_client=object(),
        memory_runtime=None,
    )

    asyncio.run(orchestrator._run_task(run_id=run.run_id, task_id="task_1", main_messages=[]))

    updated = store.load_run(run.run_id)
    assert updated is not None
    assert updated.scheduled_tasks["task_1"]["status"] == "passed"
    assert updated.scheduled_tasks["task_1"]["test_attempts"] == 2
    assert any(event["kind"] == "task_test_decision_retry" for event in updated.events)
    test_messages = updated.subagent_messages["test:task_1"]
    assert "RuntimeTestDecisionRequired" in json.dumps(test_messages, ensure_ascii=False)


def test_task_test_no_decision_fails_with_diagnostic_after_retry(tmp_path, monkeypatch):
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    registry = ToolRegistry()
    registry.register(DummyReadTool())
    run = MultiAgentRun.create(task="task")
    run.status = RunStatus.SCHEDULING
    run.scheduled_tasks["task_1"] = {
        "task_id": "task_1",
        "task": "fix one thing",
        "test_instruction": "verify one thing",
        "status": "queued",
        "depends_on": [],
    }
    store.save_run(run)
    test_calls = 0

    async def fake_stream_one_round(*args, **kwargs):
        nonlocal test_calls
        label = kwargs["output_label"]
        if label == AgentRole.EXECUTE.value:
            return (
                "",
                [
                    PendingToolCall(
                        tool_id="execute_submit",
                        tool_name="SubmitTaskExecution",
                        arguments=json.dumps(
                            {
                                "run_id": run.run_id,
                                "task_id": "task_1",
                                "summary": "done",
                                "changed_files": [],
                                "evidence": "done",
                            }
                        ),
                    )
                ],
                None,
            )
        test_calls += 1
        if test_calls == 1:
            return (
                "",
                [
                    PendingToolCall(
                        tool_id="test_read",
                        tool_name="ReadFile",
                        arguments=json.dumps({"value": "verification output"}),
                    )
                ],
                None,
            )
        return ("Still no decision.", [], None)

    monkeypatch.setattr("multiAgent.orchestrator.stream_one_round", fake_stream_one_round)
    orchestrator = MultiAgentOrchestrator(
        store=store,
        registry=registry,
        api_client=object(),
        memory_runtime=None,
    )

    asyncio.run(orchestrator._run_task(run_id=run.run_id, task_id="task_1", main_messages=[]))

    updated = store.load_run(run.run_id)
    assert updated is not None
    task = updated.scheduled_tasks["task_1"]
    assert task["status"] == "failed"
    assert task["failure_type"] == "task_test_no_decision"
    assert "ApproveTaskTest or ReportTaskFailure" in task["reason"]
    assert task["last_test_message"]
    assert task["last_tool_summary"]
    assert "verification output" in task["last_tool_summary"]
    result = json.loads(orchestrator._scheduled_task_result(run.run_id, {"task_1"}))
    assert result["tasks"][0]["failure_type"] == "task_test_no_decision"
    assert "Do not repeat broad dispatch" in result["next_action"]

    # 1. run_summary_for_main_context diagnostic fields
    summary_json = json.loads(run_summary_for_main_context(updated))
    st = summary_json["scheduled_tasks"]["task_1"]
    assert "failure_type" in st
    assert "last_test_message" in st
    assert "last_tool_summary" in st
    assert "test_attempts" in st

    # 2. _scheduled_task_result contains test_attempts
    assert "test_attempts" in result["tasks"][0]


def test_multi_agent_prompts_discourage_large_file_repeated_reads():
    plan_prompt = load_system_prompt(AgentRole.PLAN)
    plan_review_prompt = load_system_prompt(AgentRole.PLAN_REVIEW)
    execute_prompt = load_system_prompt(AgentRole.EXECUTE)
    scheduling_prompt = load_system_prompt(AgentRole.SCHEDULING)
    test_prompt = load_system_prompt(AgentRole.TEST)

    assert "reads the source once" in plan_prompt
    assert "repeatedly rereading the same file" in plan_review_prompt
    assert "many tiny leaf steps" in plan_review_prompt
    assert "Avoid repeated ReadFile loops over large files" in execute_prompt
    assert "agent_rounds_remaining" in execute_prompt
    assert "atomic engineering task" in scheduling_prompt
    assert "Do not dispatch pure reading" in scheduling_prompt
    assert "RuntimeTestDecisionRequired" in test_prompt
    assert "ApproveTaskTest or ReportTaskFailure" in test_prompt
