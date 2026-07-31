from __future__ import annotations

import json
from dataclasses import dataclass, field

from mycodingagent.mcp_integration.policy import MCPApprovalDecision, MCPApprovalRequest
from mycodingagent.terminal_ui.interrupt import PromptCancelled, TerminalInputCoordinator

USER_DENIED_MESSAGE = "用户拒绝你的工具调用"


class MCPToolApprovalHook:
    async def approve(self, request: MCPApprovalRequest) -> MCPApprovalDecision:
        return MCPApprovalDecision(allowed=True, reason="auto-approved")


@dataclass(frozen=True)
class MCPServerLaunchRequest:
    server: str
    transport: str
    target: str
    sandboxed: bool
    workspace_access: str
    network: bool


class MCPServerLaunchHook:
    async def approve(self, request: MCPServerLaunchRequest) -> MCPApprovalDecision:
        return MCPApprovalDecision(allowed=True, reason="auto-approved")


class CLILaunchApprovalHook(MCPServerLaunchHook):
    def __init__(self, coordinator: TerminalInputCoordinator) -> None:
        self.coordinator = coordinator
        self._approved: set[str] = set()

    async def approve(self, request: MCPServerLaunchRequest) -> MCPApprovalDecision:
        if request.server in self._approved:
            return MCPApprovalDecision(allowed=True, reason="session-server-approved")
        print("[MCP Server Launch Approval Required]", flush=True)
        print(f"Server: {request.server}", flush=True)
        print(f"Transport: {request.transport}", flush=True)
        print(f"Target: {request.target}", flush=True)
        print(
            f"Sandboxed: {request.sandboxed} | Workspace: {request.workspace_access} | Network: {request.network}",
            flush=True,
        )
        try:
            answer = await self.coordinator.read_choice("Launch this MCP server? [y/N]: ", allowed={"y", "yes"})
        except PromptCancelled:
            return MCPApprovalDecision(allowed=False, reason="user_cancelled")
        if answer in {"y", "yes"}:
            self._approved.add(request.server)
            return MCPApprovalDecision(allowed=True, reason="user_allowed")
        return MCPApprovalDecision(allowed=False, reason="user_denied")


@dataclass
class CLIApprovalHook(MCPToolApprovalHook):
    coordinator: TerminalInputCoordinator = field(default_factory=TerminalInputCoordinator)
    max_argument_chars: int = 2000

    async def approve(self, request: MCPApprovalRequest) -> MCPApprovalDecision:
        print("[MCP Approval Required]", flush=True)
        print(f"Server: {request.server}", flush=True)
        print(f"Tool: {request.tool}", flush=True)
        print(f"Risk: {request.risk}", flush=True)
        print(f"Intent: {request.intent}", flush=True)
        args_text = json.dumps(request.arguments, ensure_ascii=False, indent=2, default=str)
        if len(args_text) > self.max_argument_chars:
            args_text = args_text[: self.max_argument_chars] + "\n... <arguments truncated>"
        print("Arguments:", flush=True)
        print(args_text, flush=True)
        try:
            answer = await self.coordinator.read_choice(
                "Allow this MCP tool call? [y/N]: ", allowed={"y", "yes"}
            )
        except PromptCancelled:
            answer = ""
        if answer in {"y", "yes"}:
            return MCPApprovalDecision(allowed=True, reason="user_allowed")
        return MCPApprovalDecision(allowed=False, reason="user_denied")
