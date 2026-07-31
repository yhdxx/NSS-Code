from __future__ import annotations

import asyncio
import json
from time import time
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI

from mycodingagent.configuration import CONFIG
from mycodingagent.llm_runtime import client as llm_client
from mycodingagent.llm_runtime.streaming import assistant_message, normalize_stream_result, stream_one_round
from mycodingagent.tool_runtime import ToolRegistry
from mycodingagent.tool_runtime.execution import (
    RepeatedFailureTracker,
    ToolExecution,
    execute_tool,
    parse_tool_arguments_object,
)

from mycodingagent.multi_agent.context import (
    build_or_resume_subagent_messages,
    execute_round_budget,
    message_key_for_role,
    next_open_step,
    run_summary_for_main_context,
)
from mycodingagent.multi_agent.file_coordination import FileCoordinator
from mycodingagent.multi_agent.models import (
    AgentRole,
    MultiAgentRun,
    ROLE_TERMINAL_STATUSES,
    RunStatus,
    StepStatus,
    TaskStatus,
    TERMINAL_STATUSES,
)
from mycodingagent.multi_agent.store import MultiAgentStore
from mycodingagent.multi_agent.tool_policy import schemas_for_role
from mycodingagent.multi_agent.tools import control_tools_for_role


MAX_WORKFLOW_CYCLES = 30
MAX_PLAN_REVIEW_ATTEMPTS = 3
MAX_FIX_ATTEMPTS = 3

EXIT_PHASE_CHANGED = "phase_changed"
EXIT_NO_TOOL_CALLS = "no_tool_calls"
EXIT_MAX_AGENT_TOOL_ROUNDS_EXCEEDED = "max_agent_tool_rounds_exceeded"
EXIT_INTERRUPTED = "interrupted"

PHASE_AGENT_CONFIG: dict[RunStatus, tuple[AgentRole, str, int, str]] = {
    RunStatus.PLANNING: (
        AgentRole.PLAN,
        "plan_attempts",
        MAX_PLAN_REVIEW_ATTEMPTS,
        "plan did not submit a valid structured plan",
    ),
    RunStatus.PLAN_REVIEW: (
        AgentRole.PLAN_REVIEW,
        "plan_review_attempts",
        MAX_PLAN_REVIEW_ATTEMPTS,
        "plan_review did not approve or reject the plan",
    ),
    RunStatus.SCHEDULING: (
        AgentRole.SCHEDULING,
        "scheduling_attempts",
        MAX_WORKFLOW_CYCLES,
        "scheduling did not dispatch any task",
    ),
}


def agent_round_limit() -> int:
    return CONFIG.multi_agent.max_agent_rounds


def _now() -> float:
    return time()


class MultiAgentOrchestrator:
    def __init__(
        self,
        *,
        store: MultiAgentStore,
        registry: ToolRegistry,
        api_client: AsyncOpenAI,
        memory_runtime: Any | None = None,
        model: str | None = None,
        cancel_event: asyncio.Event | None = None,
        workspace_root: Any | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.api_client = api_client
        self.memory_runtime = memory_runtime
        self.model = model or llm_client.MODEL
        self.cancel_event = cancel_event
        self.file_coordinator = FileCoordinator(sandbox_root=workspace_root)
        self._operation_lock = asyncio.Lock()

    async def start(self, *, task: str, main_messages: list[dict[str, Any]]) -> MultiAgentRun:
        run = MultiAgentRun.create(
            task=task,
            source_request_ref="main_conversation",
            source_request_preview=task[:500],
        )
        run.add_event("created")
        self.store.save_run(run)
        return await self.run(run_id=run.run_id, main_messages=main_messages)

    async def resume(self, *, run_id: str, main_messages: list[dict[str, Any]]) -> MultiAgentRun:
        run = self.store.load_run(run_id)
        if run is None:
            raise ValueError(f"multi-agent run not found: {run_id}")
        if run.status == RunStatus.PAUSED:
            run.status = run.resume_status or RunStatus.SCHEDULING
            run.resume_status = None
            run.add_event("resumed")
            self.store.save_run(run)
        return await self.run(run_id=run_id, main_messages=main_messages)

    async def run(self, *, run_id: str, main_messages: list[dict[str, Any]]) -> MultiAgentRun:
        for _ in range(MAX_WORKFLOW_CYCLES):
            run = self._load_or_raise(run_id)
            if self._cancelled():
                return self._pause_run(run)
            if run.status in TERMINAL_STATUSES:
                return run
            if run.status == RunStatus.PAUSED:
                return run
            if run.status in PHASE_AGENT_CONFIG:
                await self._run_configured_phase(run, main_messages)
                continue
            if run.status == RunStatus.FINAL_TESTING:
                await self._run_final_test(run, main_messages)
                continue
            if run.status == RunStatus.EXECUTING:
                await self._run_execute(run, main_messages)
                continue
            if run.status == RunStatus.TESTING:
                await self._run_test(run, main_messages)
                continue
            if run.status == RunStatus.EXECUTE_REVIEW:
                await self._run_execute_review(run, main_messages)
                continue
        return self.store.mark_failed(self._load_or_raise(run_id), "multi-agent workflow exceeded cycle limit")

    def result_message(self, run: MultiAgentRun) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": "[MultiAgent Result]\n" + run_summary_for_main_context(run),
            "metadata": {"multi_agent_run_id": run.run_id, "multi_agent_status": run.status.value},
        }

    async def _run_configured_phase(
        self, run: MultiAgentRun, main_messages: list[dict[str, Any]]
    ) -> None:
        role, attempts_field, limit, failure_message = PHASE_AGENT_CONFIG[run.status]
        setattr(run, attempts_field, int(getattr(run, attempts_field)) + 1)
        phase_status = run.status
        self.store.save_run(run)
        await self._run_agent(role=role, run=run, main_messages=main_messages)
        refreshed = self._load_or_raise(run.run_id)
        phase_incomplete = refreshed.status == phase_status
        scheduling_without_tasks = phase_status != RunStatus.SCHEDULING or not refreshed.scheduled_tasks
        if phase_incomplete and getattr(refreshed, attempts_field) >= limit and scheduling_without_tasks:
            self.store.mark_failed(refreshed, failure_message)

    async def _process_scheduled_tasks(
        self,
        run: MultiAgentRun,
        main_messages: list[dict[str, Any]],
        *,
        batch_task_ids: set[str] | None = None,
    ) -> None:
        target_ids = set(batch_task_ids or [])
        while True:
            run = self._load_or_raise(run.run_id)
            if self._cancelled():
                self._pause_run(run)
                return
            if run.status != RunStatus.SCHEDULING:
                return
            candidates = {
                task_id: task
                for task_id, task in run.scheduled_tasks.items()
                if (not target_ids or task_id in target_ids)
            }
            unfinished = {
                task_id: task
                for task_id, task in candidates.items()
                if task.get("status") in {"queued", "running", "needs_fix", "testing"}
            }
            if not unfinished:
                return
            ready: list[str] = []
            for task_id, task in unfinished.items():
                if task.get("status") not in {"queued", "needs_fix"}:
                    continue
                deps = [str(dep) for dep in task.get("depends_on", [])]
                if any(run.scheduled_tasks.get(dep, {}).get("status") != "passed" for dep in deps):
                    continue
                ready.append(task_id)
            if not ready:
                return
            ready = ready[: max(1, int(CONFIG.multi_agent.max_parallel_tasks))]
            for task_id in ready:
                task = run.scheduled_tasks.get(task_id, {})
                task["status"] = "running"
                task["updated_at"] = _now()
            self.store.save_run(run)
            await asyncio.gather(
                *(self._run_task(run_id=run.run_id, task_id=task_id, main_messages=main_messages) for task_id in ready)
            )
            if self._cancelled():
                self._pause_run(self._load_or_raise(run.run_id))
                return

    async def _run_task(self, *, run_id: str, task_id: str, main_messages: list[dict[str, Any]]) -> None:
        for attempt in range(MAX_FIX_ATTEMPTS):
            run = self._load_or_raise(run_id)
            if self._cancelled():
                self._pause_run(run)
                return
            task = run.scheduled_tasks.get(task_id)
            if not task or task.get("status") == "passed":
                return
            task["status"] = "running"
            task["attempts"] = int(task.get("attempts", 0) or 0) + 1
            self.store.save_run(run)
            exit_reason = await self._run_agent(
                role=AgentRole.EXECUTE,
                run=run,
                main_messages=main_messages,
                task_id=task_id,
            )
            run = self._load_or_raise(run_id)
            if run.status == RunStatus.PAUSED or exit_reason == EXIT_INTERRUPTED:
                return
            task = run.scheduled_tasks.get(task_id, {})
            if task.get("status") != "testing":
                task["status"] = "failed"
                task["reason"] = (
                    f"execute exceeded agent tool rounds before submitting task: {task_id}"
                    if exit_reason == EXIT_MAX_AGENT_TOOL_ROUNDS_EXCEEDED
                    else f"execute did not submit current task: {task_id}"
                )
                run.add_event("task_execute_failed", task_id=task_id, reason=task["reason"])
                self.store.save_run(run)
                return
            for test_attempt in range(2):
                run = self._load_or_raise(run_id)
                task = run.scheduled_tasks.get(task_id, {})
                task["test_attempts"] = int(task.get("test_attempts", 0) or 0) + 1
                self.store.save_run(run)
                await self._run_agent(
                    role=AgentRole.TEST,
                    run=run,
                    main_messages=main_messages,
                    task_id=task_id,
                )
                run = self._load_or_raise(run_id)
                if run.status == RunStatus.PAUSED:
                    return
                task = run.scheduled_tasks.get(task_id, {})
                if task.get("status") == "passed":
                    self.store.save_run(run)
                    return
                if task.get("status") == "needs_fix":
                    break
                observation = self._last_agent_observation(run, AgentRole.TEST, task_id=task_id)
                if test_attempt == 0:
                    self._append_test_decision_required(run, task_id=task_id, observation=observation)
                    self.store.save_run(run)
                    continue
                task["status"] = "failed"
                task["failure_type"] = "task_test_no_decision"
                task["reason"] = f"task_test_no_decision: test did not call ApproveTaskTest or ReportTaskFailure for task: {task_id}"
                task["last_test_message"] = observation["last_assistant_message"]
                task["last_tool_summary"] = observation["last_tool_summary"]
                run.add_event(
                    "task_test_no_decision",
                    task_id=task_id,
                    last_test_message=observation["last_assistant_message"],
                    last_tool_summary=observation["last_tool_summary"],
                )
                self.store.save_run(run)
                return
            run = self._load_or_raise(run_id)
            task = run.scheduled_tasks.get(task_id, {})
            if task.get("status") == "needs_fix":
                continue
            return
        run = self._load_or_raise(run_id)
        task = run.scheduled_tasks.get(task_id, {})
        task["status"] = "failed"
        task["reason"] = f"task exceeded fix attempts: {task_id}"
        self.store.save_run(run)

    async def _run_final_test(self, run: MultiAgentRun, main_messages: list[dict[str, Any]]) -> None:
        run.final_test_attempts += 1
        self.store.save_run(run)
        await self._run_agent(role=AgentRole.FINAL_TEST, run=run, main_messages=main_messages)
        refreshed = self._load_or_raise(run.run_id)
        if refreshed.status == RunStatus.FINAL_TESTING and refreshed.final_test_attempts >= MAX_FIX_ATTEMPTS:
            self.store.mark_failed(refreshed, "final_test did not approve or report a concrete failure")

    async def _run_execute(self, run: MultiAgentRun, main_messages: list[dict[str, Any]]) -> None:
        fix_attempts_by_step: dict[str, int] = {}
        while True:
            run = self._load_or_raise(run.run_id)
            step_id = next_open_step(run)
            if not step_id:
                run.status = RunStatus.TESTING
                run.current_step_id = ""
                run.add_event("execute_completed")
                self.store.save_run(run)
                return
            run.current_step_id = step_id
            self.store.save_run(run)
            exit_reason = await self._run_agent(role=AgentRole.EXECUTE, run=run, main_messages=main_messages)
            refreshed = self._load_or_raise(run.run_id)
            if refreshed.status == RunStatus.PAUSED or exit_reason == EXIT_INTERRUPTED:
                return
            if refreshed.step_status.get(step_id) == StepStatus.COMPLETED:
                continue
            fix_attempts_by_step[step_id] = fix_attempts_by_step.get(step_id, 0) + 1
            refreshed.add_event(
                "execute_step_attempt_failed",
                step_id=step_id,
                attempt=fix_attempts_by_step[step_id],
                exit_reason=exit_reason,
            )
            self.store.save_run(refreshed)
            if fix_attempts_by_step[step_id] >= MAX_FIX_ATTEMPTS:
                if exit_reason == EXIT_MAX_AGENT_TOOL_ROUNDS_EXCEEDED:
                    self.store.mark_failed(
                        refreshed,
                        f"execute exceeded agent tool rounds before submitting step: {step_id}",
                    )
                else:
                    self.store.mark_failed(refreshed, f"execute did not submit current step: {step_id}")
                return

    async def _run_test(self, run: MultiAgentRun, main_messages: list[dict[str, Any]]) -> None:
        run.execute_test_attempts += 1
        self.store.save_run(run)
        await self._run_agent(role=AgentRole.TEST, run=run, main_messages=main_messages)
        refreshed = self._load_or_raise(run.run_id)
        if refreshed.status == RunStatus.TESTING and refreshed.execute_test_attempts >= MAX_FIX_ATTEMPTS:
            self.store.mark_failed(refreshed, "test did not approve or report a concrete failure")

    async def _run_execute_review(self, run: MultiAgentRun, main_messages: list[dict[str, Any]]) -> None:
        run.execute_review_attempts += 1
        self.store.save_run(run)
        await self._run_agent(role=AgentRole.EXECUTE_REVIEW, run=run, main_messages=main_messages)
        refreshed = self._load_or_raise(run.run_id)
        if refreshed.status == RunStatus.EXECUTE_REVIEW and refreshed.execute_review_attempts >= MAX_FIX_ATTEMPTS:
            self.store.mark_failed(refreshed, "execute_review did not approve or reject execution")

    async def _run_agent(
        self,
        *,
        role: AgentRole,
        run: MultiAgentRun,
        main_messages: list[dict[str, Any]],
        task_id: str = "",
    ) -> str:
        messages, resumed_run = build_or_resume_subagent_messages(
            role=role,
            run=self._load_or_raise(run.run_id),
            main_messages=main_messages,
            task_id=task_id,
        )
        message_key = message_key_for_role(role, resumed_run, task_id=task_id)
        resumed_run.subagent_messages[message_key] = list(messages)
        self.store.save_run(resumed_run)
        tools = llm_client.format_openai_tools(schemas_for_role(role=role, registry=self.registry, store=self.store))
        failure_tracker = RepeatedFailureTracker()
        max_rounds = agent_round_limit()
        tool_calls_used = 0
        self._record_agent_budget(
            run_id=run.run_id,
            role=role,
            task_id=task_id,
            limit=max_rounds,
            rounds_used=0,
            tool_calls_used=0,
            exit_reason="",
        )
        for round_index in range(max_rounds):
            if self._cancelled():
                self._persist_agent_messages(run.run_id, role, messages, task_id=task_id)
                self._pause_run(self._load_or_raise(run.run_id))
                return EXIT_INTERRUPTED
            self._record_agent_budget(
                run_id=run.run_id,
                role=role,
                task_id=task_id,
                limit=max_rounds,
                rounds_used=round_index,
                tool_calls_used=tool_calls_used,
                event_kind="agent_round_started",
            )
            request_messages = self._messages_with_round_budget(
                role=role,
                run_id=run.run_id,
                messages=messages,
                task_id=task_id,
            )
            stream_kwargs = {"cancel_event": self.cancel_event} if self.cancel_event is not None else {}
            stream_result = normalize_stream_result(
                await stream_one_round(
                    self.api_client,
                    self.model,
                    request_messages,
                    tools,
                    display=True,
                    output_label=f"{role.value}",
                    **stream_kwargs,
                )
            )
            assistant_text = stream_result.text
            tool_calls = stream_result.tool_calls
            messages.append(assistant_message(assistant_text, tool_calls))
            if stream_result.interrupted:
                messages.append(
                    {
                        "role": "assistant",
                        "content": "本轮子智能体已被用户中断，进度已保存。",
                        "metadata": {"interrupted": True},
                    }
                )
                self._persist_agent_messages(run.run_id, role, messages, task_id=task_id)
                self._pause_run(self._load_or_raise(run.run_id))
                return EXIT_INTERRUPTED
            if assistant_text:
                current = self._load_or_raise(run.run_id)
                current.subagent_final_answers[message_key_for_role(role, current, task_id=task_id)] = assistant_text
                self.store.save_run(current)
            if not tool_calls:
                self._record_agent_budget(
                    run_id=run.run_id,
                    role=role,
                    task_id=task_id,
                    limit=max_rounds,
                    rounds_used=round_index + 1,
                    tool_calls_used=tool_calls_used,
                    exit_reason=EXIT_NO_TOOL_CALLS,
                )
                self._persist_agent_messages(run.run_id, role, messages, task_id=task_id)
                return EXIT_NO_TOOL_CALLS
            tool_calls_used += len(tool_calls)
            for index, tool_call in enumerate(tool_calls):
                call_id = tool_call.tool_id or f"{role.value}_tool_call_{index}"
                selected_tool = self.registry.get(tool_call.tool_name)
                is_mutation = selected_tool is not None and not selected_tool.is_read_only
                blocked = failure_tracker.preflight(
                    tool_call.tool_name,
                    tool_call.arguments,
                    is_mutation=is_mutation,
                )
                if blocked is not None:
                    execution = blocked
                elif self._cancelled():
                    execution = ToolExecution("因用户中断，本工具调用未执行。", is_error=True)
                else:
                    execution = await self._execute_subagent_tool_queued(
                        role=role,
                        run_id=run.run_id,
                        tool_call_id=call_id,
                        tool_name=tool_call.tool_name,
                        raw_args=tool_call.arguments,
                        active_task_id=task_id,
                        main_messages=main_messages,
                    )
                execution = failure_tracker.annotate(
                    tool_call.tool_name,
                    tool_call.arguments,
                    execution,
                    is_mutation=is_mutation,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": execution.output,
                        "metadata": {"is_error": execution.is_error},
                    }
                )
            self._persist_agent_messages(run.run_id, role, messages, task_id=task_id)
            if self._cancelled():
                self._pause_run(self._load_or_raise(run.run_id))
                return EXIT_INTERRUPTED
            refreshed = self._load_or_raise(run.run_id)
            if role in {AgentRole.EXECUTE, AgentRole.TEST}:
                task = refreshed.scheduled_tasks.get(task_id, {})
                task_status = _task_status(task.get("status"))
                if task_status in ROLE_TERMINAL_STATUSES[role]:
                    self._record_agent_budget(
                        run_id=run.run_id,
                        role=role,
                        task_id=task_id,
                        limit=max_rounds,
                        rounds_used=round_index + 1,
                        tool_calls_used=tool_calls_used,
                        exit_reason=EXIT_PHASE_CHANGED,
                    )
                    return EXIT_PHASE_CHANGED
            if _phase_changed(role, refreshed.status):
                self._record_agent_budget(
                    run_id=run.run_id,
                    role=role,
                    task_id=task_id,
                    limit=max_rounds,
                    rounds_used=round_index + 1,
                    tool_calls_used=tool_calls_used,
                    exit_reason=EXIT_PHASE_CHANGED,
                )
                return EXIT_PHASE_CHANGED
        self._persist_agent_messages(run.run_id, role, messages, task_id=task_id)
        self._record_agent_budget(
            run_id=run.run_id,
            role=role,
            task_id=task_id,
            limit=max_rounds,
            rounds_used=max_rounds,
            tool_calls_used=tool_calls_used,
            exit_reason=EXIT_MAX_AGENT_TOOL_ROUNDS_EXCEEDED,
            event_kind="agent_round_limit_reached",
        )
        return EXIT_MAX_AGENT_TOOL_ROUNDS_EXCEEDED

    async def _execute_subagent_tool_queued(
        self,
        *,
        role: AgentRole,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        raw_args: str,
        active_task_id: str = "",
        main_messages: list[dict[str, Any]] | None = None,
    ) -> ToolExecution:
        if role == AgentRole.SCHEDULING and tool_name == "DispatchTasks":
            execution = await self._execute_subagent_tool(
                role=role,
                run_id=run_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                raw_args=raw_args,
                active_task_id=active_task_id,
            )
            try:
                payload = json.loads(execution.output)
            except json.JSONDecodeError:
                return execution
            task_ids = {
                str(task.get("task_id", ""))
                for task in payload.get("tasks", [])
                if str(task.get("task_id", "")).strip()
            }
            if payload.get("status") == "queued" and task_ids:
                await self._process_scheduled_tasks(
                    self._load_or_raise(run_id),
                    main_messages or [],
                    batch_task_ids=task_ids,
                )
                return ToolExecution(self._scheduled_task_result(run_id, task_ids))
            return execution
        if role in {AgentRole.EXECUTE, AgentRole.TEST}:
            async with self._operation_lock:
                return await self._execute_subagent_tool(
                    role=role,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    raw_args=raw_args,
                    active_task_id=active_task_id,
                )
        return await self._execute_subagent_tool(
            role=role,
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            raw_args=raw_args,
            active_task_id=active_task_id,
        )

    async def _execute_subagent_tool(
        self,
        *,
        role: AgentRole,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        raw_args: str,
        active_task_id: str = "",
    ) -> ToolExecution:
        args, parse_error = parse_tool_arguments_object(raw_args)
        if parse_error:
            return ToolExecution(parse_error, is_error=True)
        control = {tool.name: tool for tool in control_tools_for_role(self.store, role)}.get(tool_name)
        tool = control or self.registry.get(tool_name)
        if tool is None:
            return ToolExecution(f"Error: unknown tool {tool_name}", is_error=True)
        task_id = ""
        if role == AgentRole.EXECUTE and control is None:
            task_error = self._validate_execute_task(run_id, args, active_task_id=active_task_id)
            if task_error:
                return ToolExecution(task_error, is_error=True)
            task_id = str(args.get("task_id", "")).strip()
        exec_args = dict(args)
        declared_write_files: list[str] = []
        if role == AgentRole.EXECUTE and control is None:
            exec_args.pop("task_id", None)
            declared_write_files = [
                str(item)
                for item in exec_args.pop("declared_write_files", []) or []
                if str(item).strip()
            ]
            exec_args.pop("step_id", None)
        if role == AgentRole.EXECUTE and control is None:
            coordinated = await self._execute_with_file_coordination(
                run_id=run_id,
                task_id=task_id,
                tool_name=tool_name,
                tool=tool,
                args=exec_args,
                declared_write_files=declared_write_files,
            )
            if coordinated is not None:
                execution = coordinated
                return self._store_tool_output(
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=json.dumps(args, ensure_ascii=False, sort_keys=True),
                    execution=execution,
                )
        execution = await self._execute_runtime_tool(tool, exec_args)
        if control is not None:
            return execution
        return self._store_tool_output(
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=json.dumps(args, ensure_ascii=False, sort_keys=True),
            execution=execution,
        )

    async def _execute_with_file_coordination(
        self,
        *,
        run_id: str,
        task_id: str,
        tool_name: str,
        tool: Any,
        args: dict[str, Any],
        declared_write_files: list[str],
    ) -> ToolExecution | None:
        run = self._load_or_raise(run_id)
        if tool_name == "ReadFile":
            execution = await self._execute_runtime_tool(tool, args)
            if not execution.is_error:
                self.file_coordinator.record_read(run, task_id=task_id, raw_path=str(args.get("file_path", "")))
                self.store.save_run(run)
            return execution
        if tool_name in {"WriteFile", "EditFile"}:
            ok, file_key, error = self.file_coordinator.before_write(
                run,
                task_id=task_id,
                raw_path=str(args.get("file_path", "")),
            )
            self.store.save_run(run)
            if not ok:
                return ToolExecution(error, is_error=True)
            execution = await self._execute_runtime_tool(tool, args)
            success = not execution.is_error
            run = self._load_or_raise(run_id)
            self.file_coordinator.after_write(run, task_id=task_id, file_key=file_key, success=success)
            self.store.save_run(run)
            return execution
        if tool_name == "Bash":
            ok, file_keys, error = self.file_coordinator.before_bash(
                run,
                task_id=task_id,
                raw_paths=declared_write_files,
            )
            self.store.save_run(run)
            if not ok:
                return ToolExecution(error, is_error=True)
            before = self.file_coordinator.snapshot_workspace()
            execution = await self._execute_runtime_tool(tool, args)
            after = self.file_coordinator.snapshot_workspace()
            run = self._load_or_raise(run_id)
            ok, coordination_error, changed = self.file_coordinator.after_bash(
                run,
                task_id=task_id,
                declared_file_keys=file_keys,
                before_snapshot=before,
                after_snapshot=after,
            )
            task = run.scheduled_tasks.get(task_id, {})
            if changed:
                existing = set(task.get("changed_files", []))
                task["changed_files"] = sorted(existing | set(changed))
            self.store.save_run(run)
            if not ok:
                return ToolExecution(coordination_error, is_error=True)
            return execution
        return None

    async def _execute_runtime_tool(self, tool: Any, args: dict[str, Any]) -> ToolExecution:
        session_id = ""
        recorder = None
        if self.memory_runtime is not None and hasattr(self.memory_runtime, "start_execution_record"):
            recorder = self.memory_runtime
            session_id = self.memory_runtime.get_current_session_id() or ""
        return await execute_tool(
            tool,
            args,
            cancel_event=self.cancel_event,
            execution_recorder=recorder,
            session_id=session_id,
        )

    def _validate_execute_task(self, run_id: str, args: dict[str, Any], *, active_task_id: str = "") -> str:
        run = self._load_or_raise(run_id)
        task_id = str(args.get("task_id") or args.get("step_id") or "").strip()
        if not task_id:
            return "Error: execute tool calls must include task_id."
        expected = active_task_id or run.current_step_id
        if expected and task_id != expected:
            return f"Error: execute task gating rejected task_id {task_id}; current task_id is {expected}."
        return ""

    def _validate_execute_step(self, run_id: str, args: dict[str, Any]) -> str:
        return self._validate_execute_task(run_id, args)

    def _scheduled_task_result(self, run_id: str, task_ids: set[str]) -> str:
        run = self._load_or_raise(run_id)
        tasks: list[dict[str, Any]] = []
        for task_id in sorted(task_ids):
            task = run.scheduled_tasks.get(task_id, {})
            tasks.append(
                {
                    key: value
                    for key, value in {
                        "task_id": task_id,
                        "status": task.get("status", "unknown"),
                        "summary": task.get("summary", ""),
                        "changed_files": task.get("changed_files", []),
                        "reason": task.get("reason", ""),
                        "failure_type": task.get("failure_type", ""),
                        "required_fixes": task.get("required_fixes", []),
                        "test_evidence": task.get("test_evidence", ""),
                        "last_test_message": task.get("last_test_message", ""),
                        "last_tool_summary": task.get("last_tool_summary", ""),
                        "test_attempts": task.get("test_attempts", 0),
                    }.items()
                    if value not in ("", [], None) or key == "test_attempts"
                }
            )
        failed = [task for task in tasks if task.get("status") in {"failed", "needs_fix"}]
        blocked = [task for task in tasks if task.get("status") in {"queued", "running", "testing"}]
        status = "failed" if failed else "blocked" if blocked else "passed"
        failed_by_test_protocol = any(task.get("failure_type") == "task_test_no_decision" for task in failed)
        return json.dumps(
            {
                "status": status,
                "tasks": tasks,
                "next_action": (
                    "Do not repeat broad dispatch. Inspect the task_test_no_decision details, then dispatch one focused verification/repair task or request intervention."
                    if failed_by_test_protocol
                    else "Dispatch focused repair tasks for failed items."
                    if failed
                    else "Resolve dependencies or dispatch a narrower task batch."
                    if blocked
                    else "Call SubmitFinalTest when all scheduled work is complete."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    def _append_test_decision_required(
        self,
        run: MultiAgentRun,
        *,
        task_id: str,
        observation: dict[str, str],
    ) -> None:
        payload = {
            "status": "decision_required",
            "task_id": task_id,
            "reason": "The previous test turn inspected evidence but did not call ApproveTaskTest or ReportTaskFailure.",
            "required_action": "Call ApproveTaskTest if the task passes; otherwise call ReportTaskFailure. Do not use more tools unless the visible evidence is insufficient.",
            "last_test_message": observation["last_assistant_message"],
            "last_tool_summary": observation["last_tool_summary"],
        }
        run.feedback_events.setdefault(AgentRole.TEST.value, []).append(
            {
                "event_id": uuid4().hex,
                "source_agent": "runtime",
                "tool_name": "RuntimeTestDecisionRequired",
                "target_agent": AgentRole.TEST.value,
                "payload": payload,
                "created_at": time(),
                "delivered": False,
            }
        )
        run.add_event("task_test_decision_retry", task_id=task_id)

    def _last_agent_observation(self, run: MultiAgentRun, role: AgentRole, *, task_id: str = "") -> dict[str, str]:
        message_key = message_key_for_role(role, run, task_id=task_id)
        messages = run.subagent_messages.get(message_key, [])
        last_assistant = ""
        last_tool = ""
        for message in reversed(messages):
            if not last_tool and message.get("role") == "tool":
                if not str(message.get("tool_call_id", "")).startswith("feedback_"):
                    last_tool = str(message.get("content", ""))
            if not last_assistant and message.get("role") == "assistant":
                if message.get("content"):
                    last_assistant = str(message.get("content", ""))
                elif message.get("tool_calls"):
                    tool_names = [
                        str(call.get("function", {}).get("name", ""))
                        for call in message.get("tool_calls", [])
                        if isinstance(call, dict)
                    ]
                    last_assistant = "tool_calls: " + ", ".join(name for name in tool_names if name)
            if last_tool and last_assistant:
                break
        return {
            "last_assistant_message": _compact_text(last_assistant),
            "last_tool_summary": _compact_text(last_tool),
        }

    def _store_tool_output(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: str,
        execution: ToolExecution,
    ) -> ToolExecution:
        run = self._load_or_raise(run_id)
        run.add_event("tool_output", tool_name=tool_name)
        self.store.save_run(run)
        if self.memory_runtime is None:
            return ToolExecution(_preview_without_memory(execution.output), execution.is_error)
        session_id = self.memory_runtime.get_current_session_id() or self.memory_runtime.start_session(self.model)
        context_id = self.memory_runtime.save_tool_output(
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            output=execution.output,
            metadata={
                "intent": f"multiAgent {tool_name}",
                "multi_agent_run_id": run_id,
                "is_error": execution.is_error,
            },
        )
        if len(execution.output) <= CONFIG.memory.raw_tool_output_preview_chars:
            return execution
        preview = self.memory_runtime.tool_output_prompt_content(
            output_id=context_id,
            output=execution.output,
            messages=[],
            tools=[],
            current_prompt="",
        )
        return ToolExecution(preview, execution.is_error)

    def _persist_agent_messages(
        self,
        run_id: str,
        role: AgentRole,
        messages: list[dict[str, Any]],
        *,
        task_id: str = "",
    ) -> None:
        run = self._load_or_raise(run_id)
        message_key = message_key_for_role(role, run, task_id=task_id)
        self.store.set_agent_messages(run_id, message_key, list(messages))

    def _record_agent_budget(
        self,
        *,
        run_id: str,
        role: AgentRole,
        task_id: str = "",
        limit: int,
        rounds_used: int,
        tool_calls_used: int,
        exit_reason: str = "",
        event_kind: str = "",
    ) -> None:
        run = self._load_or_raise(run_id)
        role_key = f"{role.value}:{task_id}" if task_id and role in {AgentRole.EXECUTE, AgentRole.TEST} else role.value
        run.subagent_round_limits[role_key] = limit
        run.subagent_rounds_used[role_key] = rounds_used
        run.subagent_tool_calls_used[role_key] = tool_calls_used
        if exit_reason:
            run.subagent_exit_reasons[role_key] = exit_reason
        if event_kind:
            run.add_event(
                event_kind,
                role=role_key,
                step_id=task_id or (run.current_step_id if role == AgentRole.EXECUTE else ""),
                round_used=rounds_used,
                rounds_remaining=max(0, limit - rounds_used),
                tool_call_count=tool_calls_used,
            )
        self.store.save_run(run)

    def _messages_with_round_budget(
        self,
        *,
        role: AgentRole,
        run_id: str,
        messages: list[dict[str, Any]],
        task_id: str = "",
    ) -> list[dict[str, Any]]:
        if role != AgentRole.EXECUTE:
            return messages
        run = self._load_or_raise(run_id)
        return [
            *messages,
            {
                "role": "user",
                "content": "[Runtime round budget]\n"
                + json.dumps(execute_round_budget(run, task_id=task_id), ensure_ascii=False, indent=2),
            },
        ]

    def _load_or_raise(self, run_id: str) -> MultiAgentRun:
        run = self.store.load_run(run_id)
        if run is None:
            raise ValueError(f"multi-agent run not found: {run_id}")
        return run

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def _pause_run(self, run: MultiAgentRun) -> MultiAgentRun:
        if run.status in TERMINAL_STATUSES or run.status == RunStatus.PAUSED:
            return run
        run.resume_status = run.status
        run.status = RunStatus.PAUSED
        for task in run.scheduled_tasks.values():
            if _task_status(task.get("status")) in {TaskStatus.RUNNING, TaskStatus.TESTING}:
                task["status"] = TaskStatus.QUEUED.value
                task["updated_at"] = _now()
        run.add_event("paused", reason="user_interrupted")
        self.store.save_run(run)
        return run


def _phase_changed(role: AgentRole, status: RunStatus) -> bool:
    if role == AgentRole.PLAN:
        return status != RunStatus.PLANNING
    if role == AgentRole.PLAN_REVIEW:
        return status != RunStatus.PLAN_REVIEW
    if role == AgentRole.SCHEDULING:
        return status != RunStatus.SCHEDULING
    if role == AgentRole.EXECUTE:
        return status not in {RunStatus.SCHEDULING, RunStatus.EXECUTING}
    if role == AgentRole.TEST:
        return status not in {RunStatus.SCHEDULING, RunStatus.TESTING}
    if role == AgentRole.FINAL_TEST:
        return status != RunStatus.FINAL_TESTING
    if role == AgentRole.EXECUTE_REVIEW:
        return status != RunStatus.EXECUTE_REVIEW
    return False


def _task_status(value: Any) -> TaskStatus | None:
    try:
        return TaskStatus(str(value))
    except ValueError:
        return None


def _compact_text(text: str, *, limit: int = 1200) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-(limit // 2) :]
    omitted = len(text) - len(head) - len(tail)
    return f"{head}\n[... {omitted} chars omitted ...]\n{tail}"


def _preview_without_memory(output: str) -> str:
    if len(output) <= 1000:
        return output
    head = output[:500]
    tail = output[-500:]
    omitted = len(output) - len(head) - len(tail)
    return f"{head}\n[... {omitted} chars omitted; full output unavailable without memory runtime ...]\n{tail}"
