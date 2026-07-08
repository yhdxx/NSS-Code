from __future__ import annotations

import asyncio

from commands import CommandContext, CommandRegistry, CommandResult, CommandSpec
from conversation_history import format_history_message


async def noop_handler(context: CommandContext, arguments: str) -> CommandResult:
    return CommandResult(messages=[{"role": "user", "content": arguments}])


def test_command_registry_matches_command_and_alias():
    registry = CommandRegistry()
    registry.register(
        CommandSpec(
            name="/resume",
            aliases=("resume", "恢复会话"),
            description="恢复历史会话",
            handler=noop_handler,
        )
    )

    assert registry.match("/resume") is not None
    assert registry.match("/resume abc") is not None
    assert registry.match("resume abc") is not None
    assert registry.match("恢复会话 abc") is not None
    registry.register(
        CommandSpec(
            name="/delete",
            aliases=("delete", "删除会话"),
            description="删除历史会话",
            handler=noop_handler,
        )
    )
    assert registry.match("/delete abc") is not None
    assert registry.match("delete abc") is not None
    assert registry.match("删除会话 abc") is not None
    registry.register(
        CommandSpec(
            name="/fork",
            aliases=("fork", "分叉会话"),
            description="分叉历史会话",
            handler=noop_handler,
        )
    )
    assert registry.match("/fork abc") is not None
    assert registry.match("fork abc") is not None
    assert registry.match("分叉会话 abc") is not None
    assert registry.match("/path") is None


def test_command_spec_help_text_includes_usage_examples_and_aliases():
    spec = CommandSpec(
        name="/resume",
        aliases=("resume", "恢复会话"),
        description="恢复历史会话",
        usage="[session_id|--all|--help]",
        usages=(
            ("", "显示当前工作目录下的历史会话"),
            (" --all", "显示所有工作目录下的历史会话"),
        ),
        examples=("/resume", "/resume --all"),
        handler=noop_handler,
    )

    help_text = spec.help_text()

    assert "/resume                   显示当前工作目录下的历史会话" in help_text
    assert "/resume --all             显示所有工作目录下的历史会话" in help_text
    assert "别名：resume、恢复会话" in help_text
    assert "  /resume --all" in help_text


def test_command_suggestions_do_not_block_path_like_input():
    registry = CommandRegistry()
    registry.register(CommandSpec(name="/resume", description="恢复历史会话", handler=noop_handler))
    registry.register(CommandSpec(name="/delete", description="删除历史会话", handler=noop_handler))
    registry.register(CommandSpec(name="/help", description="查看帮助", handler=noop_handler))

    assert [spec.name for spec in registry.suggestions("/")] == ["/resume", "/delete", "/help"]
    assert [spec.name for spec in registry.suggestions("/re")] == ["/resume"]
    assert [spec.name for spec in registry.suggestions("/de")] == ["/delete"]
    assert registry.suggestions("/path") == []
    assert registry.suggestions("/resume abc") == []


def test_command_registry_executes_handler():
    registry = CommandRegistry()
    registry.register(CommandSpec(name="/resume", description="恢复历史会话", handler=noop_handler))

    result = asyncio.run(registry.execute("/resume session-1", CommandContext(None, None, [])))

    assert result.handled
    assert result.messages == [{"role": "user", "content": "session-1"}]


def test_history_message_formatting_skips_system_and_folds_tool_output():
    assert format_history_message({"role": "system", "content": "hidden"}) == ""
    assert format_history_message({"role": "user", "content": "hello"}) == "User: hello"
    assert format_history_message({"role": "assistant", "content": "hi"}) == "Assistant: hi"
    assert (
        format_history_message({"role": "tool", "metadata": {"tool_name": "ReadFile"}, "content": "large output"})
        == "Tool: [ReadFile] 输出已恢复到上下文"
    )


def test_history_message_formatting_truncates_long_content():
    formatted = format_history_message({"role": "assistant", "content": "abcdef"}, max_chars_per_message=4)

    assert formatted == "Assistant: abc…"
