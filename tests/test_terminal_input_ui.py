from __future__ import annotations

from mycodingagent.memory import SessionListItem
from mycodingagent.terminal_ui.input import (
    InteractivePrompt,
    format_styled_prompt_echo,
    style_input_box_lines,
    visual_vertical_cursor_index,
)
from mycodingagent.terminal_ui.input_document import InputDocument, PASTE_COLLAPSE_THRESHOLD, paste_marker
from mycodingagent.terminal_ui.session_selector import render_session_selector


def test_input_document_collapses_long_paste_as_atomic_marker() -> None:
    document = InputDocument.from_text("prefix ")
    pasted = "x" * (PASTE_COLLAPSE_THRESHOLD + 1)

    document, cursor = document.insert_paste(len(document.text), pasted)

    assert document.text == f"prefix {pasted}"
    assert document.display_text == f"prefix {paste_marker(pasted)}"
    document, cursor = document.delete_previous(cursor)
    assert document.text == "prefix "
    assert cursor == len("prefix ")


def test_input_document_displays_short_paste_as_original_editable_text() -> None:
    document = InputDocument.from_text("prefix ")

    document, cursor = document.insert_paste(len(document.text), "short paste")

    assert document.text == "prefix short paste"
    assert document.display_text == "prefix short paste"
    document, cursor = document.delete_previous(cursor)
    assert document.text == "prefix short past"
    assert cursor == len("prefix short past")


def test_short_paste_uses_same_style_as_user_input() -> None:
    document = InputDocument.from_text("prefix ")
    document, _ = document.insert_paste(len(document.text), "short paste")

    styled = document.styled_display_text(
        text_style="<text>",
        paste_style="<paste>",
        reset_style="<reset>",
    )

    assert styled == "<text>prefix <reset><text>short paste<reset>"
    assert "<paste>" not in styled


def test_long_paste_uses_paste_style_for_collapsed_marker() -> None:
    document = InputDocument.from_text("prefix ")
    pasted = "x" * (PASTE_COLLAPSE_THRESHOLD + 1)
    document, _ = document.insert_paste(len(document.text), pasted)

    styled = document.styled_display_text(
        text_style="<text>",
        paste_style="<paste>",
        reset_style="<reset>",
    )

    assert styled == f"<text>prefix <reset><paste>{paste_marker(pasted)}<reset>"


def test_delete_at_cursor_removes_one_character_from_short_paste() -> None:
    document = InputDocument.from_text("a")
    document, _ = document.insert_paste(1, "short paste")

    document, cursor = document.delete_at(1)

    assert document.text == "ahort paste"
    assert document.display_text == "ahort paste"
    assert cursor == 1


def test_delete_at_cursor_removes_entire_collapsed_paste_token() -> None:
    document = InputDocument.from_text("a")
    pasted = "x" * (PASTE_COLLAPSE_THRESHOLD + 1)
    document, cursor = document.insert_paste(1, pasted)
    document, _ = document.insert_text(cursor, "z")

    document, cursor = document.delete_at(1)

    assert document.text == "az"
    assert document.display_text == "az"
    assert cursor == 1


def test_prompt_bracketed_paste_collapses_long_content_until_submit(monkeypatch) -> None:
    prompt = InteractivePrompt(prompt="User: ", command_registry=None)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    pasted = "x" * (PASTE_COLLAPSE_THRESHOLD + 1)
    chars = iter(pasted + "\x1b[201~")
    monkeypatch.setattr(prompt, "_read_escape_sequence", lambda: "[200~")
    monkeypatch.setattr(prompt, "_read_char", lambda: next(chars))

    prompt._handle_escape_sequence()

    assert prompt.buffer == pasted
    assert prompt._document.display_text == paste_marker(pasted)
    prompt._backspace()
    assert prompt.buffer == ""


def test_prompt_bracketed_paste_displays_short_content_as_original_text(monkeypatch) -> None:
    prompt = InteractivePrompt(prompt="User: ", command_registry=None)
    monkeypatch.setattr(prompt, "_render", lambda: None)
    chars = iter("visible\r\nbody\x1b[201~")
    monkeypatch.setattr(prompt, "_read_escape_sequence", lambda: "[200~")
    monkeypatch.setattr(prompt, "_read_char", lambda: next(chars))

    prompt._handle_escape_sequence()

    assert prompt.buffer == "visible\nbody"
    assert prompt._document.display_text == "visible\nbody"
    prompt._backspace()
    assert prompt.buffer == "visible\nbod"


def test_visual_vertical_cursor_index_moves_across_wrapped_rows() -> None:
    assert visual_vertical_cursor_index("abcdef", 1, 1, prompt_width=0, columns=3) == 4
    assert visual_vertical_cursor_index("abcdef", 4, -1, prompt_width=0, columns=3) == 1


def test_input_box_styles_entire_input_line_with_light_gray_background() -> None:
    lines = style_input_box_lines(["  hello", "hint"], input_row_count=1, columns=12)

    assert lines[0].startswith("\033[48;5;252m\033[30m")
    assert lines[0].endswith("\033[0m")
    assert "hello" in lines[0]
    assert lines[1] == "hint"


def test_submitted_prompt_echo_keeps_light_gray_input_box_background() -> None:
    echo = format_styled_prompt_echo("  ", 2, "one\ntwo", columns=12)

    assert echo.count("\033[48;5;252m\033[30m") == 2
    assert "one" in echo
    assert "two" in echo
    assert "\r\n" in echo


def test_submitted_prompt_echo_omits_current_round_header(monkeypatch) -> None:
    prompt = InteractivePrompt(prompt="", command_registry=None, prompt_header="HEADER")
    prompt.buffer = "hello"
    writes: list[str] = []
    monkeypatch.setattr("sys.stdout.write", lambda value: writes.append(value))
    monkeypatch.setattr("sys.stdout.flush", lambda: None)
    monkeypatch.setattr("mycodingagent.terminal_ui.input.terminal_width", lambda: 20)

    prompt._render()
    writes.clear()
    prompt._finish()

    output = "".join(writes)
    assert "HEADER" not in output
    assert "hello" in output


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
