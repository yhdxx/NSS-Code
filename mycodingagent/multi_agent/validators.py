from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mycodingagent.multi_agent.models import PlanNode, executable_steps, flatten_plan


@dataclass(frozen=True)
class PlanValidationResult:
    ok: bool
    plan: list[PlanNode] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate_plan_payload(*, title: str, summary: str, steps: Any) -> PlanValidationResult:
    errors: list[str] = []
    if not title.strip():
        errors.append("title is required")
    if not summary.strip():
        errors.append("summary is required")
    if not isinstance(steps, list) or not steps:
        errors.append("steps must be a non-empty array")
        return PlanValidationResult(ok=False, errors=errors)

    seen: set[str] = set()
    plan = _parse_level(steps, prefix="", errors=errors, seen=seen)
    if not executable_steps(plan):
        errors.append("plan must contain at least one executable leaf step")
    return PlanValidationResult(ok=not errors, plan=plan if not errors else [], errors=errors)


def validate_step_exists(plan: list[PlanNode], step_id: str) -> bool:
    return any(node.step_id == step_id for node in flatten_plan(plan))


def validate_failed_steps(plan: list[PlanNode], step_ids: list[str]) -> list[str]:
    valid = {node.step_id for node in flatten_plan(plan)}
    return [step_id for step_id in step_ids if step_id not in valid]


def _parse_level(
    raw_steps: list[Any],
    *,
    prefix: str,
    errors: list[str],
    seen: set[str],
) -> list[PlanNode]:
    nodes: list[PlanNode] = []
    for index, raw in enumerate(raw_steps, 1):
        expected_id = f"{prefix}.{index}" if prefix else str(index)
        if not isinstance(raw, dict):
            errors.append(f"{expected_id}: step must be an object")
            continue
        step_id = str(raw.get("step_id", "")).strip()
        if step_id != expected_id:
            errors.append(f"{expected_id}: step_id must be {expected_id}, got {step_id or '(empty)'}")
        if step_id in seen:
            errors.append(f"{step_id}: duplicate step_id")
        seen.add(step_id)

        title = str(raw.get("title", "")).strip()
        goal = str(raw.get("goal", "")).strip()
        acceptance = str(raw.get("acceptance", "")).strip()
        if not title:
            errors.append(f"{expected_id}: title is required")
        if not goal:
            errors.append(f"{expected_id}: goal is required")
        if not acceptance:
            errors.append(f"{expected_id}: acceptance is required")
        files_raw = raw.get("files", [])
        if files_raw is None:
            files: list[str] = []
        elif isinstance(files_raw, list):
            files = [str(item).strip() for item in files_raw if str(item).strip()]
        else:
            errors.append(f"{expected_id}: files must be an array")
            files = []
        children_raw = raw.get("children", [])
        if children_raw is None:
            children_raw = []
        if not isinstance(children_raw, list):
            errors.append(f"{expected_id}: children must be an array")
            children_raw = []
        children = _parse_level(children_raw, prefix=expected_id, errors=errors, seen=seen)
        nodes.append(
            PlanNode(
                step_id=expected_id,
                title=title,
                goal=goal,
                acceptance=acceptance,
                files=files,
                children=children,
            )
        )
    return nodes
