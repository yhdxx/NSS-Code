from __future__ import annotations

import codecs
import sys
import termios
import tty

from mycodingagent.memory import MemoryRuntime, SessionListItem
from mycodingagent.terminal_ui.input import (
    read_char_from_fd,
    read_escape_sequence_from_fd,
    render_screen,
    safe_render_columns,
)


def select_session_interactively(
    memory_runtime: MemoryRuntime,
    *,
    limit: int = 20,
    include_all: bool = False,
    action: str = "恢复",
) -> str:
    sessions = memory_runtime.list_sessions(limit=limit, include_all=include_all)
    if not sessions:
        if include_all:
            print(f"暂无可{action}会话。", flush=True)
        else:
            command = command_for_session_action(action)
            print(f"当前工作目录下没有历史会话。可使用 {command} --all 查看其他工作目录会话。", flush=True)
            migrated_sessions = memory_runtime.list_migrated_workspace_sessions(limit=limit)
            if migrated_sessions:
                print(f"检测到可能来自迁移前同一项目的会话，可使用 {command} --all 查看。", flush=True)
        return ""
    if not sys.stdin.isatty():
        command = command_for_session_action(action)
        print(f"当前终端不支持方向键选择，使用 {command} <session_id> {action}指定会话。", flush=True)
        print_session_options(sessions, include_workspace=include_all)
        return ""

    selected = 0
    hidden_cursor = False
    rendered_selector_rows = 0
    input_fd = sys.stdin.fileno()
    decoder = codecs.getincrementaldecoder(sys.stdin.encoding or "utf-8")()
    try:
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(input_fd)
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
        hidden_cursor = True
        rendered_selector_rows = render_session_selector(
            sessions,
            selected,
            previous_row_count=rendered_selector_rows,
            include_workspace=include_all,
            action=action,
        )
        while True:
            char = read_char_from_fd(input_fd, decoder)
            if char in {"\r", "\n"}:
                clear_session_selector(rendered_selector_rows)
                return sessions[selected].session_id
            if char == "\x03":
                clear_session_selector(rendered_selector_rows)
                print(f"已取消{action}会话。", flush=True)
                return ""
            if char == "\x1b":
                seq = read_escape_sequence_from_fd(input_fd, decoder, timeout=0.5)
                if not seq:
                    clear_session_selector(rendered_selector_rows)
                    print(f"已取消{action}会话。", flush=True)
                    return ""
                if seq == "[A":
                    selected = (selected - 1) % len(sessions)
                elif seq == "[B":
                    selected = (selected + 1) % len(sessions)
                else:
                    clear_session_selector(rendered_selector_rows)
                    print(f"已取消{action}会话。", flush=True)
                    return ""
                rendered_selector_rows = render_session_selector(
                    sessions,
                    selected,
                    previous_row_count=rendered_selector_rows,
                    include_workspace=include_all,
                    action=action,
                )
    finally:
        if "old_settings" in locals():
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        decoder.reset()
        if hidden_cursor:
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()


def render_session_selector(
    sessions: list[SessionListItem],
    selected: int,
    *,
    previous_row_count: int = 0,
    include_workspace: bool = False,
    action: str = "恢复",
) -> int:
    if previous_row_count > 0:
        clear_session_selector(previous_row_count)
    logical_lines = [f"请选择要{action}的会话（↑/↓ 选择，Enter 确认，Esc/Ctrl+C 取消）："]
    logical_lines.extend(
        format_session_option(session, selected=index == selected, include_workspace=include_workspace)
        for index, session in enumerate(sessions)
    )
    screen = render_screen(logical_lines, safe_render_columns())
    sys.stdout.write("\r")
    sys.stdout.write("\r\n".join(screen.lines))
    if len(screen.lines) > 1:
        sys.stdout.write(f"\033[{len(screen.lines) - 1}A")
    sys.stdout.write("\r")
    sys.stdout.flush()
    return len(screen.lines)


def clear_session_selector(rendered_row_count: int) -> None:
    if rendered_row_count <= 0:
        return
    sys.stdout.write("\r")
    for index in range(rendered_row_count):
        sys.stdout.write("\033[2K")
        if index < rendered_row_count - 1:
            sys.stdout.write("\033[1B")
    if rendered_row_count > 1:
        sys.stdout.write(f"\033[{rendered_row_count - 1}A")
    sys.stdout.write("\r")
    sys.stdout.flush()


def print_session_options(sessions: list[SessionListItem], *, include_workspace: bool = False) -> None:
    for session in sessions:
        print(format_session_option(session, selected=False, include_workspace=include_workspace), flush=True)


def command_for_session_action(action: str) -> str:
    return {
        "恢复": "/resume",
        "分叉": "/fork",
        "清空": "/clear",
        "删除": "/delete",
    }.get(action, "/resume")


def format_session_option(session: SessionListItem, *, selected: bool, include_workspace: bool = False) -> str:
    marker = ">" if selected else " "
    short_id = session.session_id[:8]
    workspace = f" [{session.workspace_label or session.workspace_root}]" if include_workspace else ""
    return f"{marker} [{short_id}]{workspace} {session.preview}（{session.message_count} 条消息）"
