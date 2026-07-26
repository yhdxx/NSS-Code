from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any
from uuid import uuid4


class AgentRole(str, Enum):
    PLAN = "plan"
    PLAN_REVIEW = "plan_review"
    EXECUTE = "execute"
    TEST = "test"
    EXECUTE_REVIEW = "execute_review"


class RunStatus(str, Enum):
    PLANNING = "planning"
    PLAN_REVIEW = "plan_review"
    EXECUTING = "executing"
    TESTING = "testing"
    EXECUTE_REVIEW = "execute_review"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    NEEDS_FIX = "needs_fix"


TERMINAL_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED}


@dataclass
class PlanNode:
    step_id: str
    title: str
    goal: str
    acceptance: str
    files: list[str] = field(default_factory=list)
    children: list["PlanNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "goal": self.goal,
            "acceptance": self.acceptance,
            "files": list(self.files),
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanNode":
        return cls(
            step_id=str(payload.get("step_id", "")),
            title=str(payload.get("title", "")),
            goal=str(payload.get("goal", "")),
            acceptance=str(payload.get("acceptance", "")),
            files=[str(item) for item in payload.get("files", []) if str(item).strip()],
            children=[
                cls.from_dict(child)
                for child in payload.get("children", [])
                if isinstance(child, dict)
            ],
        )


@dataclass
class MultiAgentRun:
    run_id: str
    task: str
    source_request_ref: str
    source_request_preview: str
    status: RunStatus = RunStatus.PLANNING
    title: str = ""
    plan_summary: str = ""
    submitted_plan: list[PlanNode] = field(default_factory=list)
    approved_plan: list[PlanNode] = field(default_factory=list)
    current_step_id: str = ""
    step_status: dict[str, StepStatus] = field(default_factory=dict)
    step_submissions: dict[str, dict[str, Any]] = field(default_factory=dict)
    plan_rejections: list[dict[str, Any]] = field(default_factory=list)
    test_result: dict[str, Any] = field(default_factory=dict)
    review_result: dict[str, Any] = field(default_factory=dict)
    subagent_messages: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    subagent_final_answers: dict[str, str] = field(default_factory=dict)
    subagent_round_limits: dict[str, int] = field(default_factory=dict)
    subagent_rounds_used: dict[str, int] = field(default_factory=dict)
    subagent_tool_calls_used: dict[str, int] = field(default_factory=dict)
    subagent_exit_reasons: dict[str, str] = field(default_factory=dict)
    feedback_events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    plan_attempts: int = 0
    plan_review_attempts: int = 0
    execute_test_attempts: int = 0
    execute_review_attempts: int = 0
    error: str = ""
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)

    @classmethod
    def create(cls, *, task: str, source_request_ref: str = "", source_request_preview: str = "") -> "MultiAgentRun":
        return cls(
            run_id=uuid4().hex,
            task=task,
            source_request_ref=source_request_ref,
            source_request_preview=source_request_preview,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["submitted_plan"] = [node.to_dict() for node in self.submitted_plan]
        payload["approved_plan"] = [node.to_dict() for node in self.approved_plan]
        payload["step_status"] = {key: value.value for key, value in self.step_status.items()}
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MultiAgentRun":
        return cls(
            run_id=str(payload["run_id"]),
            task=str(payload.get("task", "")),
            source_request_ref=str(payload.get("source_request_ref", "")),
            source_request_preview=str(payload.get("source_request_preview", "")),
            status=RunStatus(str(payload.get("status", RunStatus.PLANNING.value))),
            title=str(payload.get("title", "")),
            plan_summary=str(payload.get("plan_summary", "")),
            submitted_plan=[
                PlanNode.from_dict(node)
                for node in payload.get("submitted_plan", [])
                if isinstance(node, dict)
            ],
            approved_plan=[
                PlanNode.from_dict(node)
                for node in payload.get("approved_plan", [])
                if isinstance(node, dict)
            ],
            current_step_id=str(payload.get("current_step_id", "")),
            step_status={
                str(key): StepStatus(str(value))
                for key, value in dict(payload.get("step_status", {})).items()
            },
            step_submissions=dict(payload.get("step_submissions", {})),
            plan_rejections=list(payload.get("plan_rejections", [])),
            test_result=dict(payload.get("test_result", {})),
            review_result=dict(payload.get("review_result", {})),
            subagent_messages=dict(payload.get("subagent_messages", {})),
            subagent_final_answers=dict(payload.get("subagent_final_answers", {})),
            subagent_round_limits={
                str(key): int(value)
                for key, value in dict(payload.get("subagent_round_limits", {})).items()
            },
            subagent_rounds_used={
                str(key): int(value)
                for key, value in dict(payload.get("subagent_rounds_used", {})).items()
            },
            subagent_tool_calls_used={
                str(key): int(value)
                for key, value in dict(payload.get("subagent_tool_calls_used", {})).items()
            },
            subagent_exit_reasons={
                str(key): str(value)
                for key, value in dict(payload.get("subagent_exit_reasons", {})).items()
            },
            feedback_events=dict(payload.get("feedback_events", {})),
            events=list(payload.get("events", [])),
            plan_attempts=int(payload.get("plan_attempts", 0) or 0),
            plan_review_attempts=int(payload.get("plan_review_attempts", 0) or 0),
            execute_test_attempts=int(payload.get("execute_test_attempts", 0) or 0),
            execute_review_attempts=int(payload.get("execute_review_attempts", 0) or 0),
            error=str(payload.get("error", "")),
            created_at=float(payload.get("created_at", time()) or time()),
            updated_at=float(payload.get("updated_at", time()) or time()),
        )

    def add_event(self, kind: str, **payload: Any) -> None:
        self.events.append({"kind": kind, "at": time(), **payload})
        self.updated_at = time()


def flatten_plan(nodes: list[PlanNode]) -> list[PlanNode]:
    result: list[PlanNode] = []
    for node in nodes:
        result.append(node)
        result.extend(flatten_plan(node.children))
    return result


def executable_steps(nodes: list[PlanNode]) -> list[PlanNode]:
    result: list[PlanNode] = []
    for node in nodes:
        if node.children:
            result.extend(executable_steps(node.children))
        else:
            result.append(node)
    return result


def plan_to_compact_text(nodes: list[PlanNode]) -> str:
    lines: list[str] = []
    for node in flatten_plan(nodes):
        lines.append(
            f"{node.step_id}. {node.title}\n"
            f"Goal: {node.goal}\n"
            f"Acceptance: {node.acceptance}\n"
            f"Files: {', '.join(node.files) if node.files else '(none)'}"
        )
    return "\n\n".join(lines)
