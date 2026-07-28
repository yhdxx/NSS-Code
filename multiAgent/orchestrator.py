from __future__ import annotations

import json
from time import time
from typing import Any

from openai import AsyncOpenAI

from mycodingagent.configuration import CONFIG
from mycodingagent.llm_runtime import client as llm_client
from mycodingagent.llm_runtime.client import PendingToolCall, stream_one_round
from mycodingagent.tool_runtime import ToolRegistry

from multiAgent.context import (
    build_or_resume_subagent_messages,
    execute_round_budget,
    message_key_for_role,
    next_open_step,
    run_summary_for_main_context,
)
from multiAgent.file_coordination import FileCoordinator
from multiAgent.models import AgentRole, MultiAgentRun, RunStatus, TERMINAL_STATUSES, StepStatus
from multiAgent.store import MultiAgentStore
from multiAgent.tool_policy import schemas_for_role
from multiAgent.tools import control_tools_for_role


MAX_WORKFLOW_CYCLES = 30
MAX_PLAN_REVIEW_ATTEMPTS = 3
MAX_FIX_ATTEMPTS = 3

EXIT_PHASE_CHANGED = "phase_changed"
EXIT_NO_TOOL_CALLS = "no_tool_calls"
EXIT_MAX_AGENT_TOOL_ROUNDS_EXCEEDED = "max_agent_tool_rounds_exceeded"


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
    ) -> None:
        self.store = store
        self.registry = registry
        self.api_client = api_client
        self.memory_runtime = memory_runtime
        self.model = model or llm_client.MODEL
        self.file_coordinator = FileCoordinator()

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
        return await self.run(run_id=run_id, main_messages=main_messages)

    async def run(self, *, run_id: str, main_messages: list[dict[str, Any]]) -> MultiAgentRun:
        for _ in range(MAX_WORKFLOW_CYCLES):
            run = self._load_or_raise(run_id)
            if run.status in TERMINAL_STATUSES:
                return run
            if run.status == RunStatus.PLANNING:
                await self._run_plan(run, main_messages)
                continue
            if run.status == RunStatus.PLAN_REVIEW:
                await self._run_plan_review(run, main_messages)
                continue
            if run.status == RunStatus.SCHEDULING:
                await self._run_scheduling(run, main_messages)
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

    async def _run_plan(self, run: MultiAgentRun, main_messages: list[dict[str, Any]]) -> None:
        run.plan_attempts += 1
        self.store.save_run(run)
        await self._run_agent(role=AgentRole.PLAN, run=run, main_messages=main_messages)
        refreshed = self._load_or_raise(run.run_id)
        if refreshed.status == RunStatus.PLANNING and refreshed.plan_attempts >= MAX_PLAN_REVIEW_ATTEMPTS:
            self.store.mark_failed(refreshed, "plan did not submit a valid structured plan")

    async def _run_plan_review(self, run: MultiAgentRun, main_messages: list[dict[str, Any]]) -> None:
        run.plan_review_attempts += 1
        self.store.save_run(run)
        await self._run_agent(role=AgentRole.PLAN_REVIEW, run=run, main_messages=main_messages)
        refreshed = self._load_or_raise(run.run_id)
        if refreshed.status == RunStatus.PLAN_REVIEW and refreshed.plan_review_attempts >= MAX_PLAN_REVIEW_ATTEMPTS:
            self.store.mark_failed(refreshed, "plan_review did not approve or reject the plan")

    async def _run_scheduling(self, run: MultiAgentRun, main_messages: list[dict[str, Any]]) -> None:
        run.scheduling_attempts += 1
        self.store.save_run(run)
        await self._run_agent(role=AgentRole.SCHEDULING, run=run, main_messages=main_messages)
        refreshed = self._load_or_raise(run.run_id)
        if refreshed.status != RunStatus.SCHEDULING:
            return
        await self._process_scheduled_tasks(refreshed, main_messages)
        refreshed = self._load_or_raise(run.run_id)
        if (
            refreshed.status == RunStatus.SCHEDULING
            and refreshed.scheduling_attempts >= MAX_WORKFLOW_CYCLES
            and not refreshed.scheduled_tasks
        ):
            self.store.mark_failed(refreshed, "scheduling did not dispatch any task")

    async def _process_scheduled_tasks(self, run: MultiAgentRun, main_messages: list[dict[str, Any]]) -> None:
        while True:
            run = self._load_or_raise(run.run_id)
            if run.status != RunStatus.SCHEDULING:
                return
            running = [task for task in run.scheduled_tasks.values() if task.get("status") == "running"]
            capacity = max(0, int(CONFIG.multi_agent.max_parallel_tasks) - len(running))
            if capacity > 0:
                for task in run.scheduled_tasks.values():
                    if capacity <= 0:
                        break
                    if task.get("status") != "queued":
                        continue
                    deps = [str(dep) for dep in task.get("depends_on", [])]
                    if any(run.scheduled_tasks.get(dep, {}).get("status") != "passed" for dep in deps):
                        continue
                    task["status"] = "running"
                    task["updated_at"] = _now()
                    capacity -= 1
                self.store.save_run(run)
            task_id = next(
                (
                    task_id
                    for task_id, task in run.scheduled_tasks.items()
                    if task.get("status") in {"running", "needs_fix"}
                ),
                "",
            )
            if not task_id:
                return
            await self._run_task(run_id=run.run_id, task_id=task_id, main_messages=main_messages)

    async def _run_task(self, *, run_id: str, task_id: str, main_messages: list[dict[str, Any]]) -> None:
        for attempt in range(MAX_FIX_ATTEMPTS):
            run = self._load_or_raise(run_id)
            task = run.scheduled_tasks.get(task_id)
            if not task or task.get("status") == "passed":
                return
            task["status"] = "running"
            task["attempts"] = int(task.get("attempts", 0) or 0) + 1
            run.current_step_id = task_id
            self.store.save_run(run)
            exit_reason = await self._run_agent(role=AgentRole.EXECUTE, run=run, main_messages=main_messages)
            run = self._load_or_raise(run_id)
            task = run.scheduled_tasks.get(task_id, {})
            if task.get("status") != "testing":
                task["status"] = "failed"
                task["reason"] = (
                    f"execute exceeded agent tool rounds before submitting task: {task_id}"
                    if exit_reason == EXIT_MAX_AGENT_TOOL_ROUNDS_EXCEEDED
                    else f"execute did not submit current task: {task_id}"
                )
                run.current_step_id = ""
                run.add_event("task_execute_failed", task_id=task_id, reason=task["reason"])
                self.store.save_run(run)
                return
            await self._run_agent(role=AgentRole.TEST, run=run, main_messages=main_messages)
            run = self._load_or_raise(run_id)
            task = run.scheduled_tasks.get(task_id, {})
            if task.get("status") == "passed":
                run.current_step_id = ""
                self.store.save_run(run)
                return
            if task.get("status") == "needs_fix":
                continue
            task["status"] = "failed"
            task["reason"] = f"task_test did not approve or report failure for task: {task_id}"
            run.current_step_id = ""
            self.store.save_run(run)
            return
        run = self._load_or_raise(run_id)
        task = run.scheduled_tasks.get(task_id, {})
        task["status"] = "failed"
        task["reason"] = f"task exceeded fix attempts: {task_id}"
        run.current_step_id = ""
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
    ) -> str:
        messages, resumed_run = build_or_resume_subagent_messages(
            role=role,
            run=self._load_or_raise(run.run_id),
            main_messages=main_messages,
        )
        message_key = message_key_for_role(role, resumed_run)
        resumed_run.subagent_messages[message_key] = list(messages)
        self.store.save_run(resumed_run)
        tools = llm_client.format_openai_tools(schemas_for_role(role=role, registry=self.registry, store=self.store))
        seen_failures: set[tuple[str, str]] = set()
        max_rounds = agent_round_limit()
        tool_calls_used = 0
        self._record_agent_budget(
            run_id=run.run_id,
            role=role,
            limit=max_rounds,
            rounds_used=0,
            tool_calls_used=0,
            exit_reason="",
        )
        for round_index in range(max_rounds):
            self._record_agent_budget(
                run_id=run.run_id,
                role=role,
                limit=max_rounds,
                rounds_used=round_index,
                tool_calls_used=tool_calls_used,
                event_kind="agent_round_started",
            )
            request_messages = self._messages_with_round_budget(role=role, run_id=run.run_id, messages=messages)
            assistant_text, tool_calls, _usage = await stream_one_round(
                self.api_client,
                self.model,
                request_messages,
                tools,
                display=True,
                output_label=f"{role.value}",
            )
            assistant_message = _assistant_message(assistant_text, tool_calls)
            messages.append(assistant_message)
            if assistant_text:
                current = self._load_or_raise(run.run_id)
                current.subagent_final_answers[message_key_for_role(role, current)] = assistant_text
                self.store.save_run(current)
            if not tool_calls:
                self._record_agent_budget(
                    run_id=run.run_id,
                    role=role,
                    limit=max_rounds,
                    rounds_used=round_index + 1,
                    tool_calls_used=tool_calls_used,
                    exit_reason=EXIT_NO_TOOL_CALLS,
                )
                self._persist_agent_messages(run.run_id, role, messages)
                return EXIT_NO_TOOL_CALLS
            tool_calls_used += len(tool_calls)
            for index, tool_call in enumerate(tool_calls):
                call_id = tool_call.tool_id or f"{role.value}_tool_call_{index}"
                output = await self._execute_subagent_tool(
                    role=role,
                    run_id=run.run_id,
                    tool_call_id=call_id,
                    tool_name=tool_call.tool_name,
                    raw_args=tool_call.arguments,
                )
                failure_key = (tool_call.tool_name, tool_call.arguments.strip())
                if output.startswith("Tool execution error:") or output.startswith("Error:") or '"error"' in output[:300]:
                    if failure_key in seen_failures:
                        output += "\nRepeated tool failure with identical arguments. Correct the call; do not retry unchanged."
                    seen_failures.add(failure_key)
                messages.append({"role": "tool", "tool_call_id": call_id, "content": output})
            self._persist_agent_messages(run.run_id, role, messages)
            refreshed = self._load_or_raise(run.run_id)
            if role in {AgentRole.EXECUTE, AgentRole.TEST}:
                task = refreshed.scheduled_tasks.get(refreshed.current_step_id, {})
                if task.get("status") in {"testing", "passed", "needs_fix", "failed"}:
                    self._record_agent_budget(
                        run_id=run.run_id,
                        role=role,
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
                    limit=max_rounds,
                    rounds_used=round_index + 1,
                    tool_calls_used=tool_calls_used,
                    exit_reason=EXIT_PHASE_CHANGED,
                )
                return EXIT_PHASE_CHANGED
        self._persist_agent_messages(run.run_id, role, messages)
        self._record_agent_budget(
            run_id=run.run_id,
            role=role,
            limit=max_rounds,
            rounds_used=max_rounds,
            tool_calls_used=tool_calls_used,
            exit_reason=EXIT_MAX_AGENT_TOOL_ROUNDS_EXCEEDED,
            event_kind="agent_round_limit_reached",
        )
        return EXIT_MAX_AGENT_TOOL_ROUNDS_EXCEEDED

    async def _execute_subagent_tool(
        self,
        *,
        role: AgentRole,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        raw_args: str,
    ) -> str:
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError as exc:
            return f"Tool execution error: invalid JSON arguments: {exc}"
        args = args if isinstance(args, dict) else {}
        control = {tool.name: tool for tool in control_tools_for_role(self.store, role)}.get(tool_name)
        tool = control or self.registry.get(tool_name)
        if tool is None:
            return f"Error: unknown tool {tool_name}"
        task_id = ""
        if role == AgentRole.EXECUTE and control is None:
            task_error = self._validate_execute_task(run_id, args)
            if task_error:
                return task_error
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
                output = coordinated
                return self._store_tool_output(
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=json.dumps(args, ensure_ascii=False, sort_keys=True),
                    output=output,
                )
        try:
            params = tool.params_model.model_validate(exec_args)
            result = await tool.execute(params)
        except Exception as exc:
            return f"Tool execution error: {exc}"
        output = result.output
        if control is not None:
            return output
        return self._store_tool_output(
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=json.dumps(args, ensure_ascii=False, sort_keys=True),
            output=output,
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
    ) -> str | None:
        run = self._load_or_raise(run_id)
        if tool_name == "ReadFile":
            try:
                params = tool.params_model.model_validate(args)
                result = await tool.execute(params)
            except Exception as exc:
                return f"Tool execution error: {exc}"
            if not result.is_error:
                self.file_coordinator.record_read(run, task_id=task_id, raw_path=str(args.get("file_path", "")))
                self.store.save_run(run)
            return result.output
        if tool_name in {"WriteFile", "EditFile"}:
            ok, file_key, error = self.file_coordinator.before_write(
                run,
                task_id=task_id,
                raw_path=str(args.get("file_path", "")),
            )
            self.store.save_run(run)
            if not ok:
                return error
            try:
                params = tool.params_model.model_validate(args)
                result = await tool.execute(params)
                output = result.output
                success = not result.is_error
            except Exception as exc:
                output = f"Tool execution error: {exc}"
                success = False
            run = self._load_or_raise(run_id)
            self.file_coordinator.after_write(run, task_id=task_id, file_key=file_key, success=success)
            self.store.save_run(run)
            return output
        if tool_name == "Bash":
            ok, file_keys, error = self.file_coordinator.before_bash(
                run,
                task_id=task_id,
                raw_paths=declared_write_files,
            )
            self.store.save_run(run)
            if not ok:
                return error
            before = self.file_coordinator.snapshot_workspace()
            try:
                params = tool.params_model.model_validate(args)
                result = await tool.execute(params)
                output = result.output
            except Exception as exc:
                output = f"Tool execution error: {exc}"
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
                return coordination_error
            return output
        return None

    def _validate_execute_task(self, run_id: str, args: dict[str, Any]) -> str:
        run = self._load_or_raise(run_id)
        task_id = str(args.get("task_id") or args.get("step_id") or "").strip()
        if not task_id:
            return "Error: execute tool calls must include task_id."
        if task_id != run.current_step_id:
            return f"Error: execute task gating rejected task_id {task_id}; current task_id is {run.current_step_id}."
        return ""

    def _validate_execute_step(self, run_id: str, args: dict[str, Any]) -> str:
        return self._validate_execute_task(run_id, args)

    def _store_tool_output(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: str,
        output: str,
    ) -> str:
        run = self._load_or_raise(run_id)
        run.add_event("tool_output", tool_name=tool_name)
        self.store.save_run(run)
        if self.memory_runtime is None:
            return _preview_without_memory(output)
        session_id = self.memory_runtime.get_current_session_id() or self.memory_runtime.start_session(self.model)
        context_id = self.memory_runtime.save_tool_output(
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            output=output,
            metadata={"intent": f"multiAgent {tool_name}", "multi_agent_run_id": run_id},
        )
        if len(output) <= CONFIG.memory.raw_tool_output_preview_chars:
            return output
        return self.memory_runtime.tool_output_prompt_content(
            output_id=context_id,
            output=output,
            messages=[],
            tools=[],
            current_prompt="",
        )

    def _persist_agent_messages(self, run_id: str, role: AgentRole, messages: list[dict[str, Any]]) -> None:
        run = self._load_or_raise(run_id)
        run.subagent_messages[message_key_for_role(role, run)] = list(messages)
        self.store.save_run(run)

    def _record_agent_budget(
        self,
        *,
        run_id: str,
        role: AgentRole,
        limit: int,
        rounds_used: int,
        tool_calls_used: int,
        exit_reason: str = "",
        event_kind: str = "",
    ) -> None:
        run = self._load_or_raise(run_id)
        role_key = role.value
        run.subagent_round_limits[role_key] = limit
        run.subagent_rounds_used[role_key] = rounds_used
        run.subagent_tool_calls_used[role_key] = tool_calls_used
        if exit_reason:
            run.subagent_exit_reasons[role_key] = exit_reason
        if event_kind:
            run.add_event(
                event_kind,
                role=role_key,
                step_id=run.current_step_id if role == AgentRole.EXECUTE else "",
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
    ) -> list[dict[str, Any]]:
        if role != AgentRole.EXECUTE:
            return messages
        run = self._load_or_raise(run_id)
        return [
            *messages,
            {
                "role": "user",
                "content": "[Runtime round budget]\n" + json.dumps(execute_round_budget(run), ensure_ascii=False, indent=2),
            },
        ]

    def _load_or_raise(self, run_id: str) -> MultiAgentRun:
        run = self.store.load_run(run_id)
        if run is None:
            raise ValueError(f"multi-agent run not found: {run_id}")
        return run


def _assistant_message(assistant_text: str, tool_calls: list[PendingToolCall]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant"}
    if assistant_text or not tool_calls:
        message["content"] = assistant_text
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": tool_call.tool_id or f"tool_call_{index}",
                "type": "function",
                "function": {"name": tool_call.tool_name, "arguments": tool_call.arguments},
            }
            for index, tool_call in enumerate(tool_calls)
        ]
    return message


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


def _preview_without_memory(output: str) -> str:
    if len(output) <= 1000:
        return output
    head = output[:500]
    tail = output[-500:]
    omitted = len(output) - len(head) - len(tail)
    return f"{head}\n[... {omitted} chars omitted; full output unavailable without memory runtime ...]\n{tail}"
