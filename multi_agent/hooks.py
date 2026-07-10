from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from multi_agent.models import ArchitectureProposal, RuntimeEvent


class RuntimeEventHook:
    async def emit(self, event: RuntimeEvent) -> None:
        return None


class CLIRuntimeEventHook(RuntimeEventHook):
    async def emit(self, event: RuntimeEvent) -> None:
        suffix = ""
        if event.metadata:
            details = ", ".join(f"{key}={value}" for key, value in event.metadata.items())
            suffix = f" ({details})"
        print(f"[MultiCoding:{event.phase}] {event.message}{suffix}", flush=True)


@dataclass(frozen=True)
class ArchitectureApprovalDecision:
    allowed: bool
    reason: str


class ArchitectureApprovalHook:
    async def approve(self, proposal: ArchitectureProposal) -> ArchitectureApprovalDecision:
        return ArchitectureApprovalDecision(allowed=False, reason="approval hook not configured")


class CLIArchitectureApprovalHook(ArchitectureApprovalHook):
    async def approve(self, proposal: ArchitectureProposal) -> ArchitectureApprovalDecision:
        print("[MultiCoding] Architecture change approval required", flush=True)
        print(proposal.summary or "(no summary)", flush=True)
        for label, values in (
            ("Directory changes", proposal.directory_changes),
            ("Module changes", proposal.module_changes),
            ("Function changes", proposal.function_changes),
            ("Compatibility impact", proposal.compatibility_impact),
        ):
            if values:
                print(f"{label}:", flush=True)
                for value in values:
                    print(f"- {value}", flush=True)
        try:
            answer = input("Apply this architecture proposal? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer in {"y", "yes"}:
            return ArchitectureApprovalDecision(allowed=True, reason="user_allowed")
        return ArchitectureApprovalDecision(allowed=False, reason="user_denied")


class StaticArchitectureApprovalHook(ArchitectureApprovalHook):
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed

    async def approve(self, proposal: ArchitectureProposal) -> ArchitectureApprovalDecision:
        reason = "test_allowed" if self.allowed else "test_denied"
        return ArchitectureApprovalDecision(allowed=self.allowed, reason=reason)


class CollectingRuntimeEventHook(RuntimeEventHook):
    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    async def emit(self, event: RuntimeEvent) -> None:
        self.events.append(event)
