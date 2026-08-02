from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TextIO

try:
    from rich.console import Console
    from rich.text import Text
    from rich.theme import Theme
except ImportError:  # pragma: no cover - only relevant before dependencies are installed
    Console = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]
    Theme = None  # type: ignore[assignment]

from mycodingagent.terminal_ui.highlighters import detect_language, highlight_for_terminal


_TERMINAL_REGION_MARKED = False

READ_LIKE_TOOLS = {
    "Glob",
    "Grep",
    "ReadFile",
    "BatchRecoverContext",
    "SearchRecoverableContext",
    "SearchSessionHistory",
    "GetRecentConversationTurns",
    "RestoreSession",
    "ProjectArchitecture",
    "UnitDependencyGraph",
    "code_index",
    "lsp",
}

STATUS_READ_TOOLS = {
    "Glob",
    "Grep",
    "ReadFile",
    "BatchRecoverContext",
    "SearchRecoverableContext",
    "SearchSessionHistory",
    "GetRecentConversationTurns",
    "RestoreSession",
}

MAX_INLINE_TEXT = 180
MAX_BLOCK_TEXT = 1200
BashDisplayLevel = Literal["low", "approval", "high"]
BashDisplayClassifier = Callable[[str], tuple[BashDisplayLevel, str]]

TERMINAL_THEME_STYLES: dict[str, str] = {
    "label": "bold bright_white",
    "text": "grey70",
    "status": "grey50",
    "error": "bold red",
    "tool.output": "grey58",
    "tool.generic": "grey70",
    "tool.section": "bold bright_white",
    "tool.branch": "grey50",
    "tool.arg": "grey70",
    "tool.read": "bright_blue",
    "tool.write": "grey70",
    "bash.command": "grey70",
    "bash.low": "green",
    "bash.approval": "yellow",
    "bash.high": "bold red",
    "edit.old": "yellow",
    "edit.new": "green",
    "markdown.base": "bright_white",
    "markdown.paragraph": "bright_white",
    "markdown.h1": "bold bright_white",
    "markdown.h2": "bold bright_white",
    "markdown.h3": "bold bright_white",
    "markdown.h4": "bold bright_white",
    "markdown.h5": "bold bright_white",
    "markdown.h6": "bold bright_white",
    "markdown.code": "grey85",
    "markdown.code_block": "grey85",
    "markdown.block_quote": "italic grey58",
    "markdown.link": "underline bright_blue",
}


def render_assistant_markdown(text: str, *, label: str = "模型", file: TextIO | None = None) -> None:
    """Render a completed assistant answer as Markdown in the terminal."""
    output = _resolve_file(file)
    console = _console(output)
    _print_text(console, f"{label}：", style="label")
    if not text:
        return
    if Console is None:
        print(text, file=output, flush=True)
        return
    console.print(highlight_for_terminal(text, declared_language="markdown", style="bright_white"))


def render_assistant_text(
    text: str,
    *,
    label: str = "模型",
    end: str = "\n",
    file: TextIO | None = None,
    style: str = "text",
) -> None:
    """Render assistant text without Markdown transformation."""
    output = _resolve_file(file)
    console = _console(output)
    rendered = f"{label}：{text}"
    if end:
        _print_text(console, rendered, style=style)
    else:
        if Text is None:
            output.write(rendered)
            output.flush()
        else:
            console.print(Text(rendered, style=style), end="")


def render_status_line(message: str, *, file: TextIO | None = None) -> None:
    output = _resolve_file(file)
    _print_text(_console(output), f"H-Agent:{message}...", style="status")


def clear_terminal(*, file: TextIO | None = None) -> None:
    """Clear the visible Agent screen without erasing terminal scrollback."""
    output = _resolve_file(file)
    if not _isatty(output):
        return
    output.write("\033[H\033[2J")
    output.flush()


def mark_terminal_region_start(*, file: TextIO | None = None) -> None:
    """Save the cursor position used as the top of the Agent redraw region."""
    global _TERMINAL_REGION_MARKED
    output = _resolve_file(file)
    if not _isatty(output):
        return
    output.write("\033[s")
    output.flush()
    _TERMINAL_REGION_MARKED = True


def processing_status(
    message: str,
    *,
    enabled: bool = True,
    file: TextIO | None = None,
) -> "TerminalStatus":
    return TerminalStatus(message=message, enabled=enabled, file=file)


def tool_status_message(tool_name: str) -> str:
    if tool_name in {"Grep", "SearchRecoverableContext", "SearchSessionHistory"}:
        return "搜索内容中"
    if tool_name in STATUS_READ_TOOLS:
        return "读取内容中"
    if tool_name in {"WriteFile", "EditFile"}:
        return "修改文件中"
    if tool_name == "Bash":
        return "执行命令中"
    if tool_name == "invoke_skill" or tool_name.startswith("skill_"):
        return "执行 Skill 中"
    return "执行工具中"


def render_tool_calls(
    tool_calls: Sequence[Any],
    *,
    file: TextIO | None = None,
    bash_classifier: BashDisplayClassifier | None = None,
) -> None:
    """Render tool calls as compact, colored terminal UI blocks."""
    if not tool_calls:
        return
    output = _resolve_file(file)
    console = _console(output)
    pending_reads: list[_ToolCallView] = []

    def flush_reads() -> None:
        if not pending_reads:
            return
        _print_text(console, "• Explored", style="tool.section")
        for index, call in enumerate(pending_reads):
            prefix = "  └ " if index == 0 else "    "
            _print_read_summary(console, prefix, read_call_summary(call))
        pending_reads.clear()

    for raw_call in tool_calls:
        call = _ToolCallView.from_call(raw_call)
        if call.name in READ_LIKE_TOOLS:
            pending_reads.append(call)
            continue
        flush_reads()
        render_single_tool_call(console, call, bash_classifier=bash_classifier)
    flush_reads()


def render_tool_result_preview(
    *,
    tool_name: str,
    content: str,
    is_error: bool = False,
    file: TextIO | None = None,
    max_chars: int = 1200,
) -> None:
    output = _resolve_file(file)
    console = _console(output)
    style = "error" if is_error else "tool.output"
    title = f"  ↳ {tool_name or 'Tool'} output"
    _print_text(console, title, style=style)
    preview = truncate_text(content, max_chars)
    if preview:
        if is_error:
            _print_block(console, preview, prefix="    ", style=style, max_chars=max_chars)
        else:
            _print_highlighted_block(console, preview, prefix="    ", style=style, max_chars=max_chars)


def render_command_approval_request(
    *,
    command: str,
    reason: str,
    intent: str = "",
    dangerous: bool = False,
    file: TextIO | None = None,
) -> None:
    output = _resolve_file(file)
    console = _console(output)
    style = "bash.high" if dangerous else "bash.approval"
    label = "高危命令需要批准" if dangerous else "命令需要批准"
    _print_text(console, f"• {label}", style=style)
    if reason:
        _print_text(console, f"  风险：{reason}", style=style)
    if intent:
        _print_text(console, f"  目的：{intent}", style="text")
    _print_text(console, "  命令：", style=style)
    _print_block(console, command, prefix="    ", style="bash.command", max_chars=2000)


def render_write_approval_request(
    *,
    tool_name: str,
    path: str,
    intent: str = "",
    preview: str = "",
    file: TextIO | None = None,
    max_preview_chars: int = 4000,
) -> None:
    output = _resolve_file(file)
    console = _console(output)
    _print_text(console, "• 文件写入需要批准", style="tool.write")
    _print_text(console, f"  工具：{tool_name}", style="tool.write")
    _print_text(console, f"  路径：{path}", style="tool.write")
    if intent:
        _print_text(console, f"  目的：{intent}", style="text")
    preview_text = truncate_text(preview, max_preview_chars) if preview else ""
    if not preview_text:
        return
    _print_text(console, "  预览：", style="tool.write")
    for line in preview_text.splitlines():
        style = "tool.output"
        if line.startswith("-") and not line.startswith("---"):
            style = "edit.old"
        elif line.startswith("+") and not line.startswith("+++"):
            style = "edit.new"
        _print_text(console, "    " + line, style=style)


class TerminalStatus:
    def __init__(
        self,
        *,
        message: str,
        enabled: bool = True,
        file: TextIO | None = None,
        interval_seconds: float = 0.35,
    ) -> None:
        self.message = message
        self.output = _resolve_file(file)
        self.enabled = bool(enabled and _isatty(self.output))
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "TerminalStatus":
        if self.enabled:
            self._task = asyncio.create_task(self._animate())
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self.enabled:
            self.output.write("\r\033[2K")
            self.output.flush()

    async def _animate(self) -> None:
        dots = (".", "..", "...")
        index = 0
        while True:
            self.output.write("\r\033[2K")
            self.output.write(f"\033[90mH-Agent:{self.message}{dots[index % len(dots)]}\033[0m")
            self.output.flush()
            index += 1
            await asyncio.sleep(self.interval_seconds)


@dataclass(frozen=True)
class _ToolCallView:
    name: str
    arguments: str
    args: dict[str, Any]

    @classmethod
    def from_call(cls, call: Any) -> "_ToolCallView":
        name = getattr(call, "tool_name", "")
        arguments = str(getattr(call, "arguments", "") or "")
        if not name and isinstance(call, dict):
            function = call.get("function", {})
            name = str(function.get("name", ""))
            arguments = str(function.get("arguments", "") or "")
        return cls(name=name, arguments=arguments, args=parse_arguments(arguments))


def render_single_tool_call(
    console: Any,
    call: _ToolCallView,
    *,
    bash_classifier: BashDisplayClassifier | None,
) -> None:
    if call.name == "Bash":
        render_bash_call(console, call, bash_classifier=bash_classifier)
        return
    if call.name == "EditFile":
        render_edit_call(console, call)
        return
    if call.name == "WriteFile":
        render_write_call(console, call)
        return
    render_generic_call(console, call)


def render_bash_call(
    console: Any,
    call: _ToolCallView,
    *,
    bash_classifier: BashDisplayClassifier | None,
) -> None:
    command = str(call.args.get("command") or "")
    level, reason = bash_classifier(command) if bash_classifier is not None else default_bash_display_level(command)
    style = f"bash.{level}"
    labels = {"low": "低危", "approval": "需审批", "high": "高危"}
    suffix = f"[{labels[level]}]"
    segments = [("• Bash ", "tool.section"), (suffix, style)]
    if reason:
        segments.extend([(" — ", "tool.arg"), (compact_one_line(reason, 80), "tool.arg")])
    _print_segments(console, segments)
    _print_block(console, command, prefix="  └ ", style="bash.command", max_chars=MAX_BLOCK_TEXT)


def render_edit_call(console: Any, call: _ToolCallView) -> None:
    path = str(call.args.get("file_path") or "")
    _print_segments(console, [("• Edit ", "tool.section"), (path, "tool.arg")])
    old_text = str(call.args.get("old_string") or "")
    new_text = str(call.args.get("new_string") or "")
    _print_text(console, "  ├ Replace", style="edit.old")
    _print_block(console, old_text, prefix="  │ ", style="edit.old", max_chars=MAX_BLOCK_TEXT)
    _print_text(console, "  └ With", style="edit.new")
    _print_block(console, new_text, prefix="    ", style="edit.new", max_chars=MAX_BLOCK_TEXT)


def render_write_call(console: Any, call: _ToolCallView) -> None:
    path = str(call.args.get("file_path") or "")
    _print_segments(console, [("• Write ", "tool.section"), (path, "tool.arg")])
    content = str(call.args.get("content") or "")
    if content:
        _print_highlighted_block(
            console,
            content,
            prefix="  └ ",
            style="tool.output",
            max_chars=MAX_BLOCK_TEXT,
            file_path=path,
        )


def render_generic_call(console: Any, call: _ToolCallView) -> None:
    summary = compact_arguments(call.args) if call.args else call.arguments
    _print_text(console, f"• {call.name}", style="tool.section")
    if summary:
        _print_text(console, f"  └ {summary}", style="tool.generic")


@dataclass(frozen=True)
class _ReadSummary:
    verb: str
    detail: str


def read_call_summary(call: _ToolCallView) -> _ReadSummary:
    if call.name == "Glob":
        pattern = compact_one_line(call.args.get("pattern"), 80)
        path = compact_one_line(call.args.get("path") or ".", 80)
        return _ReadSummary("Search", f"files {pattern} in {path}")
    if call.name == "Grep":
        pattern = compact_one_line(call.args.get("pattern"), 80)
        path = compact_one_line(call.args.get("path") or ".", 80)
        include = compact_one_line(call.args.get("include"), 60)
        suffix = f" ({include})" if include else ""
        return _ReadSummary("Search", f"{pattern} in {path}{suffix}")
    if call.name == "ReadFile":
        path = compact_one_line(call.args.get("file_path"), 120)
        offset = int(call.args.get("offset") or 0)
        limit = call.args.get("limit")
        if limit:
            return _ReadSummary("Read", f"{path} lines {offset + 1}-{offset + int(limit)}")
        return _ReadSummary("Read", path)
    if call.name == "BatchRecoverContext":
        items = call.args.get("items")
        if isinstance(items, list):
            ids = [compact_one_line(item.get("context_id"), 12) for item in items if isinstance(item, dict)]
            return _ReadSummary("Recover", "context " + ", ".join(ids))
        return _ReadSummary("Recover", "stored context")
    if call.name in {"SearchRecoverableContext", "SearchSessionHistory"}:
        query = compact_one_line(call.args.get("query"), 120)
        return _ReadSummary("Search", f"history {query}" if query else "history")
    if call.name == "GetRecentConversationTurns":
        return _ReadSummary("Read", "recent conversation")
    return _ReadSummary(call.name, compact_arguments(call.args) if call.args else "")


def default_bash_display_level(command: str) -> tuple[BashDisplayLevel, str]:
    if not command.strip():
        return "approval", "空命令"
    command_name = command.strip().split(maxsplit=1)[0].rsplit("/", 1)[-1]
    if command_name in {"pwd", "ls", "cat", "head", "tail", "grep", "rg", "find", "stat", "wc", "git"}:
        return "low", ""
    return "approval", "需要运行时策略分类"


def parse_arguments(raw_arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_arguments) if raw_arguments else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def compact_arguments(args: dict[str, Any], *, limit: int = MAX_INLINE_TEXT) -> str:
    visible = {key: value for key, value in args.items() if key != "intent"}
    if not visible:
        return ""
    return compact_one_line(json.dumps(visible, ensure_ascii=False, default=str), limit)


def compact_one_line(value: Any, limit: int = MAX_INLINE_TEXT) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    remaining = len(text) - max_chars
    return text[:max_chars] + f"\n... <truncated {remaining} chars>"


def _print_read_summary(console: Any, prefix: str, summary: _ReadSummary) -> None:
    detail = f" {summary.detail}" if summary.detail else ""
    _print_segments(
        console,
        [
            (prefix, "tool.branch"),
            (summary.verb, "tool.read"),
            (detail, "tool.arg"),
        ],
    )


def _print_block(console: Any, text: str, *, prefix: str, style: str, max_chars: int) -> None:
    preview = truncate_text(text, max_chars)
    lines = preview.splitlines() or [""]
    for index, line in enumerate(lines):
        line_prefix = prefix if index == 0 else " " * len(prefix)
        _print_text(console, line_prefix + line, style=style)


def _print_highlighted_block(
    console: Any,
    text: str,
    *,
    prefix: str,
    style: str,
    max_chars: int,
    file_path: str = "",
    declared_language: str = "",
) -> None:
    preview = truncate_text(text, max_chars)
    if not preview:
        return
    if Console is None:
        _print_block(console, preview, prefix=prefix, style=style, max_chars=max_chars)
        return
    language = detect_language(preview, file_path=file_path, declared_language=declared_language)
    if language == "text":
        _print_block(console, preview, prefix=prefix, style=style, max_chars=max_chars)
        return
    branch = prefix.rstrip()
    if branch:
        _print_text(console, branch, style="tool.branch")
    render_text = preview if language == "markdown" else _indent_text(preview, " " * max(len(prefix), 2))
    renderable = highlight_for_terminal(
        render_text,
        file_path=file_path,
        declared_language=language,
        style=style,
    )
    console.print(renderable)


def _indent_text(text: str, indentation: str) -> str:
    return "\n".join(indentation + line if line else indentation.rstrip() for line in text.splitlines())


def _print_segments(console: Any, segments: Sequence[tuple[str, str]]) -> None:
    if Text is None:
        print("".join(text for text, _style in segments), flush=True)
        return
    line = Text()
    for text, style in segments:
        line.append(text, style=style)
    console.print(line)


def _print_text(console: Any, text: str, *, style: str) -> None:
    if Text is None:
        print(text, flush=True)
        return
    console.print(Text(text, style=style))


def _console(file: TextIO) -> Any:
    if Console is None or Theme is None:
        return None
    return Console(file=file, soft_wrap=True, highlight=False, theme=_theme())


def _theme() -> Any:
    return Theme(TERMINAL_THEME_STYLES)


def _resolve_file(file: TextIO | None) -> TextIO:
    return file if file is not None else sys.stdout


def _isatty(file: TextIO) -> bool:
    isatty = getattr(file, "isatty", None)
    return bool(isatty and isatty())
