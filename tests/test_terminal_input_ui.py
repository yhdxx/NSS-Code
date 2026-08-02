from __future__ import annotations

import pytest

from mycodingagent.memory import SessionListItem
from mycodingagent.terminal_ui.clipboard import clear_internal_clipboard, copy_to_clipboard, paste_from_clipboard
from mycodingagent.terminal_ui.input import (
    InteractivePrompt,
    key_name_for_char,
    key_name_for_escape_sequence,
    style_input_box_lines,
    visual_vertical_cursor_index,
)
from mycodingagent.terminal_ui.input_document import InputDocument, paste_marker
from mycodingagent.terminal_ui.keymap import action_for_key, load_keymap
from mycodingagent.terminal_ui.session_selector import render_session_selector


def test_input_document_displays_paste_as_atomic_marker() -> None:
    document = InputDocument.from_text("prefix ")

    document, cursor = document.insert_paste(len(document.text), "line1\nline2")

    assert document.text == "prefix line1\nline2"
    assert document.display_text == f"prefix {paste_marker('line1\nline2')}"
    document, cursor = document.delete_previous(cursor)
    assert document.text == "prefix "
    assert cursor == len("prefix ")


def test_delete_at_cursor_removes_entire_paste_token() -> None:
    document = InputDocument.from_text("a")
    document, cursor = document.insert_paste(1, "secret pasted content")
    document, _ = document.insert_text(cursor, "z")

    document, cursor = document.delete_at(1)

    assert document.text == "az"
    assert document.display_text == "az"
    assert cursor == 1


def test_prompt_bracketed_paste_hides_real_content_until_submit(monkeypatch) -> None:
    prompt = InteractivePrompt(prompt="User: ", command_registry=None)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    chars = iter("hidden\r\nbody\x1b[201~")
    monkeypatch.setattr(prompt, "_read_escape_sequence", lambda: "[200~")
    monkeypatch.setattr(prompt, "_read_char", lambda: next(chars))

    prompt._handle_escape_sequence()

    assert prompt.buffer == "hidden\nbody"
    assert prompt._document.display_text == paste_marker("hidden\nbody")
    prompt._backspace()
    assert prompt.buffer == ""


def test_copy_or_interrupt_uses_selection_then_falls_back_to_interrupt(monkeypatch) -> None:
    prompt = InteractivePrompt(prompt="User: ", command_registry=None)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    clear_internal_clipboard()
    prompt.buffer = "abcdef"
    prompt.selection_anchor = 1
    prompt.cursor_index = 4

    assert prompt._handle_action("copy_or_interrupt") is False
    assert paste_from_clipboard() == "bcd"

    prompt.selection_anchor = None
    with pytest.raises(KeyboardInterrupt):
        prompt._handle_action("copy_or_interrupt")


def test_ctrl_v_inserts_internal_clipboard_as_paste_token(monkeypatch) -> None:
    prompt = InteractivePrompt(prompt="User: ", command_registry=None)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    copy_to_clipboard("clipboard text")

    prompt._handle_action("paste")

    assert prompt.buffer == "clipboard text"
    assert prompt._document.display_text == paste_marker("clipboard text")


def test_default_key_names_map_to_configurable_actions() -> None:
    keymap = load_keymap()

    assert action_for_key(keymap, key_name_for_char("\x03")) == "copy_or_interrupt"
    assert action_for_key(keymap, key_name_for_char("\x16")) == "paste"
    assert action_for_key(keymap, key_name_for_escape_sequence("[Z")) == "unindent"
    assert action_for_key(keymap, key_name_for_escape_sequence("a")) == "select_all"


def test_keymap_can_be_overridden_from_json(tmp_path) -> None:
    keymap_path = tmp_path / "keymap.json"
    keymap_path.write_text('{"select_all": "ctrl+x", "newline": ["alt+n"]}', encoding="utf-8")

    keymap = load_keymap(keymap_path)

    assert action_for_key(keymap, "ctrl+x") == "select_all"
    assert action_for_key(keymap, "alt+n") == "newline"
    assert action_for_key(keymap, "alt+a") == ""


def test_visual_vertical_cursor_index_moves_across_wrapped_rows() -> None:
    assert visual_vertical_cursor_index("abcdef", 1, 1, prompt_width=0, columns=3) == 4
    assert visual_vertical_cursor_index("abcdef", 4, -1, prompt_width=0, columns=3) == 1


def test_shift_arrow_extends_application_selection(monkeypatch) -> None:
    prompt = InteractivePrompt(prompt="  ", command_registry=None)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    prompt.buffer = "abcdef"
    prompt.cursor_index = 3

    prompt._handle_action("select_right")
    prompt._handle_action("select_right")

    assert prompt._selection_range() == (3, 5)
    prompt._handle_action("copy_or_interrupt")
    assert paste_from_clipboard() == "de"


def test_input_box_styles_entire_input_line_with_brown_background() -> None:
    lines = style_input_box_lines(["  hello", "hint"], input_row_count=1, columns=12)

    assert lines[0].startswith("\033[48;5;94m\033[97m")
    assert lines[0].endswith("\033[0m")
    assert "hello" in lines[0]
    assert lines[1] == "hint"


def test_session_selector_initial_render_leaves_list_visible(monkeypatch) -> None:
    writes: list[str] = []
    monkeypatch.setattr("sys.stdout.write", lambda text: writes.append(text))
    monkeypatch.setattr("sys.stdout.flush", lambda: None)
    monkeypatch.setattr("mycodingagent.terminal_ui.session_selector.safe_render_columns", lambda: 120)
    sessions = [
        SessionListItem(
            session_id="abcdef123456",
            updated_at=0,
            last_accessed_at=0,
            preview="hello",
            message_count=2,
        )
    ]

    rows = render_session_selector(sessions, selected=0)

    output = "".join(writes)
    assert rows == 2
    assert "请选择要恢复的会话" in output
    assert "> [abcdef12] hello" in output
    assert "\033[1A" not in output
