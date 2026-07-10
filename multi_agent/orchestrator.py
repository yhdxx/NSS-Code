from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

import client as agent_client
from config import CONFIG, MultiCodingConfig
from multi_agent.hooks import ArchitectureApprovalHook, RuntimeEventHook
from multi_agent.locks import PathLockManager
from multi_agent.models import (
    AgentRequest,
    AgentRole,
    ArchitectureProposal,
    AuditScope,
    ProjectAuditReport,
    QueryDecision,
    RuntimeEvent,
    VerificationReport,
    WorkflowResult,
    WorkflowStatus,
    WorkItem,
)
from multi_agent.permissions import (
    EXECUTION_TOOLS,
    READ_ONLY_TOOLS,
    VALIDATION_TOOLS,
    normalize_workspace_path,
)
from multi_agent.prompts import (
    AUDIT_MERGE_PROMPT,
    AUDIT_SPLIT_PROMPT,
    AUDIT_WORKER_PROMPT,
    EXECUTOR_PROMPT,
    FINAL_SYNTHESIS_PROMPT,
    MAIN_DECISION_PROMPT,
    OPTIMIZATION_DECISION_PROMPT,
    OPTIMIZER_PROMPT,
    PLANNER_SCOPE_PROMPT,
    REPAIR_PLANNER_PROMPT,
    VALIDATOR_PROMPT,
    WORK_PLANNER_PROMPT,
)
from multi_agent.runner import AgentOutputError, AgentRunner, parse_json_object
from multi_agent.workspace import capture_workspace_state, changed_paths, outside_scopes
from tools import ToolRegistry


SESSION_SYSTEM_PROMPT = """
You are H-Agent, a coding assistant. Read relevant project files before proposing or making changes.
Respect the user's scope, preserve existing behavior and local changes, use tools instead of guessing,
and avoid unrelated refactors. Multi-agent workflow details are summarized rather than stored verbatim.
""".strip()


class WorkflowError(RuntimeError):
    pass


class MultiCodingOrchestrator:
    def __init__(
        self,
        *,
        api_client: AsyncOpenAI,
        registry: ToolRegistry,
        tools: list[dict[str, Any]],
        core_tool_schemas: list[dict[str, Any]],
        workspace_root: Path,
        skill_runtime: Any = None,
        workspace_tracker: Any = None,
        memory_runtime: Any = None,
        capability_router: Any = None,
        config: MultiCodingConfig | None = None,
        event_hook: RuntimeEventHook,
        approval_hook: ArchitectureApprovalHook,
        runner: AgentRunner | None = None,
    ) -> None:
        self.api_client = api_client
        self.registry = registry
        self.tools = tools
        self.core_tool_schemas = core_tool_schemas
        self.workspace_root = workspace_root.resolve()
        self.skill_runtime = skill_runtime
        self.workspace_tracker = workspace_tracker
        self.memory_runtime = memory_runtime
        self.capability_router = capability_router
        self.config = config or CONFIG.multicoding
        self.event_hook = event_hook
        self.approval_hook = approval_hook
        self.runner = runner or AgentRunner(
            api_client=api_client,
            registry=registry,
            workspace_root=self.workspace_root,
        )
        self.path_locks = PathLockManager(self.workspace_root)

    async def run(
        self,
        prompt: str,
        messages: list[dict[str, Any]] | None,
    ) -> tuple[WorkflowResult, list[dict[str, Any]]]:
        baseline = capture_workspace_state(self.workspace_root)
        try:
            await self._emit("route", "Summarizing request and selecting workflow")
            decision = await self._decide_query(prompt)
            if not decision.needs_planning:
                await self._emit("route", "Using direct main-agent path", reason=decision.reason)
                text, updated = await agent_client.ask_deepseek(
                    self.api_client,
                    prompt,
                    self.registry,
                    self.tools,
                    messages or None,
                    skill_runtime=self.skill_runtime,
                    core_tool_schemas=self.core_tool_schemas,
                    workspace_tracker=self.workspace_tracker,
                    memory_runtime=self.memory_runtime,
                    capability_router=self.capability_router,
                )
                return WorkflowResult(status=WorkflowStatus.COMPLETED, response=text), updated

            audit_report = await self._audit(decision.query)
            proposal, architecture_constraint = await self._architecture_phase(decision.query, audit_report)
            work_items = await self._plan_work_items(
                decision.query,
                audit_report,
                proposal,
                architecture_constraint=architecture_constraint,
                planner_prompt=WORK_PLANNER_PROMPT,
            )
            await self._emit("execute", "Starting implementation", tasks=len(work_items))
            execution_reports, changed = await self._execute_work_items(
                query=decision.query,
                audit_report=audit_report,
                proposal=proposal,
                work_items=work_items,
            )

            verification = await self._validate(
                query=decision.query,
                audit_report=audit_report,
                proposal=proposal,
                work_items=work_items,
                execution_reports=execution_reports,
                changed_files=changed,
            )
            repair_rounds = 0
            all_work_items = list(work_items)
            all_execution_reports = list(execution_reports)
            while not verification.passed and repair_rounds < self.config.max_repair_rounds:
                repair_rounds += 1
                await self._emit(
                    "repair",
                    "Planning fixes for failed validation",
                    round=repair_rounds,
                )
                repair_items = await self._plan_work_items(
                    decision.query,
                    audit_report,
                    proposal,
                    architecture_constraint="No new architecture changes are allowed during repair.",
                    planner_prompt=REPAIR_PLANNER_PROMPT,
                    verification=verification,
                )
                repair_reports, repair_changed = await self._execute_work_items(
                    query=decision.query,
                    audit_report=audit_report,
                    proposal=proposal,
                    work_items=repair_items,
                )
                all_work_items.extend(repair_items)
                all_execution_reports.extend(repair_reports)
                changed.update(repair_changed)
                verification = await self._validate(
                    query=decision.query,
                    audit_report=audit_report,
                    proposal=proposal,
                    work_items=tuple(all_work_items),
                    execution_reports=all_execution_reports,
                    changed_files=changed,
                )

            status = WorkflowStatus.COMPLETED if verification.passed else WorkflowStatus.FAILED
            final_state = capture_workspace_state(self.workspace_root)
            changed.update(changed_paths(baseline, final_state))
            response = await self._synthesize(
                query=decision.query,
                status=status,
                audit_report=audit_report,
                proposal=proposal,
                work_items=tuple(all_work_items),
                verification=verification,
                repair_rounds=repair_rounds,
                changed_files=changed,
            )
            updated_messages = self._record_turn(messages, prompt, response)
            print(f"模型：{response}", flush=True)
            await self._emit(
                "complete",
                "Workflow finished",
                status=status.value,
                changed_files=len(changed),
            )
            return (
                WorkflowResult(
                    status=status,
                    response=response,
                    audit_report=audit_report,
                    architecture_proposal=proposal,
                    work_items=tuple(all_work_items),
                    verification=verification,
                    repair_rounds=repair_rounds,
                    changed_files=tuple(sorted(changed)),
                    errors=verification.failures if not verification.passed else (),
                ),
                updated_messages,
            )
        except asyncio.CancelledError:
            await self._emit("cancelled", "Workflow cancelled")
            raise
        except Exception as exc:
            response = f"Multi-agent workflow failed: {exc}"
            updated_messages = self._record_turn(messages, prompt, response)
            print(f"模型：{response}", flush=True)
            await self._emit("failed", "Workflow stopped", error=str(exc))
            return (
                WorkflowResult(
                    status=WorkflowStatus.FAILED,
                    response=response,
                    errors=(str(exc),),
                    changed_files=tuple(sorted(changed_paths(baseline, capture_workspace_state(self.workspace_root)))),
                ),
                updated_messages,
            )

    async def _decide_query(self, prompt: str) -> QueryDecision:
        try:
            payload = await self._agent_json(
                role=AgentRole.MAIN,
                system_prompt=MAIN_DECISION_PROMPT,
                user_prompt=prompt,
                allowed_tools=frozenset(),
            )
            return QueryDecision.from_mapping(payload, prompt)
        except WorkflowError:
            return QueryDecision(
                query=" ".join(prompt.split()),
                needs_planning=heuristic_requires_planning(prompt),
                reason="deterministic fallback after routing output failure",
            )

    async def _audit(self, query: str) -> ProjectAuditReport:
        await self._emit("plan", "Planning project audit")
        try:
            scope_payload = await self._agent_json(
                role=AgentRole.PLANNER,
                system_prompt=PLANNER_SCOPE_PROMPT,
                user_prompt=query,
                allowed_tools=READ_ONLY_TOOLS,
            )
            scopes = [
                AuditScope.from_mapping(item, index)
                for index, item in enumerate(scope_payload.get("audit_scopes", []))
                if isinstance(item, dict)
            ]
        except WorkflowError:
            scopes = []
        if not scopes:
            scopes = [AuditScope(name="project", paths=(".",), goals=("Understand code relevant to the query",))]

        try:
            split_payload = await self._agent_json(
                role=AgentRole.AUDITOR,
                system_prompt=AUDIT_SPLIT_PROMPT,
                user_prompt=_json({"query": query, "audit_scopes": [scope.__dict__ for scope in scopes]}),
                allowed_tools=READ_ONLY_TOOLS,
            )
            subtasks = [
                AuditScope.from_mapping(item, index)
                for index, item in enumerate(split_payload.get("subtasks", []))
                if isinstance(item, dict)
            ]
        except WorkflowError:
            subtasks = []
        if not subtasks:
            subtasks = scopes

        await self._emit("audit", "Running project audit", subtasks=len(subtasks))
        semaphore = asyncio.Semaphore(self.config.audit_parallelism)

        async def run_subtask(scope: AuditScope) -> dict[str, Any]:
            async with semaphore:
                payload = {
                    "query": query,
                    "scope": {
                        "name": scope.name,
                        "paths": scope.paths,
                        "goals": scope.goals,
                    },
                }
                return await self._agent_json(
                    role=AgentRole.AUDITOR,
                    system_prompt=AUDIT_WORKER_PROMPT,
                    user_prompt=_json(payload),
                    allowed_tools=READ_ONLY_TOOLS,
                )

        child_results = await asyncio.gather(
            *(run_subtask(scope) for scope in subtasks),
            return_exceptions=True,
        )
        reports: list[dict[str, Any]] = []
        for scope, result in zip(subtasks, child_results):
            if isinstance(result, Exception):
                reports.append(
                    {
                        "summary": f"Audit failed for {scope.name}",
                        "modules": [],
                        "functions": [],
                        "call_edges": [],
                        "risks": [str(result)],
                        "files_read": [],
                        "missing_scope": list(scope.paths or (scope.name,)),
                    }
                )
            else:
                reports.append(result)

        try:
            merged = await self._agent_json(
                role=AgentRole.AUDITOR,
                system_prompt=AUDIT_MERGE_PROMPT,
                user_prompt=_compact_json({"query": query, "reports": reports}),
                allowed_tools=frozenset(),
            )
        except WorkflowError:
            merged = merge_audit_reports(reports)
        report = ProjectAuditReport.from_mapping(merged)
        await self._emit(
            "audit",
            "Project audit completed",
            functions=len(report.functions),
            edges=len(report.call_edges),
            missing=len(report.missing_scope),
        )
        return report

    async def _architecture_phase(
        self,
        query: str,
        audit_report: ProjectAuditReport,
    ) -> tuple[ArchitectureProposal | None, str]:
        if user_forbids_architecture_change(query):
            await self._emit("optimize", "Architecture optimization skipped by user constraint")
            return None, "The user explicitly prohibited architecture changes."

        decision = await self._agent_json(
            role=AgentRole.PLANNER,
            system_prompt=OPTIMIZATION_DECISION_PROMPT,
            user_prompt=_compact_json({"query": query, "audit": audit_report.to_dict()}),
            allowed_tools=READ_ONLY_TOOLS,
        )
        if not bool(decision.get("needs_optimization", False)):
            await self._emit("optimize", "Architecture optimization not required")
            return None, "No architecture optimization was required."

        await self._emit("optimize", "Preparing read-only architecture proposal")
        payload = await self._agent_json(
            role=AgentRole.OPTIMIZER,
            system_prompt=OPTIMIZER_PROMPT,
            user_prompt=_compact_json({"query": query, "audit": audit_report.to_dict()}),
            allowed_tools=READ_ONLY_TOOLS,
        )
        proposal = ArchitectureProposal.from_mapping(payload)
        if not architecture_approval_required(proposal):
            return proposal, "Architecture proposal did not require approval."

        await self._emit("approval", "Waiting for architecture approval")
        decision = await self.approval_hook.approve(proposal)
        await self._emit(
            "approval",
            "Architecture proposal approved" if decision.allowed else "Architecture proposal rejected",
            reason=decision.reason,
        )
        if decision.allowed:
            return proposal, "Architecture proposal approved by the user."
        return None, "Architecture proposal rejected; implement without architecture changes."

    async def _plan_work_items(
        self,
        query: str,
        audit_report: ProjectAuditReport,
        proposal: ArchitectureProposal | None,
        *,
        architecture_constraint: str,
        planner_prompt: str,
        verification: VerificationReport | None = None,
    ) -> tuple[WorkItem, ...]:
        base_payload = {
            "query": query,
            "audit": audit_report.to_dict(),
            "architecture_proposal": proposal.to_dict() if proposal is not None else None,
            "architecture_constraint": architecture_constraint,
            "verification": verification.to_dict() if verification is not None else None,
        }
        validation_error = ""
        for _ in range(2):
            prompt = _compact_json(base_payload)
            if validation_error:
                prompt += f"\nPrevious work-item contract error: {validation_error}\nReturn corrected JSON only."
            payload = await self._agent_json(
                role=AgentRole.PLANNER,
                system_prompt=planner_prompt,
                user_prompt=prompt,
                allowed_tools=READ_ONLY_TOOLS,
            )
            try:
                items = parse_work_items(payload)
                items = ensure_framework_work_item(items)
                validate_work_items(items)
                await self._emit("plan", "Implementation plan ready", tasks=len(items))
                return items
            except WorkflowError as exc:
                validation_error = str(exc)
        raise WorkflowError(validation_error or "planner returned no executable work items")

    async def _execute_work_items(
        self,
        *,
        query: str,
        audit_report: ProjectAuditReport,
        proposal: ArchitectureProposal | None,
        work_items: tuple[WorkItem, ...],
    ) -> tuple[list[dict[str, Any]], set[str]]:
        pending = {item.task_id: item for item in work_items}
        completed: set[str] = set()
        reports: list[dict[str, Any]] = []
        changed: set[str] = set()

        while pending:
            batch = select_runnable_batch(
                tuple(pending.values()),
                completed,
                self.config.execution_parallelism,
                self.workspace_root,
            )
            if not batch:
                unresolved = ", ".join(sorted(pending))
                raise WorkflowError(f"work-item dependency cycle or unresolved dependency: {unresolved}")
            await self._emit(
                "execute",
                "Running execution batch",
                tasks=",".join(item.task_id for item in batch),
            )
            before = capture_workspace_state(self.workspace_root)
            results = await asyncio.gather(
                *(
                    self._execute_item(
                        query=query,
                        audit_report=audit_report,
                        proposal=proposal,
                        item=item,
                    )
                    for item in batch
                ),
                return_exceptions=True,
            )
            after = capture_workspace_state(self.workspace_root)
            wave_changed = changed_paths(before, after)
            allowed_union = tuple(path for item in batch for path in item.allowed_paths)
            violations = outside_scopes(wave_changed, allowed_union, self.workspace_root)
            if violations:
                raise WorkflowError(
                    "execution modified paths outside assigned scopes: " + ", ".join(sorted(violations))
                )
            changed.update(wave_changed)
            failures: list[str] = []
            for item, result in zip(batch, results):
                if isinstance(result, Exception):
                    failures.append(f"{item.task_id}: {result}")
                    continue
                reports.append({"task_id": item.task_id, **result})
                completed.add(item.task_id)
                pending.pop(item.task_id, None)
            if failures:
                raise WorkflowError("execution task failed: " + "; ".join(failures))
        return reports, changed

    async def _execute_item(
        self,
        *,
        query: str,
        audit_report: ProjectAuditReport,
        proposal: ArchitectureProposal | None,
        item: WorkItem,
    ) -> dict[str, Any]:
        async with self.path_locks.acquire(item.allowed_paths):
            request = AgentRequest(
                role=AgentRole.EXECUTOR,
                system_prompt=EXECUTOR_PROMPT,
                user_prompt=_compact_json(
                    {
                        "query": query,
                        "audit_summary": audit_report.summary,
                        "architecture_proposal": proposal.to_dict() if proposal else None,
                        "work_item": item.to_dict(),
                    }
                ),
                model=self._model_for(AgentRole.EXECUTOR),
                allowed_tools=EXECUTION_TOOLS,
                allowed_paths=item.allowed_paths,
                max_tool_rounds=self.config.max_agent_tool_rounds,
            )
            result = await self.runner.run(request)
            if result.error:
                raise WorkflowError(result.error)
            try:
                return parse_json_object(result.text)
            except AgentOutputError:
                return {"summary": result.text.strip(), "changed_files": [], "notes": ["non-JSON executor summary"]}

    async def _validate(
        self,
        *,
        query: str,
        audit_report: ProjectAuditReport,
        proposal: ArchitectureProposal | None,
        work_items: tuple[WorkItem, ...],
        execution_reports: list[dict[str, Any]],
        changed_files: set[str],
    ) -> VerificationReport:
        await self._emit("validate", "Validating implementation", changed_files=len(changed_files))
        payload = await self._agent_json(
            role=AgentRole.VALIDATOR,
            system_prompt=VALIDATOR_PROMPT,
            user_prompt=_compact_json(
                {
                    "query": query,
                    "audit_summary": audit_report.summary,
                    "architecture_proposal": proposal.to_dict() if proposal else None,
                    "work_items": [item.to_dict() for item in work_items],
                    "execution_reports": execution_reports,
                    "changed_files": sorted(changed_files),
                }
            ),
            allowed_tools=VALIDATION_TOOLS,
            allow_validation_bash=True,
        )
        report = VerificationReport.from_mapping(payload)
        if report.passed and (report.failures or report.blocked):
            report = VerificationReport(
                passed=False,
                summary=report.summary,
                checks=report.checks,
                failures=report.failures,
                blocked=report.blocked,
            )
        await self._emit(
            "validate",
            "Validation passed" if report.passed else "Validation failed",
            failures=len(report.failures),
            blocked=len(report.blocked),
        )
        return report

    async def _synthesize(
        self,
        *,
        query: str,
        status: WorkflowStatus,
        audit_report: ProjectAuditReport,
        proposal: ArchitectureProposal | None,
        work_items: tuple[WorkItem, ...],
        verification: VerificationReport,
        repair_rounds: int,
        changed_files: set[str],
    ) -> str:
        request = AgentRequest(
            role=AgentRole.MAIN,
            system_prompt=FINAL_SYNTHESIS_PROMPT,
            user_prompt=_compact_json(
                {
                    "query": query,
                    "status": status.value,
                    "audit_summary": audit_report.summary,
                    "architecture_proposal": proposal.to_dict() if proposal else None,
                    "work_items": [item.to_dict() for item in work_items],
                    "verification": verification.to_dict(),
                    "repair_rounds": repair_rounds,
                    "changed_files": sorted(changed_files),
                }
            ),
            model=self._model_for(AgentRole.MAIN),
            allowed_tools=frozenset(),
            max_tool_rounds=1,
        )
        result = await self.runner.run(request)
        if result.text.strip():
            return result.text.strip()
        state = "completed" if verification.passed else "stopped with validation failures"
        return f"Multi-agent workflow {state}. Changed files: {', '.join(sorted(changed_files)) or 'none'}."

    async def _agent_json(
        self,
        *,
        role: AgentRole,
        system_prompt: str,
        user_prompt: str,
        allowed_tools: frozenset[str],
        allow_validation_bash: bool = False,
    ) -> dict[str, Any]:
        prompt = user_prompt
        errors: list[str] = []
        for _ in range(3):
            request = AgentRequest(
                role=role,
                system_prompt=system_prompt,
                user_prompt=prompt,
                model=self._model_for(role),
                allowed_tools=allowed_tools,
                allow_validation_bash=allow_validation_bash,
                max_tool_rounds=self.config.max_agent_tool_rounds,
            )
            result = await self.runner.run(request)
            if result.error:
                errors.append(result.error)
            else:
                try:
                    return parse_json_object(result.text)
                except AgentOutputError as exc:
                    errors.append(str(exc))
            prompt = (
                user_prompt
                + "\nYour previous response was invalid: "
                + errors[-1]
                + "\nReturn one corrected JSON object only."
            )
        raise WorkflowError(f"{role.value} agent output failed: {'; '.join(errors)}")

    async def _emit(self, phase: str, message: str, **metadata: Any) -> None:
        await self.event_hook.emit(RuntimeEvent(phase=phase, message=message, metadata=metadata))

    def _model_for(self, role: AgentRole) -> str:
        configured = {
            AgentRole.MAIN: self.config.main_model,
            AgentRole.PLANNER: self.config.planner_model,
            AgentRole.AUDITOR: self.config.auditor_model,
            AgentRole.OPTIMIZER: self.config.optimizer_model,
            AgentRole.EXECUTOR: self.config.executor_model,
            AgentRole.VALIDATOR: self.config.validator_model,
        }[role]
        return configured or agent_client.MODEL

    def _record_turn(
        self,
        messages: list[dict[str, Any]] | None,
        prompt: str,
        response: str,
    ) -> list[dict[str, Any]]:
        updated = list(messages or [])
        if not updated:
            updated.append({"role": "system", "content": SESSION_SYSTEM_PROMPT})
        updated.append({"role": "user", "content": prompt})
        updated.append({"role": "assistant", "content": response})
        if self.memory_runtime is not None:
            session_id = self.memory_runtime.start_session(agent_client.MODEL)
            self.memory_runtime.save_messages(session_id, updated)
        return updated


def parse_work_items(payload: dict[str, Any]) -> tuple[WorkItem, ...]:
    raw_items = payload.get("work_items")
    if not isinstance(raw_items, list) or not raw_items:
        raise WorkflowError("planner returned no work_items")
    return tuple(
        WorkItem.from_mapping(item, index)
        for index, item in enumerate(raw_items)
        if isinstance(item, dict)
    )


def ensure_framework_work_item(items: tuple[WorkItem, ...]) -> tuple[WorkItem, ...]:
    if any(
        any(path.rstrip("/") == "PROJECT_FRAMEWORK.md" for path in item.allowed_paths)
        for item in items
    ):
        return items
    dependencies = tuple(item.task_id for item in items)
    framework_item = WorkItem(
        task_id="update-project-framework",
        title="Update function-level project framework",
        objective=(
            "Update PROJECT_FRAMEWORK.md for every module, class, function, and workflow changed by this implementation."
        ),
        allowed_paths=("PROJECT_FRAMEWORK.md",),
        dependencies=dependencies,
        acceptance_criteria=("The framework document matches the implemented code structure.",),
    )
    return (*items, framework_item)


def validate_work_items(items: tuple[WorkItem, ...]) -> None:
    if not items:
        raise WorkflowError("implementation plan is empty")
    ids = [item.task_id for item in items]
    if any(not task_id for task_id in ids):
        raise WorkflowError("every work item requires a task_id")
    if len(ids) != len(set(ids)):
        raise WorkflowError("work item task_id values must be unique")
    known = set(ids)
    for item in items:
        if not item.allowed_paths:
            raise WorkflowError(f"work item {item.task_id} has no allowed_paths")
        unknown = set(item.dependencies) - known
        if unknown:
            raise WorkflowError(
                f"work item {item.task_id} has unknown dependencies: {', '.join(sorted(unknown))}"
            )
        if item.task_id in item.dependencies:
            raise WorkflowError(f"work item {item.task_id} depends on itself")


def select_runnable_batch(
    items: tuple[WorkItem, ...],
    completed: set[str],
    limit: int,
    workspace_root: Path,
) -> tuple[WorkItem, ...]:
    ready = sorted(
        (item for item in items if set(item.dependencies).issubset(completed)),
        key=lambda item: item.task_id,
    )
    if not ready:
        return ()
    selected: list[WorkItem] = []
    for item in ready:
        if len(selected) >= max(1, limit):
            break
        if any(path_scopes_overlap(item.allowed_paths, other.allowed_paths, workspace_root) for other in selected):
            continue
        selected.append(item)
    return tuple(selected or ready[:1])


def path_scopes_overlap(left: tuple[str, ...], right: tuple[str, ...], root: Path) -> bool:
    left_paths = [normalize_workspace_path(path, root) for path in left]
    right_paths = [normalize_workspace_path(path, root) for path in right]
    return any(
        a == b or a in b.parents or b in a.parents
        for a in left_paths
        for b in right_paths
    )


def merge_audit_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "summary": "Merged project audit",
        "modules": [],
        "functions": [],
        "call_edges": [],
        "risks": [],
        "files_read": [],
        "missing_scope": [],
    }
    for key in ("modules", "functions", "call_edges", "risks", "files_read", "missing_scope"):
        seen: set[str] = set()
        for report in reports:
            values = report.get(key, [])
            if not isinstance(values, list):
                continue
            for value in values:
                marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
                if marker in seen:
                    continue
                seen.add(marker)
                merged[key].append(value)
    summaries = [str(report.get("summary") or "").strip() for report in reports]
    merged["summary"] = " | ".join(summary for summary in summaries if summary) or "Merged project audit"
    return merged


def architecture_approval_required(proposal: ArchitectureProposal) -> bool:
    return bool(
        proposal.requires_approval
        or proposal.directory_changes
        or proposal.module_changes
        or proposal.compatibility_impact
    )


def user_forbids_architecture_change(query: str) -> bool:
    normalized = " ".join(query.lower().split())
    phrases = (
        "不要改项目架构",
        "不要修改项目架构",
        "不要重构",
        "不改架构",
        "保持现有架构",
        "do not change the architecture",
        "no architecture changes",
        "do not refactor",
    )
    return any(phrase in normalized for phrase in phrases)


def heuristic_requires_planning(prompt: str) -> bool:
    normalized = prompt.lower()
    markers = (
        "修改",
        "实现",
        "新增",
        "添加",
        "修复",
        "重构",
        "迁移",
        "测试",
        "代码",
        "项目",
        "文件",
        "implement",
        "modify",
        "change",
        "fix",
        "refactor",
        "test",
        "build",
        ".py",
        ".ts",
        ".js",
        ".java",
        ".go",
        ".rs",
    )
    return any(marker in normalized for marker in markers)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _compact_json(value: Any, limit: int = 60000) -> str:
    text = _json(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... <context truncated>"
