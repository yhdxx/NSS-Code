from __future__ import annotations

from pathlib import Path
import json

from mycodingagent.llm_runtime.streaming import PendingToolCall
from mycodingagent.terminal_ui.output import (
    TERMINAL_THEME_STYLES,
    clear_terminal,
    default_bash_display_level,
    mark_terminal_region_start,
    render_assistant_markdown,
    render_tool_calls,
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


def test_terminal_theme_is_greyscale_first_with_limited_semantic_color():
    joined_styles = " ".join(TERMINAL_THEME_STYLES.values())
    assert "magenta" not in joined_styles
    assert "cyan" not in joined_styles
    assert "purple" not in joined_styles
    accent_words = ("green", "yellow", "red", "blue")
    accent_count = sum(any(word in style for word in accent_words) for style in TERMINAL_THEME_STYLES.values())
    neutral_count = len(TERMINAL_THEME_STYLES) - accent_count
    assert neutral_count > accent_count
    assert TERMINAL_THEME_STYLES["tool.write"].startswith("grey")
    assert TERMINAL_THEME_STYLES["tool.section"] == "bold bright_white"
    assert TERMINAL_THEME_STYLES["tool.arg"].startswith("grey")
    assert TERMINAL_THEME_STYLES["tool.read"] == "bright_blue"
    assert TERMINAL_THEME_STYLES["markdown.h1"] == "bold bright_white"
    assert TERMINAL_THEME_STYLES["markdown.base"] == "bright_white"
    assert TERMINAL_THEME_STYLES["markdown.paragraph"] == "bright_white"


def test_final_answer_markdown_is_rendered_bright_white_by_default(capsys):
    render_assistant_markdown("普通文本\n\n# 标题\n\n- item")

    output = capsys.readouterr().out

    assert "模型：" in output
    assert "普通文本" in output
    assert "标题" in output


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
    assert TERMINAL_THEME_STYLES["tool.output"].startswith("grey")


def test_terminal_output_does_not_import_tool_runtime_policy():
    source = (Path(__file__).resolve().parents[1] / "mycodingagent" / "terminal_ui" / "output.py").read_text(
        encoding="utf-8"
    )

    assert "tool_runtime" not in source
