from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from mycodingagent.configuration import CONFIG
from mycodingagent.llm_runtime import client as llm_client
from mycodingagent.llm_runtime.client import PendingToolCall, stream_one_round
from mycodingagent.tool_runtime import ToolRegistry

from multiAgent.context import (
    build_or_resume_subagent_messages,
    execute_round_budget,
    next_open_step,
    run_summary_for_main_context,
)
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
        resumed_run.subagent_messages[role.value] = list(messages)
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
                current.subagent_final_answers[role.value] = assistant_text
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
        if role == AgentRole.EXECUTE and tool_name not in {tool.name for tool in control_tools_for_role(self.store, role)}:
            step_error = self._validate_execute_step(run_id, args)
            if step_error:
                return step_error
        control = {tool.name: tool for tool in control_tools_for_role(self.store, role)}.get(tool_name)
        tool = control or self.registry.get(tool_name)
        if tool is None:
            return f"Error: unknown tool {tool_name}"
        try:
            params = tool.params_model.model_validate(args)
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

    def _validate_execute_step(self, run_id: str, args: dict[str, Any]) -> str:
        run = self._load_or_raise(run_id)
        step_id = str(args.get("step_id", "")).strip()
        if not step_id:
            return "Error: execute tool calls must include step_id."
        if step_id != run.current_step_id:
            return f"Error: execute step gating rejected step_id {step_id}; current_step_id is {run.current_step_id}."
        return ""

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
        run.subagent_messages[role.value] = list(messages)
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
    if role == AgentRole.EXECUTE:
        return status != RunStatus.EXECUTING
    if role == AgentRole.TEST:
        return status != RunStatus.TESTING
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
