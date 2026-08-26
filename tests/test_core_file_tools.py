from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from mycodingagent.tool_runtime import glob as glob_module
from mycodingagent.tool_runtime import grep as grep_module
from mycodingagent.tool_runtime.bash import (
    MAX_TIMEOUT,
    Params as BashParams,
    _format_limited_stream,
    _read_limited_stream,
)
from mycodingagent.tool_runtime.edit_file import EditFile, Params as EditParams
from mycodingagent.tool_runtime.glob import Glob, Params as GlobParams
from mycodingagent.tool_runtime.grep import Grep, Params as GrepParams
from mycodingagent.tool_runtime.read_file import Params as ReadParams
from mycodingagent.tool_runtime.read_file import ReadFile
from mycodingagent.tool_runtime.write_file import Params as WriteParams
from mycodingagent.tool_runtime.write_file import WriteFile


def run(coroutine):
    return asyncio.run(coroutine)


def test_grep_searches_a_single_html_file_and_supports_brace_includes(tmp_path) -> None:
    html = tmp_path / "game.html"
    html.write_text("<script>\nfunction gameLoop() {}\n</script>\n", encoding="utf-8")
    (tmp_path / "game.js").write_text("function gameLoop() {}\n", encoding="utf-8")

    direct = run(Grep(tmp_path).execute(GrepParams(pattern="gameLoop", path="/workspace/game.html")))
    grouped = run(
        Grep(tmp_path).execute(
            GrepParams(pattern="gameLoop", path=".", include="*.{html,js}")
        )
    )

    assert direct.is_error is False
    assert "game.html:2:function gameLoop" in direct.output
    assert grouped.output.splitlines() == [
        "game.html:2:function gameLoop() {}",
        "game.js:1:function gameLoop() {}",
    ]


def test_grep_limits_rendered_output(tmp_path, monkeypatch) -> None:
    (tmp_path / "large.txt").write_text("match " + "x" * 200, encoding="utf-8")
    monkeypatch.setattr(grep_module, "MAX_OUTPUT_CHARS", 40)

    result = run(Grep(tmp_path).execute(GrepParams(pattern="match", path="large.txt")))

    assert "搜索输出达到字符上限" in result.output
    assert len(result.output) < 160


def test_glob_supports_absolute_workspace_patterns_and_braces(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "b.pyi").write_text("", encoding="utf-8")
    (tmp_path / "src" / "c.js").write_text("", encoding="utf-8")

    result = run(
        Glob(tmp_path).execute(
            GlobParams(pattern="/workspace/src/**/*.{py,pyi}", path=".")
        )
    )

    assert result.is_error is False
    assert result.output.splitlines() == ["src/a.py", "src/b.pyi"]


def test_glob_truncation_is_deterministic_and_file_path_is_rejected(tmp_path, monkeypatch) -> None:
    for name in ("c.py", "a.py", "b.py"):
        (tmp_path / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(glob_module, "MAX_GLOB_MATCHES", 2)

    result = run(Glob(tmp_path).execute(GlobParams(pattern="**/*.py", path=".")))
    invalid = run(Glob(tmp_path).execute(GlobParams(pattern="*.py", path="a.py")))

    assert result.output.splitlines()[:2] == ["a.py", "b.py"]
    assert "已截断" in result.output
    assert invalid.is_error is True
    assert "必须是目录" in invalid.output


def test_glob_filters_files_directories_or_both_and_marks_directories(tmp_path) -> None:
    (tmp_path / "empty").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("", encoding="utf-8")
    tool = Glob(tmp_path)

    files = run(tool.execute(GlobParams(pattern="*", path=".", type="files")))
    directories = run(tool.execute(GlobParams(pattern="*", path=".", type="directories")))
    both = run(tool.execute(GlobParams(pattern="*", path=".", type="both")))
    nested_directories = run(
        tool.execute(GlobParams(pattern="**/*", path=".", type="directories"))
    )

    assert files.output == "没有匹配的路径。"
    assert directories.output.splitlines() == ["empty/", "src/"]
    assert both.output.splitlines() == ["empty/", "src/"]
    assert nested_directories.output.splitlines() == ["empty/", "src/"]


def test_read_file_validates_ranges_and_reports_continuation(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    tool = ReadFile(sandbox_root=tmp_path)

    result = run(tool.execute(ReadParams(file_path="source.txt", limit=2)))
    beyond = run(tool.execute(ReadParams(file_path="source.txt", offset=3, limit=1)))
    empty_result = run(tool.execute(ReadParams(file_path="empty.txt")))

    assert result.output == "1\tone\n2\ttwo\n... <还有 1 行；继续读取请使用 offset=2>"
    assert beyond.is_error is True
    assert "共 3 行" in beyond.output
    assert empty_result.output == "（文件为空）"
    with pytest.raises(ValidationError):
        ReadParams(file_path="source.txt", offset=-1)
    with pytest.raises(ValidationError):
        ReadParams(file_path="source.txt", limit=0)


def test_edit_file_preserves_crlf_newlines(tmp_path) -> None:
    source = tmp_path / "windows.txt"
    source.write_bytes(b"first\r\nold value\r\nlast\r\n")
    tool = EditFile(sandbox_root=tmp_path)

    result = run(
        tool.execute(
            EditParams(
                file_path="windows.txt",
                old_string="old value",
                new_string="new value",
                intent="test",
            )
        )
    )

    assert result.is_error is False
    assert source.read_bytes() == b"first\r\nnew value\r\nlast\r\n"


def test_write_file_preserves_content_and_rejects_directory_target(tmp_path) -> None:
    tool = WriteFile(sandbox_root=tmp_path)
    content = "first\r\nsecond\r\n"

    result = run(
        tool.execute(
            WriteParams(file_path="nested/output.txt", content=content, intent="test")
        )
    )
    invalid = run(
        tool.execute(WriteParams(file_path="nested", content="bad", intent="test"))
    )

    assert result.is_error is False
    assert (tmp_path / "nested" / "output.txt").read_bytes() == content.encode()
    assert invalid.is_error is True
    assert "路径不是文件" in invalid.output


def test_bash_validates_command_and_timeout() -> None:
    assert BashParams(command="true").is_persistent_command is False
    assert BashParams(command="npm run dev", is_persistent_command=True).is_persistent_command is True
    with pytest.raises(ValidationError):
        BashParams(command="")
    with pytest.raises(ValidationError):
        BashParams(command="true", timeout=0)
    with pytest.raises(ValidationError):
        BashParams(command="true", timeout=MAX_TIMEOUT + 1)


def test_bash_stream_reader_drains_but_only_keeps_the_limit() -> None:
    async def scenario() -> tuple[bytes, int]:
        stream = asyncio.StreamReader()
        stream.feed_data(b"abcdefghij")
        stream.feed_eof()
        return await _read_limited_stream(stream, 4)

    content, omitted = run(scenario())

    assert content == b"abcd"
    assert omitted == 6
    assert "已截断 6 字节" in _format_limited_stream("标准输出", content, omitted)
