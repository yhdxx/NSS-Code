from __future__ import annotations

import json
from dataclasses import dataclass, field

from mycodingagent.mcp_integration.policy import MCPApprovalDecision, MCPApprovalRequest
from mycodingagent.terminal_ui.interrupt import PromptCancelled, TerminalInputCoordinator

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
    def __init__(self, coordinator: TerminalInputCoordinator) -> None:
        self.coordinator = coordinator
        self._approved: set[str] = set()

    async def approve(self, request: MCPServerLaunchRequest) -> MCPApprovalDecision:
        if request.server in self._approved:
            return MCPApprovalDecision(allowed=True, reason="本会话已批准该 Server")
        print("[需要批准启动 MCP Server]", flush=True)
        print(f"Server：{request.server}", flush=True)
        print(f"传输方式：{request.transport}", flush=True)
        print(f"目标：{request.target}", flush=True)
        print(
            f"沙箱：{request.sandboxed} | 工作区权限：{request.workspace_access} | 网络：{request.network}",
            flush=True,
        )
        try:
            answer = await self.coordinator.read_choice("启动该 MCP Server 吗？[y/N]：", allowed={"y", "yes"})
        except PromptCancelled:
            return MCPApprovalDecision(allowed=False, reason="用户取消")
        if answer in {"y", "yes"}:
            self._approved.add(request.server)
            return MCPApprovalDecision(allowed=True, reason="用户批准")
        return MCPApprovalDecision(allowed=False, reason="用户拒绝")


@dataclass
class CLIApprovalHook(MCPToolApprovalHook):
    coordinator: TerminalInputCoordinator = field(default_factory=TerminalInputCoordinator)
    max_argument_chars: int = 2000

    async def approve(self, request: MCPApprovalRequest) -> MCPApprovalDecision:
        print("[需要批准 MCP 调用]", flush=True)
        print(f"Server：{request.server}", flush=True)
        print(f"工具：{request.tool}", flush=True)
        print(f"风险：{request.risk}", flush=True)
        print(f"目的：{request.intent}", flush=True)
        args_text = json.dumps(request.arguments, ensure_ascii=False, indent=2, default=str)
        if len(args_text) > self.max_argument_chars:
            args_text = args_text[: self.max_argument_chars] + "\n... <参数已截断>"
        print("参数：", flush=True)
        print(args_text, flush=True)
        try:
            answer = await self.coordinator.read_choice(
                "允许本次 MCP 工具调用吗？[y/N]：", allowed={"y", "yes"}
            )
        except PromptCancelled:
            answer = ""
        if answer in {"y", "yes"}:
            return MCPApprovalDecision(allowed=True, reason="用户批准")
        return MCPApprovalDecision(allowed=False, reason="用户拒绝")
