from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import time


class InteractionMode(StrEnum):
    NORMAL = "normal"
    PLAN = "plan"


class PlanStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PlanStepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class PlanStep:
    id: str
    text: str
    position: int
    status: PlanStepStatus = PlanStepStatus.PENDING
    note: str = ""


@dataclass(frozen=True)
class PlanRecord:
    id: str
    session_id: str
    objective: str
    status: PlanStatus
    steps: tuple[PlanStep, ...] = field(default_factory=tuple)
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)

