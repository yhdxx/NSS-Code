from __future__ import annotations

import codecs
import sys
import termios
import tty
from collections.abc import Sequence

from mycodingagent.memory.models import WorkspaceCheckpoint
from mycodingagent.terminal_ui.input import (
    read_char_from_fd,
    read_escape_sequence_from_fd,
    render_screen,
    safe_render_columns,
)


def select_checkpoint_interactively(
    checkpoints: Sequence[WorkspaceCheckpoint],
    *,
    limit: int = 20,
) -> str:
    options = list(reversed(checkpoints[-limit:]))
    labels = [format_checkpoint_option(checkpoint) for checkpoint in options]
    selected = _select_interactively(
        labels,
        prompt="请选择要回退到的轮次（↑/↓ 选择，Enter 确认，Esc/Ctrl+C 取消）：",
    )
    if selected < 0:
        if not sys.stdin.isatty():
            print("当前终端不支持方向键选择。", flush=True)
            for label in labels:
                print(f"  {label}", flush=True)
        return ""
    return options[selected].checkpoint_id


def select_rewind_scope_interactively() -> str:
    scopes = (
        ("both", "代码和会话"),
        ("conversation", "仅会话（保留 workspace snapshot）"),
        ("code", "仅代码"),
    )
    selected = _select_interactively(
        [label for _, label in scopes],
        prompt="请选择回退范围（↑/↓ 选择，Enter 确认，Esc/Ctrl+C 取消）：",
    )
    return scopes[selected][0] if selected >= 0 else ""


def format_checkpoint_option(checkpoint: WorkspaceCheckpoint) -> str:
    prompt = " ".join(checkpoint.prompt.split())
    return f"turn {checkpoint.turn_index} | {checkpoint.checkpoint_id[:8]} | {prompt[:80]}"


def _select_interactively(labels: Sequence[str], *, prompt: str) -> int:
    if not labels or not sys.stdin.isatty():
        return -1
    selected = 0
    rendered_rows = 0
    input_fd = sys.stdin.fileno()
    decoder = codecs.getincrementaldecoder(sys.stdin.encoding or "utf-8")()
    hidden_cursor = False
    try:
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(input_fd)
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
        hidden_cursor = True
        rendered_rows = _render_selector(labels, selected, prompt=prompt, previous_row_count=rendered_rows)
        while True:
            char = read_char_from_fd(input_fd, decoder)
            if char in {"\r", "\n"}:
                _clear_selector(rendered_rows)
                return selected
            if char == "\x03":
                _clear_selector(rendered_rows)
                return -1
            if char != "\x1b":
                continue
            sequence = read_escape_sequence_from_fd(input_fd, decoder, timeout=0.5)
            if sequence == "[A":
                selected = (selected - 1) % len(labels)
            elif sequence == "[B":
                selected = (selected + 1) % len(labels)
            else:
                _clear_selector(rendered_rows)
                return -1
            rendered_rows = _render_selector(
                labels,
                selected,
                prompt=prompt,
                previous_row_count=rendered_rows,
            )
    finally:
        if "old_settings" in locals():
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        decoder.reset()
        if hidden_cursor:
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()


def _render_selector(
    labels: Sequence[str],
    selected: int,
    *,
    prompt: str,
    previous_row_count: int,
) -> int:
    if previous_row_count > 0:
        _clear_selector(previous_row_count)
    lines = [prompt]
    lines.extend(f"{'>' if index == selected else ' '} {label}" for index, label in enumerate(labels))
    screen = render_screen(lines, safe_render_columns())
    sys.stdout.write("\r")
    sys.stdout.write("\r\n".join(screen.lines))
    sys.stdout.write("\r")
    sys.stdout.flush()
    return len(screen.lines)


def _clear_selector(rendered_row_count: int) -> None:
    if rendered_row_count <= 0:
        return
    sys.stdout.write("\r")
    if rendered_row_count > 1:
        sys.stdout.write(f"\033[{rendered_row_count - 1}A")
    for index in range(rendered_row_count):
        sys.stdout.write("\033[2K")
        if index < rendered_row_count - 1:
            sys.stdout.write("\033[1B")
    sys.stdout.write("\r")
    sys.stdout.flush()
