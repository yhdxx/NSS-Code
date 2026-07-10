from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from mycodingagent.multi_agent.domain.models import AgentRequest, AgentResult, ArchitectureProposal, RuntimeEvent


class AgentRuntime(Protocol):
    async def run(self, request: AgentRequest) -> AgentResult: ...


class DirectResponder(Protocol):
    async def respond(
        self,
        prompt: str,
        messages: list[dict[str, Any]] | None,
    ) -> tuple[str, list[dict[str, Any]]]: ...


class RuntimeEventSink(Protocol):
    async def emit(self, event: RuntimeEvent) -> None: ...


class MultiAgentSettings(Protocol):
    audit_parallelism: int
    execution_parallelism: int
    max_repair_rounds: int
    max_agent_tool_rounds: int
    main_model: str
    planner_model: str
    auditor_model: str
    optimizer_model: str
    executor_model: str
    validator_model: str


class ConversationRecorder(Protocol):
    def start_session(self, model: str) -> str: ...

    def save_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None: ...


class RunJournal(Protocol):
    def save(self, record: dict[str, Any]) -> str: ...

    def latest(self) -> dict[str, Any] | None: ...

    def get(self, run_id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class ArchitectureApprovalDecision:
    allowed: bool
    reason: str


class ArchitectureApprovalPort(Protocol):
    async def approve(self, proposal: ArchitectureProposal) -> ArchitectureApprovalDecision: ...
