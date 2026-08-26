from __future__ import annotations

from mycodingagent.terminal_ui.streaming_markdown import (
    MAX_HIGHLIGHT_LINE_BYTES,
    MarkdownStreamCollector,
    StreamingMarkdownRenderer,
    visual_line_count,
)


def _preview(source: str) -> list[tuple[str, str]]:
    renderer = StreamingMarkdownRenderer()
    renderer.update(source)
    return renderer.preview(max_chars=100_000)


def test_collector_commits_only_complete_lines_and_finalizes_tail() -> None:
    collector = MarkdownStreamCollector()

    collector.push_delta("first")
    assert collector.commit_complete_source() is False
    assert collector.committed_source == ""

    collector.push_delta(" line\nsecond")
    assert collector.commit_complete_source() is True
    assert collector.committed_source == "first line\n"
    assert collector.commit_complete_source() is False

    assert collector.finalize() == "first line\nsecond"
    assert collector.committed_source == "first line\nsecond"


def test_renderer_renders_markdown_inline_styles_and_closed_code() -> None:
    fragments = _preview(
        "# Title\n\n"
        "> **Strong** and *emphasis* with `code`\n\n"
        "```python title=example\n"
        "def value():\n"
        "    return 1\n"
        "```\n"
    )

    assert ("class:stream.heading", "Title") in fragments
    assert ("class:stream.strong", "Strong") in fragments
    assert ("class:stream.emphasis", "emphasis") in fragments
    assert ("class:stream.inline_code", "code") in fragments
    assert ("class:stream.code_keyword", "def") in fragments
    assert ("class:stream.code_number", "1") in fragments


def test_renderer_keeps_unclosed_code_plain_and_uses_language_first_token() -> None:
    pending = _preview("```python title=example\nprint('pending')\n")
    invalid_close = _preview("```python\nprint('pending')\n```not-a-close\n")
    closed = _preview("```python,ignore\nprint('closed')\n```\n")

    assert ("class:stream.code_pending", "print('pending')\n") in pending
    assert ("class:stream.code_pending", "print('pending')\n```not-a-close\n") in invalid_close
    assert any(style == "class:stream.code_string" and "closed" in text for style, text in closed)


def test_renderer_falls_back_to_plain_code_for_unknown_or_oversized_code() -> None:
    unknown = _preview("```does-not-exist\nx = 1\n```\n")
    oversized = _preview(f"```python\n{'x' * (MAX_HIGHLIGHT_LINE_BYTES + 1)}\n```\n")

    assert ("class:stream.code_block", "x = 1\n") in unknown
    assert any(style == "class:stream.code_block" for style, _text in oversized)
    assert not any(style == "class:stream.code_name" for style, _text in oversized)


def test_renderer_freezes_completed_blocks_and_falls_back_for_reference_links() -> None:
    renderer = StreamingMarkdownRenderer()
    first = "# Heading\n\nActive paragraph\n"
    renderer.update(first)
    assert renderer._stable_source == "# Heading\n\n"

    renderer.update(first + " continues\n")
    assert renderer._stable_source == "# Heading\n\n"

    renderer.update(first + "\n[ref]: https://example.test\n")
    assert renderer._stable_source == ""


def test_renderer_renders_tables_and_truncates_preview_by_tail() -> None:
    fragments = _preview("| Name | Value |\n| --- | --- |\n| one | two |\n")
    assert ("class:stream.table", "| Name | Value |\n| --- | --- |\n| one | two |\n") in fragments

    renderer = StreamingMarkdownRenderer()
    renderer.update("old text\n\nnew text\n")
    preview = renderer.preview(max_chars=10)
    assert "".join(text for _style, text in preview).endswith("new text\n\n")
    assert preview[0] == ("class:stream.muted", "...\n")


def test_visual_line_count_uses_display_width() -> None:
    assert visual_line_count([("", "abcdefghij")], columns=5) == 2
    assert visual_line_count([("", "\u4e2d\u6587\u4e2d\u6587")], columns=4) == 2
