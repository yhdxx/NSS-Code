from __future__ import annotations

from typing import Any

from mycodingagent.multi_agent.domain.contracts import MultiAgentSettings
from mycodingagent.multi_agent.domain.models import WorkflowResult


class MultiCodingController:
    def __init__(self, orchestrator: Any, config: MultiAgentSettings) -> None:
        self.orchestrator = orchestrator
        self.config = config
        self.enabled = False
        self.running = False
        self.last_result: WorkflowResult | None = None

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        if self.running:
            raise RuntimeError("cannot disable multicoding while a workflow is running")
        self.enabled = False

    def status_text(self) -> str:
        state = "running" if self.running else ("enabled" if self.enabled else "disabled")
        return (
            f"multicoding={state}, "
            f"audit_parallelism={self.config.audit_parallelism}, "
            f"execution_parallelism={self.config.execution_parallelism}, "
            f"max_repair_rounds={self.config.max_repair_rounds}"
        )

    async def run(
        self,
        prompt: str,
        messages: list[dict[str, Any]] | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        if not self.enabled:
            raise RuntimeError("multicoding mode is disabled")
        if self.running:
            raise RuntimeError("a multicoding workflow is already running")
        self.running = True
        try:
            result, updated_messages = await self.orchestrator.run(prompt, messages)
            self.last_result = result
            return result.response, updated_messages
        finally:
            self.running = False
