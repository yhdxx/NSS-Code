from __future__ import annotations

import json
from dataclasses import dataclass, field

from mycodingagent.mcp_integration.policy import MCPApprovalDecision, MCPApprovalRequest
from mycodingagent.terminal_ui.interrupt import PromptCancelled, TerminalInputCoordinator

USER_DENIED_MESSAGE = "用户拒绝你的工具调用"


class MCPToolApprovalHook:
    async def approve(self, request: MCPApprovalRequest) -> MCPApprovalDecision:
        return MCPApprovalDecision(allowed=True, reason="auto-approved")


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
