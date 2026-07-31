from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from tree_sitter_language_pack import get_parser

from mycodingagent.terminal_ui.interrupt import PromptCancelled, TerminalInputCoordinator

CommandRisk = Literal["normal", "dangerous"]
ExecutionRisk = Literal["read", "write", "network", "process", "dangerous", "unknown"]

USER_DENIED_COMMAND_MESSAGE = "用户拒绝执行该命令"

# 高危命令模式。判定原则是"难以撤销"或"影响范围超出当前工作区"，
# 而不是"会写文件"——普通写入由沙箱和先读后改约束覆盖，不在这里拦截。
_DANGEROUS_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rR][a-zA-Z]*f|\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*f[a-zA-Z]*[rR]", "递归强制删除（rm -rf）"),
    (r"\bgit\s+push\b.*(--force\b|--force-with-lease\b|\s-f\b)", "强制推送（git push --force）"),
    (r"\bgit\s+reset\b.*--hard\b", "丢弃本地改动（git reset --hard）"),
    (r"\bgit\s+clean\b.*-[a-zA-Z]*f", "删除未跟踪文件（git clean -f）"),
    (r"\bgit\s+checkout\s+\.(\s|$)", "丢弃工作区改动（git checkout .）"),
    (r"\bgit\s+branch\s+(-D|--delete\s+--force)", "强制删除分支"),
    (r"\bgit\b.*\s--amend\b", "修改已有 commit（--amend）"),
    (r"\bgit\b.*\s--no-verify\b", "跳过 git hooks（--no-verify）"),
    (r"\bchmod\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rR]\b", "递归修改权限（chmod -R）"),
    (r"\bchown\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rR]\b", "递归修改属主（chown -R）"),
    (r"\b(curl|wget)\b[^|;&]*[|]\s*(sudo\s+)?(ba)?sh\b", "下载后直接执行脚本"),
    (r"\bdd\s+.*\bof=", "裸设备写入（dd of=）"),
    (r"\bmkfs(\.[a-z0-9]+)?\b", "格式化文件系统（mkfs）"),
    (r">\s*/dev/(sd|nvme|hd|vd)", "直接写入块设备"),
    (r"\bshred\b", "不可恢复擦除（shred）"),
    (r"\bsudo\b", "提权执行（sudo）"),
    (r"\btruncate\s+.*-s\s*0", "清空文件内容（truncate -s 0）"),
    (r":\(\)\s*\{.*\}\s*;\s*:", "fork 炸弹"),
    (r"\bhistory\s+-c\b", "清空命令历史"),
)

# 指向工作区之外的绝对路径写入/删除。容器内工作区固定挂载在 /workspace，
# 因此对 / 下其他系统目录的破坏性操作视为越界。
_OUT_OF_SANDBOX_PATTERN = re.compile(
    r"\b(rm|mv|cp|dd|tee|truncate|install)\b[^|;&]*\s(/(?!workspace\b|tmp\b|dev/null\b|proc\b)[a-zA-Z][^\s]*)"
)

_READ_COMMANDS = {"pwd", "ls", "cat", "head", "tail", "grep", "rg", "find", "stat", "wc", "git"}
_WRITE_COMMANDS = {"mkdir", "touch", "cp", "mv", "rm", "install", "chmod", "chown", "truncate"}
_NETWORK_COMMANDS = {"curl", "wget", "ssh", "scp", "rsync", "git"}


@dataclass(frozen=True)
class CommandApprovalRequest:
    command: str
    risk: CommandRisk
    reason: str
    intent: str = ""


@dataclass(frozen=True)
class CommandApprovalDecision:
    allowed: bool
    reason: str = ""


def classify_command(command: str) -> tuple[CommandRisk, str]:
    """Return the risk level for a shell command plus a human-readable reason.

    Only flags operations that are hard to undo or reach outside the workspace. Ordinary
    reads and writes stay unflagged -- the Docker sandbox and read-before-write rules
    already cover those, and prompting on every write would make the agent unusable.
    """
    normalized = " ".join(command.split())
    if not normalized:
        return "normal", ""
    lowered = normalized.lower()
    for pattern, reason in _DANGEROUS_PATTERNS:
        if re.search(pattern, lowered):
            return "dangerous", reason
    match = _OUT_OF_SANDBOX_PATTERN.search(normalized)
    if match:
        return "dangerous", f"操作指向工作区之外的路径：{match.group(2)}"
    return "normal", ""


def analyze_command(command: str) -> tuple[ExecutionRisk, str]:
    """Classify shell semantics for the execution gate.

    Regex rules retain precise destructive-operation messages while the syntax tree
    prevents malformed or indirect shell from being mistaken for a read-only call.
    """
    legacy_risk, legacy_reason = classify_command(command)
    if legacy_risk == "dangerous":
        return "dangerous", legacy_reason
    if not command.strip():
        return "read", ""
    try:
        parser = get_parser("bash")
        tree = parser.parse(command.encode("utf-8"))
    except Exception as exc:
        return "unknown", f"shell parser unavailable: {exc}"
    if tree.root_node.has_error:
        return "unknown", "shell syntax could not be parsed safely"

    command_names: list[str] = []
    has_write_redirect = False
    has_dynamic_command = False
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in {"file_redirect", "heredoc_redirect"}:
            text = command.encode("utf-8")[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
            if re.search(r"(^|\s)(>|>>|<>|&>)", text):
                has_write_redirect = True
        if node.type == "command":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = command.encode("utf-8")[name_node.start_byte : name_node.end_byte].decode(
                    "utf-8", errors="ignore"
                ).strip()
                if "$" in name or "`" in name:
                    has_dynamic_command = True
                elif name:
                    command_names.append(name.rsplit("/", 1)[-1])
        stack.extend(node.named_children)
    if has_dynamic_command or not command_names:
        return "unknown", "command target is dynamic or could not be identified"
    if has_write_redirect:
        return "write", "shell output redirects to a file"
    if any(name in _NETWORK_COMMANDS for name in command_names):
        if all(name == "git" for name in command_names):
            lowered = " ".join(command.lower().split())
            if re.search(r"\bgit\s+(status|diff|log|show|branch\s+--show-current)\b", lowered):
                return "read", ""
        return "network", "command may access a network or remote system"
    if any(name in _WRITE_COMMANDS for name in command_names):
        return "write", "command may modify workspace files"
    if all(name in _READ_COMMANDS for name in command_names):
        return "read", ""
    return "process", "command starts a process whose side effects are not statically known"


class CommandApprovalHook:
    """Default hook: allow everything. Keeps non-interactive callers unchanged."""

    async def approve(self, request: CommandApprovalRequest) -> CommandApprovalDecision:
        return CommandApprovalDecision(allowed=True, reason="auto-approved")


@dataclass
class CLICommandApprovalHook(CommandApprovalHook):
    coordinator: TerminalInputCoordinator = field(default_factory=TerminalInputCoordinator)
    max_command_chars: int = 2000

    async def approve(self, request: CommandApprovalRequest) -> CommandApprovalDecision:
        command_text = request.command
        if len(command_text) > self.max_command_chars:
            command_text = command_text[: self.max_command_chars] + "\n... <command truncated>"
        print("[Dangerous Command Approval Required]", flush=True)
        print(f"Risk: {request.reason}", flush=True)
        if request.intent:
            print(f"Intent: {request.intent}", flush=True)
        print("Command:", flush=True)
        print(command_text, flush=True)
        try:
            answer = await self.coordinator.read_choice(
                "Allow this command? [y/N]: ", allowed={"y", "yes"}
            )
        except PromptCancelled:
            return CommandApprovalDecision(allowed=False, reason="user_cancelled")
        if answer in {"y", "yes"}:
            return CommandApprovalDecision(allowed=True, reason="user_allowed")
        return CommandApprovalDecision(allowed=False, reason="user_denied")
