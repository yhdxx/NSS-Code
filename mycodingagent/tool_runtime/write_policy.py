from __future__ import annotations

from dataclasses import dataclass, field
from difflib import unified_diff

from mycodingagent.terminal_ui.interrupt import PromptCancelled, TerminalInputCoordinator

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
        return WriteApprovalDecision(allowed=True, reason="auto-approved")


@dataclass
class CLIWriteApprovalHook(WriteApprovalHook):
    coordinator: TerminalInputCoordinator
    max_preview_chars: int = 4000
    _always_allowed: set[str] = field(default_factory=set)

    async def approve(self, request: WriteApprovalRequest) -> WriteApprovalDecision:
        if request.path in self._always_allowed:
            return WriteApprovalDecision(allowed=True, remember_file=True, reason="session-file-approved")
        print("[File Write Approval Required]", flush=True)
        print(f"Tool: {request.tool_name}", flush=True)
        print(f"Path: {request.path}", flush=True)
        if request.intent:
            print(f"Intent: {request.intent}", flush=True)
        preview = request.preview
        if len(preview) > self.max_preview_chars:
            preview = preview[: self.max_preview_chars] + "\n... <preview truncated>"
        if preview:
            print("Preview:", flush=True)
            print(preview, flush=True)
        try:
            answer = await self.coordinator.read_choice(
                "Allow this write? [y/N/a]: ", allowed={"y", "yes", "a", "always"}
            )
        except PromptCancelled:
            return WriteApprovalDecision(allowed=False, reason="user_cancelled")
        if answer in {"a", "always"}:
            self._always_allowed.add(request.path)
            return WriteApprovalDecision(allowed=True, remember_file=True, reason="session-file-approved")
        if answer in {"y", "yes"}:
            return WriteApprovalDecision(allowed=True, reason="user_allowed")
        return WriteApprovalDecision(allowed=False, reason="user_denied")


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
