from __future__ import annotations

import codecs
import os

from mycodingagent.terminal_ui.input import (
    InteractivePrompt,
    clamp_selection,
    format_prompt_echo,
    format_command_argument_usage_panel,
    format_command_suggestion,
    format_command_usage_panel,
    hard_wrap_ansi,
    normalize_pasted_text,
    read_escape_sequence_from_fd,
    render_prompt_buffer,
    render_screen,
    safe_render_columns,
    strip_readline_markers,
    vertical_cursor_index,
    visible_width,
)
from mycodingagent.commands import CommandRegistry, CommandResult, CommandSpec


async def noop_handler(context, arguments):
    return CommandResult()


def test_format_command_suggestion_marks_selected_item():
    spec = CommandSpec(
        name="/resume",
        description="恢复历史会话",
        usage="[session_id|--all|--help]",
        handler=noop_handler,
    )

    assert format_command_suggestion(spec, selected=True).startswith("> /resume")
    assert format_command_suggestion(spec, selected=False).startswith("  /resume")
    assert "[session_id|--all|--help]" in format_command_suggestion(spec)


def test_format_command_usage_panel_lists_each_usage():
    spec = CommandSpec(
        name="/resume",
        description="恢复历史会话",
        usages=(
            ("", "显示当前工作目录下的历史会话"),
            (" --all", "显示所有工作目录下的历史会话"),
            (" <session_id>", "直接恢复指定会话 id"),
        ),
        handler=noop_handler,
    )

    panel = "\n".join(format_command_usage_panel(spec))

    assert "/resume                   显示当前工作目录下的历史会话" in panel
    assert "/resume --all             显示所有工作目录下的历史会话" in panel
    assert "/resume <session_id>      直接恢复指定会话 id" in panel


def test_delete_usage_panel_lists_expiry_cleanup():
    spec = CommandSpec(
        name="/delete",
        description="删除历史会话",
        usages=(
            ("", "显示当前工作目录下的历史会话"),
            (" --all", "显示所有工作目录下的历史会话"),
            (" <session_id>", "直接删除指定会话 id"),
            (" --expired", "立即清理超过有效期未访问的会话"),
        ),
        handler=noop_handler,
    )

    panel = "\n".join(format_command_usage_panel(spec))

    assert "/delete                   显示当前工作目录下的历史会话" in panel
    assert "/delete <session_id>      直接删除指定会话 id" in panel
    assert "/delete --expired         立即清理超过有效期未访问的会话" in panel


def test_exact_command_shows_usage_panel_instead_of_simple_suggestion():
    registry = CommandRegistry()
    registry.register(
        CommandSpec(
            name="/resume",
            description="恢复历史会话",
            usages=(("", "显示当前工作目录下的历史会话"),),
            handler=noop_handler,
        )
    )
    prompt = InteractivePrompt(prompt="User: ", command_registry=registry)
    prompt.buffer = "/resume"

    hints = prompt._hint_lines(prompt._suggestions())

    assert any("用法：" in line for line in hints)
    assert any("显示当前工作目录下的历史会话" in line for line in hints)


def test_command_space_argument_shows_available_usage_options():
    registry = CommandRegistry()
    registry.register(
        CommandSpec(
            name="/resume",
            description="恢复历史会话",
            usages=(
                ("", "显示当前工作目录下的历史会话"),
                (" --all", "显示所有工作目录下的历史会话"),
                (" <session_id>", "直接恢复指定会话 id"),
            ),
            handler=noop_handler,
        )
    )
    prompt = InteractivePrompt(prompt="User: ", command_registry=registry)
    prompt.buffer = "/resume "

    hints = "\n".join(prompt._hint_lines(prompt._suggestions()))

    assert "可用参数：" in hints
    assert "/resume --all" in hints
    assert "/resume <session_id>" in hints
    assert "/resume                   显示当前工作目录下的历史会话" not in hints


def test_command_argument_hides_usage_when_prefix_matches_nothing():
    spec = CommandSpec(
        name="/delete",
        description="删除历史会话",
        usages=(
            (" --all", "显示所有工作目录下的历史会话"),
            (" --workspace-all", "删除当前工作目录下的全部会话"),
            (" <session_id>", "直接删除指定会话 id"),
        ),
        handler=noop_handler,
    )

    assert format_command_argument_usage_panel(spec, "/delete nope") == []


def test_command_dash_argument_shows_matching_usage_options():
    spec = CommandSpec(
        name="/delete",
        description="删除历史会话",
        usages=(
            ("", "显示当前工作目录下的历史会话"),
            (" --all", "显示所有工作目录下的历史会话"),
            (" --workspace-all", "删除当前工作目录下的全部会话"),
            (" --all-workspaces", "删除全部工作目录下的全部会话"),
            (" <session_id>", "直接删除指定会话 id"),
            (" --expired", "立即清理超过有效期未访问的会话"),
        ),
        handler=noop_handler,
    )

    panel = "\n".join(format_command_argument_usage_panel(spec, "/delete -"))

    assert "/delete --all             显示所有工作目录下的历史会话" in panel
    assert "/delete --workspace-all   删除当前工作目录下的全部会话" in panel
    assert "/delete --all-workspaces  删除全部工作目录下的全部会话" in panel
    assert "/delete <session_id>" not in panel


def test_command_partial_dash_argument_filters_matching_usage_options():
    spec = CommandSpec(
        name="/delete",
        description="删除历史会话",
        usages=(
            (" --all", "显示所有工作目录下的历史会话"),
            (" --workspace-all", "删除当前工作目录下的全部会话"),
            (" --all-workspaces", "删除全部工作目录下的全部会话"),
            (" --expired", "立即清理超过有效期未访问的会话"),
        ),
        handler=noop_handler,
    )

    panel = "\n".join(format_command_argument_usage_panel(spec, "/delete --all-w"))

    assert "/delete --all-workspaces" in panel
    assert "/delete --all             " not in panel
    assert "/delete --workspace-all" not in panel


def test_selection_clamps_to_available_suggestions():
    assert clamp_selection(2, 1) == 0
    assert clamp_selection(-1, 2) == 0
    assert clamp_selection(1, 2) == 1
    assert clamp_selection(0, 0) == 0


def test_accept_selected_suggestion_completes_buffer_once(monkeypatch):
    registry = CommandRegistry()
    registry.register(CommandSpec(name="/resume", description="恢复历史会话", handler=noop_handler))
    prompt = InteractivePrompt(prompt="User: ", command_registry=registry)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    prompt.buffer = "/"

    assert prompt.accept_selected_suggestion()
    assert prompt.buffer == "/resume "
    assert not prompt.accept_selected_suggestion()


def test_accept_selected_suggestion_does_not_intercept_exact_command(monkeypatch):
    registry = CommandRegistry()
    registry.register(CommandSpec(name="/resume", description="恢复历史会话", handler=noop_handler))
    prompt = InteractivePrompt(prompt="User: ", command_registry=registry)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    prompt.buffer = "/resume"

    assert not prompt.accept_selected_suggestion()
    assert prompt.buffer == "/resume"


def test_move_selection_wraps_only_when_suggestions_exist(monkeypatch):
    registry = CommandRegistry()
    registry.register(CommandSpec(name="/resume", description="恢复历史会话", handler=noop_handler))
    registry.register(CommandSpec(name="/help", description="查看帮助", handler=noop_handler))
    prompt = InteractivePrompt(prompt="User: ", command_registry=registry)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    prompt.buffer = "/"

    prompt.move_selection(1)
    assert prompt.selected_suggestion_index == 1
    prompt.move_selection(1)
    assert prompt.selected_suggestion_index == 0


def test_path_like_input_has_no_selectable_suggestions():
    registry = CommandRegistry()
    registry.register(CommandSpec(name="/resume", description="恢复历史会话", handler=noop_handler))
    prompt = InteractivePrompt(prompt="User: ", command_registry=registry)
    prompt.buffer = "/path"

    assert prompt._suggestions() == []


def test_escape_sequences_move_selection_without_editing_buffer(monkeypatch):
    registry = CommandRegistry()
    registry.register(CommandSpec(name="/resume", description="恢复历史会话", handler=noop_handler))
    registry.register(CommandSpec(name="/help", description="查看帮助", handler=noop_handler))
    prompt = InteractivePrompt(prompt="User: ", command_registry=registry)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    prompt.buffer = "/"
    sequences = iter(["[B", "[A", "OB", "OA"])
    monkeypatch.setattr(prompt, "_read_escape_sequence", lambda: next(sequences))

    prompt._handle_escape_sequence()
    assert prompt.selected_suggestion_index == 1
    prompt._handle_escape_sequence()
    assert prompt.selected_suggestion_index == 0
    prompt._handle_escape_sequence()
    assert prompt.selected_suggestion_index == 1
    prompt._handle_escape_sequence()
    assert prompt.selected_suggestion_index == 0
    assert prompt.buffer == "/"


def test_escape_sequence_reads_raw_fd_without_buffer_leak(monkeypatch):
    registry = CommandRegistry()
    registry.register(CommandSpec(name="/resume", description="恢复历史会话", handler=noop_handler))
    registry.register(CommandSpec(name="/delete", description="删除历史会话", handler=noop_handler))
    prompt = InteractivePrompt(prompt="User: ", command_registry=registry)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    prompt.buffer = "/"
    read_fd, write_fd = os.pipe()
    try:
        prompt._input_fd = read_fd
        os.write(write_fd, b"[B")

        prompt._handle_escape_sequence()

        assert prompt.selected_suggestion_index == 1
        assert prompt.buffer == "/"
    finally:
        prompt._input_fd = None
        os.close(read_fd)
        os.close(write_fd)


def test_escape_sequence_helper_reads_arrow_suffix_from_fd():
    decoder = codecs.getincrementaldecoder("utf-8")()
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b"[B")

        assert read_escape_sequence_from_fd(read_fd, decoder, timeout=0.01) == "[B"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_escape_sequence_helper_reads_full_tilde_sequence_from_fd():
    decoder = codecs.getincrementaldecoder("utf-8")()
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b"[200~")

        assert read_escape_sequence_from_fd(read_fd, decoder, timeout=0.01) == "[200~"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_left_right_home_end_and_delete_edit_buffer(monkeypatch):
    prompt = InteractivePrompt(prompt="User: ", command_registry=None)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    prompt.buffer = "abcd"
    sequences = iter(["[D", "[D", "[3~", "[H", "[C", "[F"])
    monkeypatch.setattr(prompt, "_read_escape_sequence", lambda: next(sequences))

    prompt._handle_escape_sequence()
    prompt._handle_escape_sequence()
    assert prompt.cursor_index == 2

    prompt._handle_escape_sequence()
    assert prompt.buffer == "abd"
    assert prompt.cursor_index == 2

    prompt._handle_escape_sequence()
    assert prompt.cursor_index == 0

    prompt._handle_escape_sequence()
    assert prompt.cursor_index == 1

    prompt._handle_escape_sequence()
    assert prompt.cursor_index == len(prompt.buffer)


def test_insert_and_backspace_apply_at_cursor(monkeypatch):
    prompt = InteractivePrompt(prompt="User: ", command_registry=None)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    prompt.buffer = "acd"
    prompt.cursor_index = 1

    prompt._insert_text("b")
    assert prompt.buffer == "abcd"
    assert prompt.cursor_index == 2

    prompt._backspace()
    assert prompt.buffer == "acd"
    assert prompt.cursor_index == 1


def test_bracketed_paste_preserves_multiline_text(monkeypatch):
    prompt = InteractivePrompt(prompt="User: ", command_registry=None)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    prompt.buffer = "prefix "
    chars = iter("line1\r\nline2\x1b[201~")
    monkeypatch.setattr(prompt, "_read_escape_sequence", lambda: "[200~")
    monkeypatch.setattr(prompt, "_read_char", lambda: next(chars))

    prompt._handle_escape_sequence()

    assert prompt.buffer == "prefix line1\nline2"
    assert prompt.cursor_index == len(prompt.buffer)


def test_render_clears_relative_lines_and_returns_cursor_to_input(monkeypatch):
    registry = CommandRegistry()
    registry.register(CommandSpec(name="/resume", description="恢复历史会话", handler=noop_handler))
    prompt = InteractivePrompt(prompt="User: ", command_registry=registry)
    prompt.buffer = "/"
    writes = []
    monkeypatch.setattr("sys.stdout.write", lambda text: writes.append(text))
    monkeypatch.setattr("sys.stdout.flush", lambda: None)
    monkeypatch.setattr("mycodingagent.terminal_ui.input.terminal_width", lambda: 80)

    prompt._render()
    prompt.buffer = "/r"
    prompt._render()

    assert "\0337" not in writes
    assert "\0338" not in writes
    assert not any("\033[" in item and item.endswith("F") for item in writes)
    assert "\033[2K" in writes
    assert "\033[1B" in writes
    assert "\033[1A" in writes
    assert any("\033[8C" in item for item in writes)


def test_prompt_strips_readline_markers_and_counts_visible_width():
    prompt_text = "\001\033[7m\002User：\001\033[0m\002"
    prompt = InteractivePrompt(prompt=prompt_text, command_registry=None)

    assert "\001" not in prompt.prompt
    assert "\002" not in prompt.prompt
    assert visible_width(prompt_text) == 6
    assert visible_width("输入") == 4
    assert strip_readline_markers(prompt_text) == "\033[7mUser：\033[0m"


def test_visible_width_uses_wcwidth_when_available(monkeypatch):
    monkeypatch.setattr(
        "mycodingagent.terminal_ui.input.wcswidth",
        lambda text: 2 if text == "👨‍👩‍👧‍👦" else len(text),
    )

    assert visible_width("👨‍👩‍👧‍👦") == 2


def test_hard_wrap_avoids_soft_wrap_and_last_column(monkeypatch):
    monkeypatch.setattr("mycodingagent.terminal_ui.input.terminal_width", lambda: 10)

    assert safe_render_columns() == 9
    assert hard_wrap_ansi("1234567890", safe_render_columns()) == ["123456789", "0"]


def test_render_screen_tracks_input_cursor_after_hard_wrap(monkeypatch):
    monkeypatch.setattr("mycodingagent.terminal_ui.input.terminal_width", lambda: 10)

    screen = render_screen(["User: 12345", "hint"], safe_render_columns())

    assert screen.lines == ["User: 123", "45", "hint"]
    assert screen.cursor_row == 1
    assert screen.cursor_column == 2


def test_render_prompt_buffer_tracks_mid_buffer_cursor_and_multiline():
    screen = render_prompt_buffer("User: ", 6, "first\nsecond", len("first\nse"), [], 80)

    assert screen.lines == ["User: first", "      second"]
    assert screen.cursor_row == 1
    assert screen.cursor_column == len("      se")


def test_vertical_cursor_index_moves_between_buffer_lines():
    buffer = "abcd\nxy\n12345"

    assert vertical_cursor_index(buffer, 3, 1) == len("abcd\nxy")
    assert vertical_cursor_index(buffer, len("abcd\nxy"), -1) == 2


def test_format_prompt_echo_uses_crlf_and_continuation_indent():
    assert format_prompt_echo("User: ", 6, "one\ntwo") == "User: one\r\n      two"


def test_normalize_pasted_text_converts_line_endings():
    assert normalize_pasted_text("a\r\nb\rc") == "a\nb\nc"


def test_render_uses_crlf_in_raw_mode(monkeypatch):
    registry = CommandRegistry()
    registry.register(
        CommandSpec(
            name="/resume",
            description="恢复历史会话",
            usages=(("", "显示当前工作目录下的历史会话"),),
            handler=noop_handler,
        )
    )
    prompt = InteractivePrompt(prompt="User: ", command_registry=registry)
    prompt.buffer = "/resume"
    writes = []
    monkeypatch.setattr("sys.stdout.write", lambda text: writes.append(text))
    monkeypatch.setattr("sys.stdout.flush", lambda: None)
    monkeypatch.setattr("mycodingagent.terminal_ui.input.terminal_width", lambda: 80)

    prompt._render()

    assert any("\r\n" in item for item in writes)
    assert not any("\n" in item.replace("\r\n", "") for item in writes)
