from __future__ import annotations

from prompt_toolkit.styles import Style


MAIN_BACKGROUND = "#380C2A"
COMPOSER_BACKGROUND = "#4F2943"
WINDOW_CHROME = "#3E3E3E"
PRIMARY_TEXT = "#D7D7D7"
SECONDARY_TEXT = "#8F8F8F"
MUTED_BORDER = "#282828"
TOOL_ACTION_TEAL = "#5FD7C4"


PROMPT_TOOLKIT_STYLES: dict[str, str] = {
    "loading": f"bg:{MAIN_BACKGROUND} {PRIMARY_TEXT}",
    "input.body": f"bg:{COMPOSER_BACKGROUND} {PRIMARY_TEXT}",
    "input.prefix": f"bg:{COMPOSER_BACKGROUND} {PRIMARY_TEXT} bold",
    "status": f"bg:{MAIN_BACKGROUND} {SECONDARY_TEXT}",
    "queue.title": f"bg:{MAIN_BACKGROUND} {SECONDARY_TEXT}",
    "queue.item": f"bg:{MAIN_BACKGROUND} {SECONDARY_TEXT}",
    "stream.label": f"bg:{MAIN_BACKGROUND} {PRIMARY_TEXT} bold",
    "stream.text": f"bg:{MAIN_BACKGROUND} {PRIMARY_TEXT}",
    "plan.preview": f"bg:{COMPOSER_BACKGROUND} {PRIMARY_TEXT}",
    "plan.option": f"bg:{COMPOSER_BACKGROUND} {SECONDARY_TEXT}",
    "plan.option.current": f"bg:{COMPOSER_BACKGROUND} {PRIMARY_TEXT} bold",
    "plan.hint": f"bg:{COMPOSER_BACKGROUND} {SECONDARY_TEXT}",
    "completion-menu.completion": f"bg:{MUTED_BORDER} {PRIMARY_TEXT}",
    "completion-menu.completion.current": f"bg:{COMPOSER_BACKGROUND} {PRIMARY_TEXT}",
    "completion-menu.meta.completion": f"bg:{MUTED_BORDER} {SECONDARY_TEXT}",
    "completion-menu.meta.completion.current": f"bg:{COMPOSER_BACKGROUND} {PRIMARY_TEXT}",
}


RICH_THEME_STYLES: dict[str, str] = {
    "label": f"bold {PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "text": f"{PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "status": f"{SECONDARY_TEXT} on {MAIN_BACKGROUND}",
    "error": f"bold {PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "tool.output": f"{SECONDARY_TEXT} on {MAIN_BACKGROUND}",
    "tool.generic": f"{PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "tool.section": f"bold {PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "tool.branch": f"{SECONDARY_TEXT} on {MAIN_BACKGROUND}",
    "tool.arg": f"{PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "tool.read": f"{TOOL_ACTION_TEAL} on {MAIN_BACKGROUND}",
    "tool.write": f"{PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "bash.command": f"{PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "bash.low": f"{SECONDARY_TEXT} on {MAIN_BACKGROUND}",
    "bash.approval": f"bold {PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "bash.high": f"bold {PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "edit.old": f"{SECONDARY_TEXT} on {MAIN_BACKGROUND}",
    "edit.new": f"{PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "markdown.base": f"{PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "markdown.paragraph": f"{PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "markdown.h1": f"bold {PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "markdown.h2": f"bold {PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "markdown.h3": f"bold {PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "markdown.h4": f"bold {PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "markdown.h5": f"bold {PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "markdown.h6": f"bold {PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "markdown.code": f"{PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "markdown.code_block": f"{PRIMARY_TEXT} on {MAIN_BACKGROUND}",
    "markdown.block_quote": f"italic {SECONDARY_TEXT} on {MAIN_BACKGROUND}",
    "markdown.link": f"underline {PRIMARY_TEXT} on {MAIN_BACKGROUND}",
}


def prompt_toolkit_style() -> Style:
    return Style.from_dict(PROMPT_TOOLKIT_STYLES)


def _rgb_escape(color: str, *, background: bool) -> str:
    value = color.removeprefix("#")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    channel = 48 if background else 38
    return f"\x1b[{channel};2;{red};{green};{blue}m"


ACTIVE_USER_ANSI = (
    _rgb_escape(COMPOSER_BACKGROUND, background=True)
    + _rgb_escape(PRIMARY_TEXT, background=False)
)
RESET_ANSI = "\x1b[0m"
