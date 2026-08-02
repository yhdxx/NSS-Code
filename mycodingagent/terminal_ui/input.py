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
from mycodingagent.terminal_ui.clipboard import copy_to_clipboard, paste_from_clipboard
from mycodingagent.terminal_ui.input_document import InputDocument
from mycodingagent.terminal_ui.keymap import action_for_key, load_keymap

try:
    from wcwidth import wcswidth
except ImportError:  # pragma: no cover - only used before dependencies are installed
    wcswidth = None

ESC_SEQUENCE_TIMEOUT_SECONDS = 0.15
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
READLINE_MARKER_RE = re.compile(r"[\x01\x02]")
MIN_RENDER_COLUMNS = 1
SAFE_COLUMN_MARGIN = 1
BRACKETED_PASTE_START = "[200~"
BRACKETED_PASTE_END = "\x1b[201~"
ANSI_RESET = "\033[0m"
INPUT_BOX_STYLE = "\033[48;5;94m\033[97m"
INPUT_TEXT_STYLE = "\033[97m"
INPUT_PASTE_STYLE = "\033[94m"
INPUT_SELECTION_STYLE = "\033[48;5;240m\033[97m"
CURSOR_BRIGHT_WHITE = "\033]12;#FFFFFF\a"
CURSOR_RESET = "\033]112\a"
INDENT_TEXT = "    "


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
        self._document = InputDocument()
        self.cursor_index = 0
        self.selection_anchor: int | None = None
        self.keymap = load_keymap()
        self.rendered_screen_lines: list[str] = []
        self.cursor_row = 0
        self.cursor_column = 0
        self.selected_suggestion_index = 0
        self._input_fd: int | None = None
        self._decoder = codecs.getincrementaldecoder(sys.stdin.encoding or "utf-8")()

    @property
    def buffer(self) -> str:
        return self._document.text

    @buffer.setter
    def buffer(self, value: str) -> None:
        self._set_buffer(value, len(value))

    def read(self) -> str:
        self._input_fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setraw(self._input_fd)
            self._enable_bracketed_paste()
            self._render()
            while True:
                char = self._read_char()
                if not char:
                    continue
                if char == "\x04":
                    if not self.buffer:
                        raise EOFError
                    continue
                if char == "\x1b":
                    self._handle_escape_sequence()
                    continue
                action = action_for_key(self.keymap, key_name_for_char(char))
                if action:
                    if self._handle_action(action):
                        return self._finish()
                    continue
                if char.isprintable() or char == "\t":
                    self._insert_text(char)
        finally:
            self._disable_bracketed_paste()
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            self._input_fd = None
            self._decoder.reset()

    def _finish(self) -> str:
        final_text = self.buffer
        self._clear_render()
        sys.stdout.write(format_prompt_echo(self.prompt, self.prompt_width, final_text) + "\r\n")
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
        render_columns = safe_render_columns()
        styled_buffer = self._styled_display_buffer()
        cursor_index = raw_index_for_visible_index(
            styled_buffer,
            self._document.display_index_for_text_index(self.cursor_index),
        )
        input_screen = render_prompt_buffer(
            self.prompt,
            self.prompt_width,
            styled_buffer,
            cursor_index,
            [],
            render_columns,
        )
        screen = render_prompt_buffer(
            self.prompt,
            self.prompt_width,
            styled_buffer,
            cursor_index,
            hint_lines,
            render_columns,
        )
        screen.lines = style_input_box_lines(screen.lines, input_row_count=len(input_screen.lines), columns=render_columns)
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
        if sequence == BRACKETED_PASTE_START:
            self._insert_paste(normalize_pasted_text(self._read_bracketed_paste()))
            return
        key_name = key_name_for_escape_sequence(sequence)
        action = action_for_key(self.keymap, key_name)
        if action:
            self._handle_action(action)
            return
        if sequence:
            self._drain_escape_sequence()
            return

    def _read_escape_sequence(self) -> str:
        first = self._read_pending_char(timeout=ESC_SEQUENCE_TIMEOUT_SECONDS)
        if first not in {"[", "O"}:
            return first
        sequence = first
        for _ in range(12):
            char = self._read_pending_char(timeout=ESC_SEQUENCE_TIMEOUT_SECONDS)
            if not char:
                return sequence
            sequence += char
            if is_escape_sequence_final_char(char):
                return sequence
        return sequence

    def _read_bracketed_paste(self) -> str:
        text = ""
        while True:
            char = self._read_char()
            if not char:
                continue
            text += char
            if text.endswith(BRACKETED_PASTE_END):
                return text[: -len(BRACKETED_PASTE_END)]

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
        self._set_buffer(completed, len(completed))
        self.selected_suggestion_index = 0
        self._render()
        return True

    def _set_buffer(self, value: str, cursor_index: int | None = None) -> None:
        self._document = InputDocument.from_text(value)
        if cursor_index is None:
            cursor_index = self.cursor_index
        self.cursor_index = clamp_cursor_index(cursor_index, len(self.buffer))
        self.selection_anchor = None

    def _insert_text(self, text: str) -> None:
        if not text:
            return
        self._delete_selection_if_needed(render=False)
        self._document, self.cursor_index = self._document.insert_text(self.cursor_index, text)
        self.selection_anchor = None
        self.selected_suggestion_index = 0
        self._render()

    def _insert_paste(self, text: str) -> None:
        if not text:
            return
        self._delete_selection_if_needed(render=False)
        self._document, self.cursor_index = self._document.insert_paste(self.cursor_index, text)
        self.selection_anchor = None
        self.selected_suggestion_index = 0
        self._render()

    def _backspace(self) -> None:
        if self._delete_selection_if_needed():
            return
        if self.cursor_index <= 0:
            return
        self._document, self.cursor_index = self._document.delete_previous(self.cursor_index)
        self._render()

    def _delete_at_cursor(self) -> None:
        if self._delete_selection_if_needed():
            return
        if self.cursor_index >= len(self.buffer):
            return
        self._document, self.cursor_index = self._document.delete_at(self.cursor_index)
        self._render()

    def _delete_selection_if_needed(self, *, render: bool = True) -> bool:
        selection = self._selection_range()
        if selection is None:
            return False
        self._document, self.cursor_index = self._document.delete_range(*selection)
        self.selection_anchor = None
        if render:
            self._render()
        return True

    def _selection_range(self) -> tuple[int, int] | None:
        if self.selection_anchor is None or self.selection_anchor == self.cursor_index:
            return None
        start, end = sorted((self.selection_anchor, self.cursor_index))
        return start, end

    def _clear_selection(self) -> bool:
        if self.selection_anchor is None:
            return False
        self.selection_anchor = None
        self._render()
        return True

    def _handle_action(self, action: str) -> bool:
        if action == "submit":
            if self.accept_selected_suggestion():
                return False
            return True
        if action == "newline":
            self._insert_text("\n")
            return False
        if action == "copy_or_interrupt":
            selection = self._selection_range()
            if selection is None:
                raise KeyboardInterrupt
            copy_to_clipboard(self._document.selected_text(*selection))
            return False
        if action == "paste":
            pasted = paste_from_clipboard()
            if pasted:
                self._insert_paste(normalize_pasted_text(pasted))
            return False
        if action == "select_all":
            self.selection_anchor = 0
            self.cursor_index = len(self.buffer)
            self._render()
            return False
        if action == "indent":
            self._indent_selection_or_line()
            return False
        if action == "unindent":
            self._unindent_selection_or_line()
            return False
        if action == "line_start":
            self._move_cursor_to_line_start()
            return False
        if action == "line_end":
            self._move_cursor_to_line_end()
            return False
        if action == "delete_line_start":
            self._delete_to_line_start()
            return False
        if action == "delete_line_end":
            self._delete_to_line_end()
            return False
        if action == "delete_word_backward":
            self._delete_word_backward()
            return False
        if action == "escape":
            self._clear_selection()
            return False
        if action == "backspace":
            self._backspace()
            return False
        if action == "delete":
            self._delete_at_cursor()
            return False
        if action == "left":
            self._move_cursor(-1)
            return False
        if action == "right":
            self._move_cursor(1)
            return False
        if action == "up":
            if self._suggestions():
                self.move_selection(-1)
            else:
                self._move_cursor_vertical(-1)
            return False
        if action == "down":
            if self._suggestions():
                self.move_selection(1)
            else:
                self._move_cursor_vertical(1)
            return False
        if action == "select_left":
            self._move_cursor(-1, extend_selection=True)
            return False
        if action == "select_right":
            self._move_cursor(1, extend_selection=True)
            return False
        if action == "select_up":
            self._move_cursor_vertical(-1, extend_selection=True)
            return False
        if action == "select_down":
            self._move_cursor_vertical(1, extend_selection=True)
            return False
        return False

    def _styled_display_buffer(self) -> str:
        return self._document.styled_display_text(
            text_style=INPUT_TEXT_STYLE,
            paste_style=INPUT_PASTE_STYLE,
            selection_style=INPUT_SELECTION_STYLE,
            reset_style=INPUT_BOX_STYLE,
            selection_range=self._selection_range(),
        )

    def _set_document(self, document: InputDocument, cursor_index: int) -> None:
        self._document = document
        self.cursor_index = self._document.normalize_cursor(cursor_index)
        self.selection_anchor = None

    def _indent_selection_or_line(self) -> None:
        starts = self._line_starts_for_selection_or_cursor()
        document = self._document
        cursor_shift = 0
        anchor_shift = 0
        for start in reversed(starts):
            document, _ = document.insert_text(start, INDENT_TEXT)
            if start <= self.cursor_index:
                cursor_shift += len(INDENT_TEXT)
            if self.selection_anchor is not None and start <= self.selection_anchor:
                anchor_shift += len(INDENT_TEXT)
        self._document = document
        self.cursor_index += cursor_shift
        if self.selection_anchor is not None:
            self.selection_anchor += anchor_shift
        self._render()

    def _unindent_selection_or_line(self) -> None:
        starts = self._line_starts_for_selection_or_cursor()
        document = self._document
        cursor_shift = 0
        anchor_shift = 0
        for start in reversed(starts):
            text = document.text
            remove = 0
            if text.startswith(INDENT_TEXT, start):
                remove = len(INDENT_TEXT)
            elif start < len(text) and text[start] == "\t":
                remove = 1
            if not remove:
                continue
            document, _ = document.delete_range(start, start + remove)
            if start < self.cursor_index:
                cursor_shift -= min(remove, self.cursor_index - start)
            if self.selection_anchor is not None and start < self.selection_anchor:
                anchor_shift -= min(remove, self.selection_anchor - start)
        self._document = document
        self.cursor_index = clamp_cursor_index(self.cursor_index + cursor_shift, len(self.buffer))
        if self.selection_anchor is not None:
            self.selection_anchor = clamp_cursor_index(self.selection_anchor + anchor_shift, len(self.buffer))
        self._render()

    def _line_starts_for_selection_or_cursor(self) -> list[int]:
        text = self.buffer
        selection = self._selection_range()
        if selection is None:
            start = text.rfind("\n", 0, self.cursor_index) + 1
            return [start]
        start, end = selection
        line_start = text.rfind("\n", 0, start) + 1
        line_end = end
        starts = [line_start]
        position = line_start
        while True:
            newline = text.find("\n", position, line_end)
            if newline < 0:
                return starts
            starts.append(newline + 1)
            position = newline + 1

    def _delete_to_line_start(self) -> None:
        line_start = self.buffer.rfind("\n", 0, self.cursor_index) + 1
        if line_start == self.cursor_index:
            return
        self._document, self.cursor_index = self._document.delete_range(line_start, self.cursor_index)
        self.selection_anchor = None
        self._render()

    def _delete_to_line_end(self) -> None:
        cursor = self.cursor_index
        line_end = self.buffer.find("\n", cursor)
        if line_end < 0:
            line_end = len(self.buffer)
        if line_end == cursor:
            return
        self._document, self.cursor_index = self._document.delete_range(cursor, line_end)
        self.selection_anchor = None
        self._render()

    def _delete_word_backward(self) -> None:
        if self._delete_selection_if_needed():
            return
        text = self.buffer
        cursor = self._document.normalize_cursor(self.cursor_index, direction=-1)
        if cursor <= 0:
            return
        start = cursor
        while start > 0 and text[start - 1].isspace() and text[start - 1] != "\n":
            start -= 1
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        if start == cursor:
            start = cursor - 1
        self._document, self.cursor_index = self._document.delete_range(start, cursor)
        self.selection_anchor = None
        self._render()

    def _move_cursor(self, delta: int, *, extend_selection: bool = False) -> None:
        new_index = self._document.move_cursor(self.cursor_index, delta)
        if new_index == self.cursor_index:
            return
        if extend_selection and self.selection_anchor is None:
            self.selection_anchor = self.cursor_index
        self.cursor_index = new_index
        if not extend_selection:
            self.selection_anchor = None
        self._render()

    def _move_cursor_to_line_start(self) -> None:
        line_start = self.buffer.rfind("\n", 0, self.cursor_index) + 1
        if line_start == self.cursor_index:
            return
        self.cursor_index = line_start
        self.selection_anchor = None
        self._render()

    def _move_cursor_to_line_end(self) -> None:
        line_end = self.buffer.find("\n", self.cursor_index)
        if line_end < 0:
            line_end = len(self.buffer)
        if line_end == self.cursor_index:
            return
        self.cursor_index = line_end
        self.selection_anchor = None
        self._render()

    def _move_cursor_vertical(self, delta: int, *, extend_selection: bool = False) -> None:
        display_text = self._document.display_text
        display_cursor = self._document.display_index_for_text_index(self.cursor_index)
        target_display_index = visual_vertical_cursor_index(
            display_text,
            display_cursor,
            delta,
            prompt_width=self.prompt_width,
            columns=safe_render_columns(),
        )
        target_index = self._document.text_index_for_display_index(target_display_index)
        if target_index == self.cursor_index:
            return
        if extend_selection and self.selection_anchor is None:
            self.selection_anchor = self.cursor_index
        self.cursor_index = target_index
        if not extend_selection:
            self.selection_anchor = None
        self._render()

    def _enable_bracketed_paste(self) -> None:
        sys.stdout.write(CURSOR_BRIGHT_WHITE)
        sys.stdout.write("\033[?2004h")
        sys.stdout.flush()

    def _disable_bracketed_paste(self) -> None:
        sys.stdout.write("\033[?2004l")
        sys.stdout.write(CURSOR_RESET)
        sys.stdout.flush()


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


def clamp_cursor_index(index: int, buffer_length: int) -> int:
    if index < 0:
        return 0
    if index > buffer_length:
        return buffer_length
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
    sequence = first
    for _ in range(12):
        char = read_char_from_fd(input_fd, decoder)
        sequence += char
        if is_escape_sequence_final_char(char):
            return sequence
        ready, _, _ = select.select([input_fd], [], [], timeout)
        if not ready:
            return sequence
    return sequence


def is_escape_sequence_final_char(char: str) -> bool:
    return len(char) == 1 and 0x40 <= ord(char) <= 0x7E


def normalize_pasted_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def key_name_for_char(char: str) -> str:
    return {
        "\r": "enter",
        "\n": "ctrl+j",
        "\x03": "ctrl+c",
        "\x16": "ctrl+v",
        "\x01": "ctrl+a",
        "\x05": "ctrl+e",
        "\x0b": "ctrl+k",
        "\x15": "ctrl+u",
        "\x7f": "backspace",
        "\b": "backspace",
        "\t": "tab",
    }.get(char, "")


def key_name_for_escape_sequence(sequence: str) -> str:
    if sequence in {"[1;2A", "[A;2"}:
        return "shift+up"
    if sequence in {"[1;2B", "[B;2"}:
        return "shift+down"
    if sequence in {"[1;2D", "[D;2"}:
        return "shift+left"
    if sequence in {"[1;2C", "[C;2"}:
        return "shift+right"
    if sequence in {"[A", "OA"}:
        return "up"
    if sequence in {"[B", "OB"}:
        return "down"
    if sequence in {"[D", "OD"}:
        return "left"
    if sequence in {"[C", "OC"}:
        return "right"
    if sequence in {"[H", "OH", "[1~", "[7~"}:
        return "home"
    if sequence in {"[F", "OF", "[4~", "[8~"}:
        return "end"
    if sequence == "[3~":
        return "delete"
    if sequence == "[Z":
        return "shift+tab"
    if sequence in {"\x7f", "\b"}:
        return "alt+backspace"
    if len(sequence) == 1 and sequence.isprintable():
        return f"alt+{sequence.lower()}"
    if not sequence:
        return "esc"
    return ""


def format_prompt_echo(prompt: str, prompt_width: int, text: str) -> str:
    continuation = " " * prompt_width
    return prompt + normalize_pasted_text(text).replace("\n", "\r\n" + continuation)


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


def render_prompt_buffer(
    prompt: str,
    prompt_width: int,
    buffer: str,
    cursor_index: int,
    hint_lines: list[str],
    columns: int,
) -> RenderedScreen:
    buffer_lines = buffer.split("\n")
    cursor_index = clamp_cursor_index(cursor_index, len(buffer))
    before_cursor = buffer[:cursor_index]
    cursor_buffer_line = before_cursor.count("\n")
    cursor_line_prefix = before_cursor.rsplit("\n", 1)[-1]
    screen_lines: list[str] = []
    cursor_row = 0
    cursor_column = 0

    for index, line in enumerate(buffer_lines):
        prefix = prompt if index == 0 else " " * prompt_width
        if index == cursor_buffer_line:
            cursor_wrapped = hard_wrap_ansi(prefix + cursor_line_prefix, columns)
            cursor_row = len(screen_lines) + max(0, len(cursor_wrapped) - 1)
            cursor_column = visible_width(cursor_wrapped[-1]) if cursor_wrapped else 0
        screen_lines.extend(hard_wrap_ansi(prefix + line, columns))

    for hint_line in hint_lines:
        screen_lines.extend(hard_wrap_ansi(hint_line, columns))

    return RenderedScreen(lines=screen_lines, cursor_row=cursor_row, cursor_column=cursor_column)


def style_input_box_lines(lines: list[str], *, input_row_count: int, columns: int) -> list[str]:
    styled: list[str] = []
    for index, line in enumerate(lines):
        if index >= input_row_count:
            styled.append(line)
            continue
        padding = max(0, columns - visible_width(line))
        styled.append(INPUT_BOX_STYLE + line + (" " * padding) + ANSI_RESET)
    return styled


def vertical_cursor_index(buffer: str, cursor_index: int, delta: int) -> int:
    if delta == 0 or "\n" not in buffer:
        return cursor_index
    lines = buffer.split("\n")
    cursor_index = clamp_cursor_index(cursor_index, len(buffer))
    line_index, column_offset = cursor_line_and_offset(buffer, cursor_index)
    target_line_index = line_index + delta
    if target_line_index < 0 or target_line_index >= len(lines):
        return cursor_index
    desired_column = visible_width(lines[line_index][:column_offset])
    target_offset = char_index_for_visible_column(lines[target_line_index], desired_column)
    return absolute_index_for_line_offset(lines, target_line_index, target_offset)


def visual_vertical_cursor_index(
    buffer: str,
    cursor_index: int,
    delta: int,
    *,
    prompt_width: int,
    columns: int,
) -> int:
    if delta == 0:
        return cursor_index
    positions = visual_cursor_positions(buffer, prompt_width=prompt_width, columns=columns)
    cursor_index = clamp_cursor_index(cursor_index, len(buffer))
    current_row, current_column = positions[cursor_index]
    target_row = current_row + delta
    candidates = [
        (index, column)
        for index, (row, column) in enumerate(positions)
        if row == target_row
    ]
    if not candidates:
        return cursor_index
    before_or_at = [(index, column) for index, column in candidates if column <= current_column]
    if before_or_at:
        return max(before_or_at, key=lambda item: item[1])[0]
    return min(candidates, key=lambda item: item[1])[0]


def visual_cursor_positions(buffer: str, *, prompt_width: int, columns: int) -> list[tuple[int, int]]:
    columns = max(MIN_RENDER_COLUMNS, columns)
    positions: list[tuple[int, int]] = [(0, 0)] * (len(buffer) + 1)
    row = 0
    column = 0
    absolute_index = 0
    lines = buffer.split("\n")
    for line_index, line in enumerate(lines):
        prefix = " " * prompt_width
        if line_index > 0:
            column = 0
        for char in prefix:
            row, column = advance_visual_position(row, column, visible_width(char), columns)
        for char in line:
            positions[absolute_index] = (row, column)
            row, column = advance_visual_position(row, column, visible_width(char), columns)
            absolute_index += 1
        positions[absolute_index] = (row, column)
        if line_index < len(lines) - 1:
            absolute_index += 1
            row += 1
            column = 0
    positions[len(buffer)] = (row, column)
    return positions


def advance_visual_position(row: int, column: int, char_width: int, columns: int) -> tuple[int, int]:
    char_width = max(0, min(char_width, columns))
    if column > 0 and column + char_width > columns:
        row += 1
        column = 0
    return row, column + char_width


def cursor_line_and_offset(buffer: str, cursor_index: int) -> tuple[int, int]:
    before_cursor = buffer[:cursor_index]
    line_index = before_cursor.count("\n")
    line_start = before_cursor.rfind("\n") + 1
    return line_index, cursor_index - line_start


def char_index_for_visible_column(text: str, column: int) -> int:
    width = 0
    for index, char in enumerate(text):
        char_width = visible_width(char)
        if width + char_width > column:
            return index
        width += char_width
    return len(text)


def absolute_index_for_line_offset(lines: list[str], line_index: int, offset: int) -> int:
    return sum(len(line) + 1 for line in lines[:line_index]) + offset


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


def raw_index_for_visible_index(text: str, visible_index: int) -> int:
    visible_index = max(0, visible_index)
    visible_seen = 0
    raw_index = 0
    while raw_index < len(text):
        match = ANSI_ESCAPE_RE.match(text, raw_index)
        if match is not None:
            raw_index = match.end()
            continue
        if visible_seen >= visible_index:
            return raw_index
        visible_seen += 1
        raw_index += 1
    return len(text)


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
