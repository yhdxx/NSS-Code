from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AgentRole(str, Enum):
    MAIN = "main"
    PLANNER = "planner"
    AUDITOR = "auditor"
    OPTIMIZER = "optimizer"
    EXECUTOR = "executor"
    VALIDATOR = "validator"


class WorkflowStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowMode(str, Enum):
    DIRECT = "direct"
    AUDIT_ONLY = "audit_only"
    IMPLEMENTATION = "implementation"


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


@dataclass(frozen=True)
class QueryDecision:
    query: str
    mode: WorkflowMode
    reason: str = ""

    @property
    def needs_planning(self) -> bool:
        return self.mode is not WorkflowMode.DIRECT

    @classmethod
    def from_mapping(cls, value: dict[str, Any], fallback_query: str) -> QueryDecision:
        raw_mode = str(value.get("mode") or "").strip().lower()
        if raw_mode not in {item.value for item in WorkflowMode}:
            raw_mode = (
                WorkflowMode.IMPLEMENTATION.value
                if bool(value.get("needs_planning", True))
                else WorkflowMode.DIRECT.value
            )
        return cls(
            query=str(value.get("query") or fallback_query).strip(),
            mode=WorkflowMode(raw_mode),
            reason=str(value.get("reason") or "").strip(),
        )


@dataclass(frozen=True)
class AuditScope:
    name: str
    paths: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any], index: int = 0) -> AuditScope:
        return cls(
            name=str(value.get("name") or f"scope-{index + 1}").strip(),
            paths=_strings(value.get("paths")),
            goals=_strings(value.get("goals")),
        )


@dataclass(frozen=True)
class FunctionNode:
    path: str
    qualified_name: str
    kind: str = "function"
    purpose: str = ""
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> FunctionNode:
        return cls(
            path=str(value.get("path") or "").strip(),
            qualified_name=str(value.get("qualified_name") or value.get("name") or "").strip(),
            kind=str(value.get("kind") or "function").strip(),
            purpose=str(value.get("purpose") or "").strip(),
            inputs=_strings(value.get("inputs")),
            outputs=_strings(value.get("outputs")),
            side_effects=_strings(value.get("side_effects")),
        )


@dataclass(frozen=True)
class CallEdge:
    caller: str
    callee: str
    relation: str = "calls"
    confidence: float = 1.0
    evidence: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> CallEdge:
        try:
            confidence = float(value.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 0.5
        return cls(
            caller=str(value.get("caller") or "").strip(),
            callee=str(value.get("callee") or "").strip(),
            relation=str(value.get("relation") or "calls").strip(),
            confidence=max(0.0, min(1.0, confidence)),
            evidence=str(value.get("evidence") or "").strip(),
        )


@dataclass(frozen=True)
class ProjectAuditReport:
    summary: str
    modules: tuple[dict[str, Any], ...] = ()
    functions: tuple[FunctionNode, ...] = ()
    call_edges: tuple[CallEdge, ...] = ()
    risks: tuple[str, ...] = ()
    files_read: tuple[str, ...] = ()
    missing_scope: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> ProjectAuditReport:
        modules = value.get("modules")
        return cls(
            summary=str(value.get("summary") or "").strip(),
            modules=tuple(item for item in modules if isinstance(item, dict)) if isinstance(modules, list) else (),
            functions=tuple(
                FunctionNode.from_mapping(item)
                for item in value.get("functions", [])
                if isinstance(item, dict)
            ),
            call_edges=tuple(
                CallEdge.from_mapping(item)
                for item in value.get("call_edges", [])
                if isinstance(item, dict)
            ),
            risks=_strings(value.get("risks")),
            files_read=_strings(value.get("files_read")),
            missing_scope=_strings(value.get("missing_scope")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArchitectureProposal:
    summary: str
    requires_approval: bool = False
    directory_changes: tuple[str, ...] = ()
    module_changes: tuple[str, ...] = ()
    function_changes: tuple[str, ...] = ()
    compatibility_impact: tuple[str, ...] = ()
    affected_paths: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> ArchitectureProposal:
        return cls(
            summary=str(value.get("summary") or "").strip(),
            requires_approval=bool(value.get("requires_approval", False)),
            directory_changes=_strings(value.get("directory_changes")),
            module_changes=_strings(value.get("module_changes")),
            function_changes=_strings(value.get("function_changes")),
            compatibility_impact=_strings(value.get("compatibility_impact")),
            affected_paths=_strings(value.get("affected_paths")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkItem:
    task_id: str
    title: str
    objective: str
    allowed_paths: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any], index: int = 0) -> WorkItem:
        return cls(
            task_id=str(value.get("task_id") or value.get("id") or f"task-{index + 1}").strip(),
            title=str(value.get("title") or f"Task {index + 1}").strip(),
            objective=str(value.get("objective") or value.get("description") or "").strip(),
            allowed_paths=_strings(value.get("allowed_paths")),
            dependencies=_strings(value.get("dependencies")),
            acceptance_criteria=_strings(value.get("acceptance_criteria")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationReport:
    passed: bool
    summary: str
    checks: tuple[dict[str, Any], ...] = ()
    failures: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> VerificationReport:
        checks = value.get("checks")
        return cls(
            passed=bool(value.get("passed", False)),
            summary=str(value.get("summary") or "").strip(),
            checks=tuple(item for item in checks if isinstance(item, dict)) if isinstance(checks, list) else (),
            failures=_strings(value.get("failures")),
            blocked=_strings(value.get("blocked")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentRequest:
    role: AgentRole
    system_prompt: str
    user_prompt: str
    model: str
    allowed_tools: frozenset[str] = frozenset()
    allowed_paths: tuple[str, ...] = ()
    allow_validation_bash: bool = False
    max_tool_rounds: int = 20


@dataclass(frozen=True)
class AgentResult:
    text: str
    messages: tuple[dict[str, Any], ...] = ()
    tool_calls: int = 0
    error: str = ""


@dataclass(frozen=True)
class RuntimeEvent:
    phase: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowResult:
    status: WorkflowStatus
    response: str
    run_id: str = ""
    audit_report: ProjectAuditReport | None = None
    architecture_proposal: ArchitectureProposal | None = None
    work_items: tuple[WorkItem, ...] = ()
    execution_reports: tuple[dict[str, Any], ...] = ()
    verification: VerificationReport | None = None
    repair_rounds: int = 0
    changed_files: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
