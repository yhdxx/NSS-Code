from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mycodingagent.llm_runtime.streaming import PendingToolCall
from mycodingagent.terminal_ui.output import (
    clear_terminal,
    default_bash_display_level,
    mark_terminal_region_start,
    mcp_display_level,
    processing_status,
    render_assistant_markdown,
    render_tool_calls,
    tool_status_message,
)
from mycodingagent.terminal_ui.theme import (
    COMPOSER_BACKGROUND,
    MAIN_BACKGROUND,
    MUTED_BORDER,
    PRIMARY_TEXT,
    RICH_THEME_STYLES,
    SECONDARY_TEXT,
    TOOL_ACTION_TEAL,
    RISK_APPROVAL_YELLOW,
    RISK_HIGH_RED,
    RISK_LOW_GREEN,
)
from mycodingagent.tool_runtime.command_policy import analyze_command


def _call(name: str, **arguments) -> PendingToolCall:
    return PendingToolCall(tool_id=f"call_{name}", tool_name=name, arguments=json.dumps(arguments, ensure_ascii=False))


def _runtime_bash_display_level(command: str):
    risk, reason = analyze_command(command)
    if risk == "dangerous":
        return "high", reason
    if risk == "read":
        return "low", reason
    return "approval", reason


def test_tool_calls_group_reads_and_render_edit_preview(capsys):
    render_tool_calls(
        [
            _call("Grep", pattern="terminal_ui|stream_one_round", path="PROJECT_FRAMEWORK.md"),
            _call("ReadFile", file_path="mycodingagent/llm_runtime/streaming.py", offset=0, limit=20),
            _call("EditFile", file_path="app.py", old_string="old value", new_string="new value"),
        ]
    )

    output = capsys.readouterr().out

    assert "• Explored" in output
    assert "Search terminal_ui|stream_one_round in PROJECT_FRAMEWORK.md" in output
    assert "Read mycodingagent/llm_runtime/streaming.py lines 1-20" in output
    assert "• Edit app.py" in output
    assert "Replace" in output
    assert "old value" in output
    assert "With" in output
    assert "new value" in output
    assert "old_string" not in output


def test_media_tool_calls_render_as_reads_and_have_processing_status(capsys):
    render_tool_calls(
        [
            _call("TranscribeAudio", source="meeting.wav"),
            _call(
                "AnalyzeImage",
                sources=["before.png", "after.png"],
                query="比较界面变化",
            ),
            _call("FetchUrl", url="https://playwright.dev/python/"),
        ]
    )

    output = capsys.readouterr().out
    assert "• Explored" in output
    assert "Transcribe meeting.wav" in output
    assert "Analyze 2 image(s): 比较界面变化" in output
    assert "Fetch https://playwright.dev/python/" in output
    assert tool_status_message("TranscribeAudio") == "正在处理音频中"
    assert tool_status_message("AnalyzeImage") == "正在处理图片中"
    assert tool_status_message("FetchUrl") == "正在读取网页中"


def test_media_processing_status_animates_while_tool_is_waiting():
    output = _TTYBuffer(tty=True)

    async def run() -> None:
        async with processing_status("正在处理图片中", file=output):
            await asyncio.sleep(0)

    asyncio.run(run())

    assert "H-Agent:正在处理图片中." in output.content
    assert output.content.endswith("\r\033[2K")


def test_default_bash_display_level_is_ui_only_and_conservative():
    assert default_bash_display_level("ls -la")[0] == "low"
    assert default_bash_display_level("python3 -m pytest -q")[0] == "approval"
    assert default_bash_display_level("rm -rf /workspace")[0] == "approval"


def test_bash_tool_call_labels_risk_levels(capsys):
    render_tool_calls(
        [
            _call("Bash", command="ls -la"),
            _call("Bash", command="python3 -m pytest -q"),
            _call("Bash", command="rm -rf /workspace"),
        ],
        bash_classifier=_runtime_bash_display_level,
    )

    output = capsys.readouterr().out

    assert "Bash [低危]" in output
    assert "Bash [需审批]" in output
    assert "Bash [高危]" in output


def test_mcp_risks_map_to_semantic_display_levels():
    assert mcp_display_level("read") == "low"
    assert mcp_display_level("write") == "approval"
    assert mcp_display_level("network") == "approval"
    assert mcp_display_level("unknown") == "approval"
    assert mcp_display_level("destructive") == "high"
    assert mcp_display_level("admin") == "high"


def test_tool_calls_are_grouped_not_mixed_raw_json(capsys):
    render_tool_calls(
        [
            _call("Glob", pattern="*.py", path="mycodingagent"),
            _call("Grep", pattern="render_tool_calls", path="mycodingagent", include="*.py"),
            _call("ReadFile", file_path="mycodingagent/terminal_ui/output.py", offset=0, limit=10),
            _call("Bash", command="ls -la"),
            _call("ReadFile", file_path="PROJECT_FRAMEWORK.md", offset=0, limit=5),
        ],
        bash_classifier=_runtime_bash_display_level,
    )

    output = capsys.readouterr().out

    assert output.count("• Explored") == 2
    assert "工具调用：" not in output
    assert '"pattern"' not in output
    assert '"file_path"' not in output
    assert '"command"' not in output
    assert output.index("• Bash") > output.index("• Explored")


def test_rendering_does_not_mutate_tool_calls():
    calls = [
        _call("ReadFile", file_path="mycodingagent/terminal_ui/output.py", offset=0, limit=10),
        _call("Bash", command="ls -la"),
    ]
    before = [(call.tool_id, call.tool_name, call.arguments) for call in calls]

    render_tool_calls(calls, bash_classifier=_runtime_bash_display_level)

    assert [(call.tool_id, call.tool_name, call.arguments) for call in calls] == before


def test_terminal_theme_uses_the_configured_semantic_palette():
    assert MAIN_BACKGROUND == "#380C2A"
    assert COMPOSER_BACKGROUND == "#4F2943"
    assert RISK_LOW_GREEN == "#5FD75F"
    assert RISK_APPROVAL_YELLOW == "#FFD75F"
    assert RISK_HIGH_RED == "#FF5F5F"
    assert RISK_LOW_GREEN in RICH_THEME_STYLES["bash.low"]
    assert RISK_APPROVAL_YELLOW in RICH_THEME_STYLES["bash.approval"]
    assert RISK_HIGH_RED in RICH_THEME_STYLES["bash.high"]
    assert PRIMARY_TEXT == "#D7D7D7"
    assert SECONDARY_TEXT == "#8F8F8F"
    assert MUTED_BORDER == "#282828"
    assert all(MAIN_BACKGROUND in style for style in RICH_THEME_STYLES.values())
    assert PRIMARY_TEXT in RICH_THEME_STYLES["tool.write"]
    assert SECONDARY_TEXT in RICH_THEME_STYLES["tool.output"]
    assert TOOL_ACTION_TEAL in RICH_THEME_STYLES["tool.read"]


def test_final_answer_markdown_uses_primary_text_by_default(capsys):
    render_assistant_markdown("普通文本\n\n# 标题\n\n- item")

    output = capsys.readouterr().out

    assert "模型：" in output
    assert "普通文本" in output
    assert "标题" in output


def test_long_markdown_lines_are_wrapped_without_losing_content(capsys):
    repeated = "完整内容不能被截断。" * 20

    render_assistant_markdown(f"1. 上下文双层管理：{repeated}")

    output = capsys.readouterr().out
    assert repeated in "".join(output.split())


class _TTYBuffer:
    def __init__(self, *, tty: bool) -> None:
        self.tty = tty
        self.content = ""
        self.flushed = False

    def isatty(self) -> bool:
        return self.tty

    def write(self, text: str) -> int:
        self.content += text
        return len(text)

    def flush(self) -> None:
        self.flushed = True


def test_clear_terminal_clears_agent_region_without_full_screen_reset(monkeypatch):
    tty_buffer = _TTYBuffer(tty=True)
    plain_buffer = _TTYBuffer(tty=False)
    monkeypatch.setattr("mycodingagent.terminal_ui.output._TERMINAL_REGION_MARKED", False)

    clear_terminal(file=tty_buffer)
    clear_terminal(file=plain_buffer)

    assert tty_buffer.content == "\033[H\033[2J"
    assert tty_buffer.flushed is True
    assert plain_buffer.content == ""

    marked_buffer = _TTYBuffer(tty=True)
    mark_terminal_region_start(file=marked_buffer)
    clear_terminal(file=marked_buffer)

    assert marked_buffer.content == "\033[s\033[H\033[2J"
    assert "\033[3J" not in marked_buffer.content


def test_write_file_preview_uses_neutral_block_not_green_action_color(capsys):
    render_tool_calls([_call("WriteFile", file_path="app.py", content="print('ok')")])

    output = capsys.readouterr().out

    assert "• Write app.py" in output
    assert "print('ok')" in output
    assert SECONDARY_TEXT in RICH_THEME_STYLES["tool.output"]


def test_terminal_output_does_not_import_tool_runtime_policy():
    source = (Path(__file__).resolve().parents[1] / "mycodingagent" / "terminal_ui" / "output.py").read_text(
        encoding="utf-8"
    )

    assert "tool_runtime" not in source
