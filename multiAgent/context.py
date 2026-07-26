from __future__ import annotations

import copy
import json
from pathlib import Path
from time import time
from typing import Any

from mycodingagent.configuration import CONFIG
from multiAgent.models import AgentRole, MultiAgentRun, executable_steps


PROMPT_ROOT = Path(__file__).resolve().parent / "prompts"


def build_subagent_messages(
    *,
    role: AgentRole,
    run: MultiAgentRun,
    main_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": load_system_prompt(role)},
        {"role": "user", "content": build_role_context(role=role, run=run, main_messages=main_messages)},
    ]


def build_or_resume_subagent_messages(
    *,
    role: AgentRole,
    run: MultiAgentRun,
    main_messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], MultiAgentRun]:
    previous = run.subagent_messages.get(role.value)
    if previous:
        messages = copy.deepcopy(previous)
        messages.append(
            {
                "role": "user",
                "content": "[Runtime state update]\n"
                + build_role_context(role=role, run=run, main_messages=main_messages),
            }
        )
    else:
        messages = build_subagent_messages(role=role, run=run, main_messages=main_messages)
    messages = append_pending_feedback_messages(role=role, run=run, messages=messages)
    return messages, run


def append_pending_feedback_messages(
    *,
    role: AgentRole,
    run: MultiAgentRun,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events = run.feedback_events.get(role.value, [])
    for event in events:
        if event.get("delivered"):
            continue
        event_id = str(event.get("event_id", ""))
        tool_name = str(event.get("tool_name", "Feedback"))
        payload = event.get("payload", {})
        call_id = f"feedback_{event_id}" if event_id else f"feedback_{tool_name}_{len(messages)}"
        arguments = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        messages.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": arguments,
                        },
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        )
        event["delivered"] = True
        event["delivered_at"] = time()
    return messages


def load_system_prompt(role: AgentRole) -> str:
    path = PROMPT_ROOT / role.value / "SYSTEM.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return f"You are the {role.value} sub-agent in a multi-agent coding workflow."


def build_role_context(
    *,
    role: AgentRole,
    run: MultiAgentRun,
    main_messages: list[dict[str, Any]],
) -> str:
    if role == AgentRole.PLAN:
        return _plan_context(run, main_messages)
    if role == AgentRole.PLAN_REVIEW:
        return _plan_review_context(run)
    if role == AgentRole.EXECUTE:
        return _execute_context(run)
    if role == AgentRole.TEST:
        return _test_context(run)
    if role == AgentRole.EXECUTE_REVIEW:
        return _execute_review_context(run)
    return json.dumps({"run_id": run.run_id}, ensure_ascii=False, indent=2)


def _plan_context(run: MultiAgentRun, main_messages: list[dict[str, Any]]) -> str:
    payload = {
        "run_id": run.run_id,
        "task": run.task,
        "recent_main_conversation": recent_text_turns(main_messages, limit=8),
        "plan_rejections": run.plan_rejections[-3:],
        "required_action": "Call SubmitPlan with a structured plan. Do not modify files.",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _plan_review_context(run: MultiAgentRun) -> str:
    payload = {
        "run_id": run.run_id,
        "submitted_plan": [node.to_dict() for node in run.submitted_plan],
        "source_request_provenance": {
            "source_request_ref": run.source_request_ref,
            "preview_for_coverage_review_only": run.source_request_preview,
        },
        "required_action": "Call ApprovePlan or RejectPlan. Do not execute the plan.",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _execute_context(run: MultiAgentRun) -> str:
    budget = execute_round_budget(run)
    payload = {
        "run_id": run.run_id,
        "approved_plan": [node.to_dict() for node in run.approved_plan],
        "current_step_id": run.current_step_id,
        "completed_steps": sorted(run.step_submissions),
        "step_status": {key: str(value.value) for key, value in run.step_status.items()},
        "agent_round_limit": budget["agent_round_limit"],
        "agent_rounds_used": budget["agent_rounds_used"],
        "agent_rounds_remaining": budget["agent_rounds_remaining"],
        "tool_calls_used_in_step": budget["tool_calls_used_in_step"],
        "round_budget_warning": budget["round_budget_warning"],
        "plan_review_approval": run.review_result.get("plan_review") or run.review_result,
        "test_feedback": run.test_result if run.test_result.get("status") == "failed" else {},
        "execute_review_feedback": run.review_result if run.review_result.get("status") == "rejected" else {},
        "execution_authority": "Only the approved_plan is authoritative. Do not reinterpret the original user request.",
        "required_action": (
            "Use ordinary tools only for current_step_id, then call SubmitSubAgentStep for that step."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def execute_round_budget(run: MultiAgentRun) -> dict[str, Any]:
    role = AgentRole.EXECUTE.value
    limit = int(run.subagent_round_limits.get(role) or CONFIG.multi_agent.max_agent_rounds)
    used = max(0, int(run.subagent_rounds_used.get(role, 0)))
    remaining = max(0, limit - used)
    warning = ""
    if remaining <= 5:
        warning = (
            "Round budget is nearly exhausted. If current_step_id acceptance is satisfied, "
            "call SubmitSubAgentStep now; otherwise use the fewest possible tools to finish verification."
        )
    return {
        "agent_round_limit": limit,
        "agent_rounds_used": used,
        "agent_rounds_remaining": remaining,
        "tool_calls_used_in_step": max(0, int(run.subagent_tool_calls_used.get(role, 0))),
        "round_budget_warning": warning,
    }


def _test_context(run: MultiAgentRun) -> str:
    payload = {
        "run_id": run.run_id,
        "approved_plan": [node.to_dict() for node in run.approved_plan],
        "step_submissions": run.step_submissions,
        "execute_final_answer": run.subagent_final_answers.get(AgentRole.EXECUTE.value, ""),
        "required_action": "Validate acceptance criteria. Call ApproveTest or ReportTestFailure.",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _execute_review_context(run: MultiAgentRun) -> str:
    payload = {
        "run_id": run.run_id,
        "approved_plan": [node.to_dict() for node in run.approved_plan],
        "step_submissions": run.step_submissions,
        "test_result": run.test_result,
        "execute_final_answer": run.subagent_final_answers.get(AgentRole.EXECUTE.value, ""),
        "required_action": "Review quality and completeness. Call ApproveExecution or RejectExecution.",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def recent_text_turns(messages: list[dict[str, Any]], *, limit: int = 8, max_chars: int = 8000) -> str:
    text_messages = [
        message
        for message in messages
        if message.get("role") in {"user", "assistant"} and str(message.get("content", "")).strip()
    ][-limit:]
    lines: list[str] = []
    for message in text_messages:
        role = str(message.get("role", ""))
        content = str(message.get("content", "")).strip()
        if "tool_calls" in message:
            content += "\n[assistant tool calls omitted]"
        lines.append(f"{role.upper()}:\n{content}")
    text = "\n\n".join(lines)
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def run_summary_for_main_context(run: MultiAgentRun) -> str:
    payload = {
        "run_id": run.run_id,
        "status": run.status.value,
        "plan_summary": run.plan_summary,
        "test_result": run.test_result,
        "execute_review_result": run.review_result,
        "inspect_tool": "InspectSubAgentWork",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def next_open_step(run: MultiAgentRun) -> str:
    for step in executable_steps(run.approved_plan):
        status = run.step_status.get(step.step_id)
        if status is None or status.value in {"pending", "needs_fix"}:
            return step.step_id
    return ""
