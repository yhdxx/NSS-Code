from __future__ import annotations

import codecs
import os
import re
import select
import shutil
import sys
import termios
import tty
import unicodedata

from mycodingagent.commands import CommandRegistry, CommandSpec

try:
    from wcwidth import wcswidth
except ImportError:  # pragma: no cover - only used before dependencies are installed
    wcswidth = None

ESC_SEQUENCE_TIMEOUT_SECONDS = 0.15
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
READLINE_MARKER_RE = re.compile(r"[\x01\x02]")
MIN_RENDER_COLUMNS = 1
SAFE_COLUMN_MARGIN = 1


def read_user_prompt(prompt: str, command_registry: CommandRegistry | None = None) -> str:
    if not sys.stdin.isatty():
        return input(prompt)
    reader = InteractivePrompt(prompt=prompt, command_registry=command_registry)
    return reader.read()


class InteractivePrompt:
    def __init__(self, *, prompt: str, command_registry: CommandRegistry | None) -> None:
        self.prompt = strip_readline_markers(prompt)
        self.prompt_width = visible_width(self.prompt)
        self.command_registry = command_registry
        self.buffer = ""
        self.rendered_screen_lines: list[str] = []
        self.cursor_row = 0
        self.cursor_column = 0
        self.selected_suggestion_index = 0
        self._input_fd: int | None = None
        self._decoder = codecs.getincrementaldecoder(sys.stdin.encoding or "utf-8")()

    def read(self) -> str:
        self._input_fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setraw(self._input_fd)
            self._render()
            while True:
                char = self._read_char()
                if not char:
                    continue
                if char in {"\r", "\n"}:
                    if self.accept_selected_suggestion():
                        continue
                    return self._finish()
                if char == "\x03":
                    raise KeyboardInterrupt
                if char == "\x04":
                    if not self.buffer:
                        raise EOFError
                    continue
                if char in {"\x7f", "\b"}:
                    self.buffer = self.buffer[:-1]
                    self._render()
                    continue
                if char == "\x1b":
                    self._handle_escape_sequence()
                    continue
                if char.isprintable() or char == "\t":
                    self.buffer += char
                    self._render()
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            self._input_fd = None
            self._decoder.reset()

    def _finish(self) -> str:
        final_text = self.buffer
        self._clear_render()
        sys.stdout.write(self.prompt + final_text + "\r\n")
        sys.stdout.flush()
        return final_text

    def _suggestions(self) -> list[CommandSpec]:
        if self.command_registry is None:
            return []
        return self.command_registry.suggestions(self.buffer)

    def _render(self) -> None:
        suggestions = self._suggestions()
        self.selected_suggestion_index = clamp_selection(self.selected_suggestion_index, len(suggestions))
        hint_lines = self._hint_lines(suggestions)
        lines = [self.prompt + self.buffer, *hint_lines]
        render_columns = safe_render_columns()
        screen = render_screen(lines, render_columns)
        self._clear_render()
        sys.stdout.write("\r\n".join(screen.lines))
        sys.stdout.flush()
        self.rendered_screen_lines = screen.lines
        self.cursor_row = screen.cursor_row
        self.cursor_column = screen.cursor_column
        self._move_cursor_to_input_end()

    def _hint_lines(self, suggestions: list[CommandSpec]) -> list[str]:
        if self.command_registry is None:
            return []
        exact = self.command_registry.exact_command(self.buffer)
        if exact is not None and self.buffer == exact.name:
            return format_command_usage_panel(exact)
        if exact is not None:
            return format_command_argument_usage_panel(exact, self.buffer)
        return [
            format_command_suggestion(spec, selected=index == self.selected_suggestion_index)
            for index, spec in enumerate(suggestions)
        ]

    def _clear_render(self) -> None:
        rendered_rows = len(self.rendered_screen_lines)
        if rendered_rows <= 0:
            return
        sys.stdout.write("\r")
        if self.cursor_row > 0:
            sys.stdout.write(f"\033[{self.cursor_row}A")
        for index in range(rendered_rows):
            sys.stdout.write("\033[2K")
            if index < rendered_rows - 1:
                sys.stdout.write("\033[1B")
        if rendered_rows > 1:
            sys.stdout.write(f"\033[{rendered_rows - 1}A")
        sys.stdout.write("\r")
        sys.stdout.flush()
        self.rendered_screen_lines = []
        self.cursor_row = 0
        self.cursor_column = 0

    def _move_cursor_to_input_end(self) -> None:
        rendered_rows = len(self.rendered_screen_lines)
        if rendered_rows > 1:
            sys.stdout.write(f"\033[{rendered_rows - 1}A")
        if self.cursor_row > 0:
            sys.stdout.write(f"\033[{self.cursor_row}B")
        sys.stdout.write("\r")
        if self.cursor_column > 0:
            sys.stdout.write(f"\033[{self.cursor_column}C")
        sys.stdout.flush()

    def _handle_escape_sequence(self) -> None:
        sequence = self._read_escape_sequence()
        if sequence in {"[A", "OA"}:
            self.move_selection(-1)
            return
        if sequence in {"[B", "OB"}:
            self.move_selection(1)
            return
        if sequence:
            self._drain_escape_sequence()
            return

    def _read_escape_sequence(self) -> str:
        first = self._read_pending_char(timeout=ESC_SEQUENCE_TIMEOUT_SECONDS)
        if first not in {"[", "O"}:
            return first
        second = self._read_pending_char(timeout=ESC_SEQUENCE_TIMEOUT_SECONDS)
        if not second:
            return first
        return first + second

    def _read_pending_char(self, *, timeout: float = 0.0) -> str:
        input_source = self._input_fd if self._input_fd is not None else sys.stdin
        ready, _, _ = select.select([input_source], [], [], timeout)
        if not ready:
            return ""
        return self._read_char()

    def _read_char(self) -> str:
        if self._input_fd is None:
            return sys.stdin.read(1)
        return read_char_from_fd(self._input_fd, self._decoder)

    def _drain_escape_sequence(self) -> None:
        for _ in range(6):
            input_source = self._input_fd if self._input_fd is not None else sys.stdin
            ready, _, _ = select.select([input_source], [], [], 0)
            if not ready:
                return
            self._read_char()

    def move_selection(self, delta: int) -> None:
        suggestions = self._suggestions()
        if not suggestions:
            return
        self.selected_suggestion_index = (self.selected_suggestion_index + delta) % len(suggestions)
        self._render()

    def accept_selected_suggestion(self) -> bool:
        if self.command_registry is not None and self.command_registry.exact_command(self.buffer) is not None:
            return False
        suggestions = self._suggestions()
        if not suggestions:
            return False
        spec = suggestions[self.selected_suggestion_index]
        completed = spec.name + " "
        if self.buffer == completed:
            return False
        self.buffer = completed
        self.selected_suggestion_index = 0
        self._render()
        return True


def format_command_suggestion(spec: CommandSpec, *, selected: bool = False) -> str:
    marker = ">" if selected else " "
    usage = f" {spec.usage}" if spec.usage else ""
    return f"{marker} {spec.name}{usage:<24} {spec.description}"


def format_command_usage_panel(spec: CommandSpec) -> list[str]:
    lines = [f"  {spec.name} - {spec.description}"]
    if spec.usages:
        lines.append("  用法：")
        lines.extend(f"    {spec.name}{usage:<18} {description}" for usage, description in spec.usages)
    elif spec.usage:
        lines.append(f"  用法：{spec.name} {spec.usage}")
    if spec.aliases:
        lines.append("  别名：" + "、".join(spec.aliases))
    if spec.examples:
        lines.append("  示例：" + "；".join(spec.examples))
    return lines


def format_command_argument_usage_panel(spec: CommandSpec, buffer: str) -> list[str]:
    if not spec.usages:
        return []
    prefix = command_argument_prefix(spec, buffer)
    matches = [
        (usage, description)
        for usage, description in spec.usages
        if command_usage_matches_prefix(usage, prefix)
    ]
    if not matches:
        return []
    lines = ["  可用参数："]
    lines.extend(f"    {spec.name}{usage:<18} {description}" for usage, description in matches)
    return lines


def command_argument_prefix(spec: CommandSpec, buffer: str) -> str:
    if buffer == spec.name:
        return ""
    if not buffer.startswith(spec.name + " "):
        return ""
    return buffer[len(spec.name) + 1 :].strip()


def command_usage_matches_prefix(usage: str, prefix: str) -> bool:
    usage_text = usage.strip()
    if not prefix:
        return bool(usage_text)
    return usage_text.startswith(prefix)


def clamp_selection(index: int, suggestion_count: int) -> int:
    if suggestion_count <= 0:
        return 0
    if index < 0:
        return 0
    if index >= suggestion_count:
        return suggestion_count - 1
    return index


def strip_readline_markers(text: str) -> str:
    return READLINE_MARKER_RE.sub("", text)


def visible_width(text: str) -> int:
    plain = ANSI_ESCAPE_RE.sub("", strip_readline_markers(text))
    if not plain:
        return 0
    if wcswidth is not None:
        width = wcswidth(plain)
        if width >= 0:
            return width
    return sum(character_width(char) for char in plain)


def terminal_width() -> int:
    return max(1, shutil.get_terminal_size((80, 24)).columns)


def read_char_from_fd(input_fd: int, decoder: codecs.IncrementalDecoder) -> str:
    while True:
        chunk = os.read(input_fd, 1)
        if not chunk:
            return ""
        char = decoder.decode(chunk)
        if char:
            return char


def read_escape_sequence_from_fd(
    input_fd: int,
    decoder: codecs.IncrementalDecoder,
    *,
    timeout: float = ESC_SEQUENCE_TIMEOUT_SECONDS,
) -> str:
    ready, _, _ = select.select([input_fd], [], [], timeout)
    if not ready:
        return ""
    first = read_char_from_fd(input_fd, decoder)
    if first not in {"[", "O"}:
        return first
    ready, _, _ = select.select([input_fd], [], [], timeout)
    if not ready:
        return first
    return first + read_char_from_fd(input_fd, decoder)


def safe_render_columns() -> int:
    return max(MIN_RENDER_COLUMNS, terminal_width() - SAFE_COLUMN_MARGIN)


class RenderedScreen:
    def __init__(self, *, lines: list[str], cursor_row: int, cursor_column: int) -> None:
        self.lines = lines
        self.cursor_row = cursor_row
        self.cursor_column = cursor_column


def render_screen(lines: list[str], columns: int) -> RenderedScreen:
    screen_lines: list[str] = []
    cursor_row = 0
    cursor_column = 0
    for index, line in enumerate(lines):
        wrapped = hard_wrap_ansi(line, columns)
        if index == 0:
            cursor_row = max(0, len(wrapped) - 1)
            cursor_column = visible_width(wrapped[-1]) if wrapped else 0
        screen_lines.extend(wrapped)
    return RenderedScreen(lines=screen_lines, cursor_row=cursor_row, cursor_column=cursor_column)


def hard_wrap_ansi(text: str, columns: int) -> list[str]:
    columns = max(MIN_RENDER_COLUMNS, columns)
    parts: list[str] = []
    line_parts: list[str] = []
    line_width = 0
    index = 0
    while index < len(text):
        match = ANSI_ESCAPE_RE.match(text, index)
        if match is not None:
            line_parts.append(match.group(0))
            index = match.end()
            continue

        char = text[index]
        char_width = visible_width(char)
        if char_width > columns:
            char_width = columns
        if line_width > 0 and line_width + char_width > columns:
            parts.append("".join(line_parts))
            line_parts = []
            line_width = 0
        line_parts.append(char)
        line_width += char_width
        index += 1
    parts.append("".join(line_parts))
    return parts


def character_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    codepoint = ord(char)
    if codepoint < 32 or 0x7F <= codepoint < 0xA0:
        return 0
    if unicodedata.category(char) in {"Mn", "Me", "Cf"}:
        return 0
    if unicodedata.east_asian_width(char) in {"W", "F"}:
        return 2
    return 1
