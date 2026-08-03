from __future__ import annotations

from dataclasses import dataclass, field
from difflib import unified_diff

from mycodingagent.terminal_ui.application import TerminalCancelled, TerminalInput
from mycodingagent.terminal_ui.output import render_write_approval_request

USER_DENIED_WRITE_MESSAGE = "用户拒绝执行该文件写入"


@dataclass(frozen=True)
class WriteApprovalRequest:
    tool_name: str
    path: str
    intent: str
    is_new_file: bool
    preview: str


@dataclass(frozen=True)
class WriteApprovalDecision:
    allowed: bool
    remember_file: bool = False
    reason: str = ""


class WriteApprovalHook:
    async def approve(self, request: WriteApprovalRequest) -> WriteApprovalDecision:
        return WriteApprovalDecision(allowed=True, reason="自动批准")


@dataclass
class CLIWriteApprovalHook(WriteApprovalHook):
    coordinator: TerminalInput
    max_preview_chars: int = 4000
    _always_allowed: set[str] = field(default_factory=set)

    async def approve(self, request: WriteApprovalRequest) -> WriteApprovalDecision:
        if request.path in self._always_allowed:
            return WriteApprovalDecision(allowed=True, remember_file=True, reason="本会话已批准该文件")
        render_write_approval_request(
            tool_name=request.tool_name,
            path=request.path,
            intent=request.intent,
            preview=request.preview,
            max_preview_chars=self.max_preview_chars,
        )
        try:
            answer = await self.coordinator.read_choice(
                "允许本次写入吗？[y/N/a]：", allowed={"y", "yes", "a", "always"}
            )
        except TerminalCancelled:
            return WriteApprovalDecision(allowed=False, reason="用户取消")
        if answer in {"a", "always"}:
            self._always_allowed.add(request.path)
            return WriteApprovalDecision(allowed=True, remember_file=True, reason="本会话已批准该文件")
        if answer in {"y", "yes"}:
            return WriteApprovalDecision(allowed=True, reason="用户批准")
        return WriteApprovalDecision(allowed=False, reason="用户拒绝")


def write_preview(path: str, before: str, after: str) -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    return "".join(
        unified_diff(
            before_lines,
            after_lines,
            fromfile=path if before else "/dev/null",
            tofile=path,
        )
    )
