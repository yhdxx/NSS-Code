from __future__ import annotations

from dataclasses import replace
from time import time
from typing import Any, Callable
from uuid import uuid4

from mycodingagent.plan_runtime.models import (
    InteractionMode,
    PlanRecord,
    PlanStatus,
    PlanStep,
    PlanStepStatus,
)


class PlanRuntime:
    def __init__(
        self,
        *,
        store: Any | None = None,
        session_id: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._session_id = session_id or (lambda: "runtime")
        self._mode = InteractionMode.NORMAL
        self._plans: dict[str, PlanRecord] = {}
        self._pending_prompt: str | None = None
        self._mode_listeners: list[Callable[[InteractionMode], None]] = []
        self._plan_skill_pending = False
        self._plan_skill_session_id: str | None = None

    @property
    def mode(self) -> InteractionMode:
        return self._mode

    @property
    def is_planning(self) -> bool:
        return self._mode is InteractionMode.PLAN

    def current_session_id(self) -> str:
        return str(self._session_id() or "runtime")

    def bind_mode_listener(self, listener: Callable[[InteractionMode], None] | None) -> None:
        if listener is not None and listener not in self._mode_listeners:
            self._mode_listeners.append(listener)

    def should_load_plan_skill(self) -> bool:
        return self.is_planning and self._plan_skill_pending

    def mark_plan_skill_loaded(self) -> None:
        self._plan_skill_pending = False

    def restore_current_session(self) -> InteractionMode:
        session_id = self.current_session_id()
        if self._store is None:
            return self._mode
        state = self._store.load_plan_runtime_state(session_id)
        restored_mode = InteractionMode(state.get("interaction_mode", InteractionMode.NORMAL.value))
        same_plan_epoch = self.is_planning and self._plan_skill_session_id == session_id
        self._set_mode(
            restored_mode,
            persist=False,
        )
        if restored_mode is InteractionMode.PLAN:
            if not same_plan_epoch:
                self._plan_skill_pending = True
            self._plan_skill_session_id = session_id
        else:
            self._plan_skill_pending = False
            self._plan_skill_session_id = None
        plan = state.get("plan")
        if isinstance(plan, PlanRecord):
            self._plans[session_id] = plan
        else:
            self._plans.pop(session_id, None)
        return self._mode

    def enter_plan_mode(self) -> None:
        session_id = self.current_session_id()
        current = self.current_plan()
        if current is not None and current.status in {PlanStatus.ACTIVE, PlanStatus.BLOCKED}:
            self._save(replace(current, status=PlanStatus.SUPERSEDED, updated_at=time()))
        self._plan_skill_pending = True
        self._plan_skill_session_id = session_id
        self._set_mode(InteractionMode.PLAN, persist=True, session_id=session_id)

    def exit_plan_mode(self, *, cancel_proposal: bool = True) -> None:
        current = self.current_plan()
        if cancel_proposal and current is not None and current.status is PlanStatus.PROPOSED:
            self._save(replace(current, status=PlanStatus.CANCELLED, updated_at=time()))
        self._plan_skill_pending = False
        self._plan_skill_session_id = None
        self._set_mode(InteractionMode.NORMAL, persist=True)

    def reset_current_session(self) -> None:
        session_id = self.current_session_id()
        self._plan_skill_pending = False
        self._plan_skill_session_id = None
        self._set_mode(InteractionMode.NORMAL, persist=False)
        self._plans.pop(session_id, None)
        if self._store is not None:
            self._store.clear_plan_runtime_state(session_id)

    def queue_implementation_prompt(self) -> None:
        self._pending_prompt = "按照计划实施"

    def take_pending_prompt(self) -> str | None:
        prompt = self._pending_prompt
        self._pending_prompt = None
        return prompt

    def current_plan(self) -> PlanRecord | None:
        session_id = self.current_session_id()
        if session_id not in self._plans and self._store is not None:
            self.restore_current_session()
        return self._plans.get(session_id)

    def proposed_plan(self) -> PlanRecord | None:
        plan = self.current_plan()
        return plan if plan is not None and plan.status is PlanStatus.PROPOSED else None

    def active_plan(self) -> PlanRecord | None:
        plan = self.current_plan()
        if plan is not None and plan.status in {PlanStatus.ACTIVE, PlanStatus.BLOCKED}:
            return plan
        return None

    def create_proposal(self, objective: str, steps: list[str]) -> PlanRecord:
        if not self.is_planning:
            raise ValueError("create_plan 只能在 Plan 模式中调用")
        objective = objective.strip()
        normalized_steps = [step.strip() for step in steps if step.strip()]
        if not objective:
            raise ValueError("计划目标不能为空")
        if not normalized_steps:
            raise ValueError("计划至少需要一个步骤")
        current = self.current_plan()
        if current is not None and current.status is PlanStatus.PROPOSED:
            self._save(replace(current, status=PlanStatus.SUPERSEDED, updated_at=time()))
        plan_id = uuid4().hex
        plan = PlanRecord(
            id=plan_id,
            session_id=self.current_session_id(),
            objective=objective,
            status=PlanStatus.PROPOSED,
            steps=tuple(
                PlanStep(id=f"{plan_id}:{index + 1}", text=text, position=index)
                for index, text in enumerate(normalized_steps)
            ),
        )
        self._save(plan)
        return plan

    def activate_proposal(self, plan_id: str) -> PlanRecord:
        plan = self._require_plan(plan_id, {PlanStatus.PROPOSED})
        activated = replace(plan, status=PlanStatus.ACTIVE, updated_at=time())
        self._save(activated)
        self._plan_skill_pending = False
        self._plan_skill_session_id = None
        self._set_mode(InteractionMode.NORMAL, persist=True, session_id=plan.session_id)
        return activated

    def reject_proposal(self, plan_id: str, *, superseded: bool = False) -> PlanRecord:
        plan = self._require_plan(plan_id, {PlanStatus.PROPOSED})
        rejected = replace(
            plan,
            status=PlanStatus.SUPERSEDED if superseded else PlanStatus.REJECTED,
            updated_at=time(),
        )
        self._save(rejected)
        return rejected

    def update_step(
        self,
        *,
        plan_id: str,
        step_id: str,
        status: PlanStepStatus,
        note: str = "",
    ) -> PlanRecord:
        plan = self._require_plan(plan_id, {PlanStatus.ACTIVE, PlanStatus.BLOCKED})
        target = next((step for step in plan.steps if step.id == step_id), None)
        if target is None:
            raise ValueError(f"计划中不存在步骤：{step_id}")
        allowed = {
            PlanStepStatus.PENDING: {PlanStepStatus.IN_PROGRESS},
            PlanStepStatus.IN_PROGRESS: {PlanStepStatus.COMPLETED, PlanStepStatus.BLOCKED},
            PlanStepStatus.BLOCKED: {PlanStepStatus.IN_PROGRESS},
            PlanStepStatus.COMPLETED: set(),
        }
        if status not in allowed[target.status]:
            raise ValueError(f"非法步骤状态转换：{target.status.value} -> {status.value}")
        if status is PlanStepStatus.IN_PROGRESS:
            other = next(
                (
                    step
                    for step in plan.steps
                    if step.id != step_id and step.status is PlanStepStatus.IN_PROGRESS
                ),
                None,
            )
            if other is not None:
                raise ValueError(f"步骤 {other.id} 正在执行，同一时间只能执行一个步骤")
        updated_steps = tuple(
            replace(step, status=status, note=note.strip()) if step.id == step_id else step
            for step in plan.steps
        )
        if all(step.status is PlanStepStatus.COMPLETED for step in updated_steps):
            plan_status = PlanStatus.COMPLETED
        elif any(step.status is PlanStepStatus.IN_PROGRESS for step in updated_steps):
            plan_status = PlanStatus.ACTIVE
        elif any(step.status is PlanStepStatus.BLOCKED for step in updated_steps):
            plan_status = PlanStatus.BLOCKED
        else:
            plan_status = PlanStatus.ACTIVE
        updated = replace(plan, status=plan_status, steps=updated_steps, updated_at=time())
        self._save(updated)
        return updated

    def context_payload(self) -> dict[str, Any] | None:
        plan = self.active_plan()
        if plan is None:
            return None
        return {
            "id": plan.id,
            "objective": plan.objective,
            "status": plan.status.value,
            "steps": [
                {
                    "id": step.id,
                    "text": step.text,
                    "status": step.status.value,
                    "note": step.note,
                }
                for step in plan.steps
            ],
        }

    def _require_plan(self, plan_id: str, statuses: set[PlanStatus]) -> PlanRecord:
        plan = self.current_plan()
        if plan is None or plan.id != plan_id:
            raise ValueError(f"当前会话不存在计划：{plan_id}")
        if plan.status not in statuses:
            expected = ", ".join(sorted(status.value for status in statuses))
            raise ValueError(f"计划状态为 {plan.status.value}，需要 {expected}")
        return plan

    def _save(self, plan: PlanRecord) -> None:
        self._plans[plan.session_id] = plan
        if self._store is not None:
            self._store.save_plan(plan)

    def _persist_mode(self, session_id: str) -> None:
        if self._store is not None:
            self._store.set_interaction_mode(session_id, self._mode.value)

    def _set_mode(
        self,
        mode: InteractionMode,
        *,
        persist: bool,
        session_id: str | None = None,
    ) -> None:
        changed = self._mode is not mode
        self._mode = mode
        if persist:
            self._persist_mode(session_id or self.current_session_id())
        if changed:
            for listener in tuple(self._mode_listeners):
                listener(mode)
