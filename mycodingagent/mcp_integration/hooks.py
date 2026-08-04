from __future__ import annotations

import json
from dataclasses import dataclass, field

from mycodingagent.approval import ApprovalRuntime
from mycodingagent.mcp_integration.policy import MCPApprovalDecision, MCPApprovalRequest
from mycodingagent.terminal_ui.application import SharedTerminalInput, TerminalCancelled, TerminalInput
from mycodingagent.terminal_ui.output import (
    render_mcp_approval_request,
    render_mcp_launch_approval_request,
)

USER_DENIED_MESSAGE = "用户拒绝你的工具调用"


class MCPToolApprovalHook:
    async def approve(self, request: MCPApprovalRequest) -> MCPApprovalDecision:
        return MCPApprovalDecision(allowed=True, reason="自动批准")


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
        return MCPApprovalDecision(allowed=True, reason="自动批准")


class CLILaunchApprovalHook(MCPServerLaunchHook):
    def __init__(
        self,
        coordinator: TerminalInput,
        approval_runtime: ApprovalRuntime | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.approval_runtime = approval_runtime
        self._approved: set[str] = set()

    async def approve(self, request: MCPServerLaunchRequest) -> MCPApprovalDecision:
        if self.approval_runtime is not None and self.approval_runtime.auto_approve:
            return MCPApprovalDecision(allowed=True, reason="auto 模式自动批准")
        if request.server in self._approved:
            return MCPApprovalDecision(allowed=True, reason="本会话已批准该 Server")
        render_mcp_launch_approval_request(
            server=request.server,
            transport=request.transport,
            target=request.target,
            sandboxed=request.sandboxed,
            workspace_access=request.workspace_access,
            network=request.network,
        )
        try:
            answer = await self.coordinator.read_choice("启动该 MCP Server 吗？[y/N]：", allowed={"y", "yes"})
        except TerminalCancelled:
            return MCPApprovalDecision(allowed=False, reason="用户取消")
        if answer in {"y", "yes"}:
            self._approved.add(request.server)
            return MCPApprovalDecision(allowed=True, reason="用户批准")
        return MCPApprovalDecision(allowed=False, reason="用户拒绝")


@dataclass
class CLIApprovalHook(MCPToolApprovalHook):
    coordinator: TerminalInput = field(default_factory=SharedTerminalInput)
    approval_runtime: ApprovalRuntime | None = None
    max_argument_chars: int = 2000
    _always_allowed: set[tuple[str, str, str]] = field(default_factory=set)

    async def approve(self, request: MCPApprovalRequest) -> MCPApprovalDecision:
        if self.approval_runtime is not None and self.approval_runtime.auto_approve:
            return MCPApprovalDecision(allowed=True, reason="auto 模式自动批准")
        approval_key = (request.server, request.tool, request.risk)
        if approval_key in self._always_allowed:
            return MCPApprovalDecision(allowed=True, reason="本会话已批准该 MCP 工具")
        args_text = json.dumps(request.arguments, ensure_ascii=False, indent=2, default=str)
        if len(args_text) > self.max_argument_chars:
            args_text = args_text[: self.max_argument_chars] + "\n... <参数已截断>"
        render_mcp_approval_request(
            server=request.server,
            tool=request.tool,
            risk=request.risk,
            intent=request.intent,
            arguments=args_text,
        )
        try:
            answer = await self.coordinator.read_choice(
                "允许本次 MCP 工具调用吗？[y/N/a]：", allowed={"y", "yes", "a", "always"}
            )
        except TerminalCancelled:
            answer = ""
        if answer in {"a", "always"}:
            self._always_allowed.add(approval_key)
            return MCPApprovalDecision(allowed=True, reason="本会话已批准该 MCP 工具")
        if answer in {"y", "yes"}:
            return MCPApprovalDecision(allowed=True, reason="用户批准")
        return MCPApprovalDecision(allowed=False, reason="用户拒绝")
