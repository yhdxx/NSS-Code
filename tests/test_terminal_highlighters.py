from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text

from mycodingagent.terminal_ui.highlighters import HIGHLIGHTERS, detect_language, highlight_for_terminal
from mycodingagent.tool_runtime.write_file import WriteFile


@pytest.mark.parametrize(
    ("file_path", "expected"),
    [
        ("README.md", "markdown"),
        ("app.py", "python"),
        ("Main.java", "java"),
        ("engine.cpp", "cpp"),
        ("engine.c", "c"),
        ("main.go", "go"),
        ("lib.rs", "rust"),
        ("index.js", "javascript"),
        ("index.ts", "typescript"),
        ("index.html", "html"),
    ],
)
def test_detect_language_from_extension(file_path: str, expected: str):
    assert detect_language("content", file_path=file_path) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("```rust\nfn main() {}\n```", "rust"),
        ("#!/usr/bin/env python3\nprint('ok')", "python"),
        ("#!/usr/bin/env node\nconsole.log('ok')", "javascript"),
        ("package main\nfunc main() {}", "go"),
        ("public class Main {}", "java"),
        ("#include <iostream>\nint main(){ std::cout << 1; }", "cpp"),
        ("#include <stdio.h>\nint main(){ printf(\"ok\"); }", "c"),
        ("const value: number = 1;", "typescript"),
        ("const value = () => 1;", "javascript"),
        ("<!doctype html><html></html>", "html"),
        ("# Title\n\n- item", "markdown"),
    ],
)
def test_detect_language_from_content(text: str, expected: str):
    assert detect_language(text) == expected


def test_unknown_language_uses_default_text_highlighter():
    assert detect_language("plain sentence without markdown markers") == "text"
    assert isinstance(HIGHLIGHTERS["text"].render("plain"), Text)


def test_highlight_for_terminal_returns_matching_renderables_without_mutating_text():
    source = "print('ok')"

    python_renderable = highlight_for_terminal(source, file_path="app.py")
    markdown_renderable = highlight_for_terminal("# Title", declared_language="markdown")
    text_renderable = highlight_for_terminal("plain sentence")

    assert source == "print('ok')"
    assert isinstance(python_renderable, Syntax)
    assert isinstance(markdown_renderable, Markdown)
    assert isinstance(text_renderable, Text)


def test_highlighters_live_under_terminal_ui_highlighters_package():
    package_root = Path(__file__).resolve().parents[1] / "mycodingagent" / "terminal_ui"

    assert (package_root / "highlighters" / "__init__.py").exists()
    assert (package_root / "highlighters" / "registry.py").exists()
    assert not (package_root / "syntax.py").exists()


def test_write_file_writes_raw_content_not_terminal_highlight_markup(tmp_path):
    content = "**bold**\n\n```python\nprint('ok')\n```\n"
    tool = WriteFile(sandbox_root=tmp_path)

    result = asyncio.run(
        tool.execute(tool.params_model(file_path="rendered.md", content=content, intent="raw write"))
    )

    written = (tmp_path / "rendered.md").read_text(encoding="utf-8")
    assert result.is_error is False
    assert written == content
    assert "\x1b" not in written
