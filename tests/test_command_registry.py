from __future__ import annotations

import asyncio
import json

from mycodingagent.commands import CommandContext, CommandRegistry, CommandResult, CommandSpec
from mycodingagent.code_intelligence.project_graph_runtime import BootstrapUpdate
from mycodingagent.work_mode import WorkMode, WorkModeManager
from mycodingagent.commands import handlers
from mycodingagent.terminal_ui.history import format_history_message


async def noop_handler(context: CommandContext, arguments: str) -> CommandResult:
    return CommandResult(messages=[{"role": "user", "content": arguments}])


def test_command_registry_only_matches_exact_command_and_alias():
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
    assert registry.exact_command("/resume") is not None
    assert registry.match("/resume abc") is None
    assert registry.exact_command("/resume abc") is None
    assert registry.match("resume abc") is None
    assert registry.match("恢复会话 abc") is None
    registry.register(
        CommandSpec(
            name="/delete",
            aliases=("delete", "删除会话"),
            description="删除历史会话",
            handler=noop_handler,
        )
    )
    assert registry.match("/delete abc") is None
    assert registry.match("delete abc") is None
    assert registry.match("删除会话 abc") is None
    registry.register(
        CommandSpec(
            name="/fork",
            aliases=("fork", "分叉会话"),
            description="分叉历史会话",
            handler=noop_handler,
        )
    )
    assert registry.match("/fork abc") is None
    assert registry.match("fork abc") is None
    assert registry.match("分叉会话 abc") is None
    registry.register(
        CommandSpec(
            name="/clear",
            aliases=("clear", "清空会话"),
            description="清空当前会话",
            handler=noop_handler,
        )
    )
    assert registry.match("/clear") is not None
    assert registry.match("clear") is not None
    assert registry.match("清空会话") is not None
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


def test_command_registry_executes_only_exact_command():
    registry = CommandRegistry()
    registry.register(CommandSpec(name="/resume", description="恢复历史会话", handler=noop_handler))

    result = asyncio.run(registry.execute("/resume", CommandContext(None, None, [])))

    assert result.handled
    assert result.messages == [{"role": "user", "content": ""}]

    model_input = asyncio.run(
        registry.execute("/resume session-1", CommandContext(None, None, []))
    )

    assert not model_input.handled


def test_mode_code_initializes_and_renders_project_graph_bootstrap(monkeypatch, capsys):
    class FakeMemoryRuntime:
        def __init__(self) -> None:
            self.work_mode = "general"

        def set_work_mode(self, value: str) -> None:
            self.work_mode = value

    class FakeGraphRuntime:
        def __init__(self) -> None:
            self.activate_called = False

        async def activate(self, progress) -> dict[str, int]:
            self.activate_called = True
            progress("正在刷新静态代码索引...")
            work_mode.commit(WorkMode.CODE)
            return {"modules": 2, "units": 3}

        async def prepare_bootstrap(self, messages, *, force=False):
            payload = {
                "bootstrap": True,
                "generation": 7,
                "navigation_hash": "nav-1",
                "primary_language": "python",
                "modules": [
                    {
                        "id": "root",
                        "parent_id": "",
                        "name": "project",
                        "path": ".",
                        "recursive_unit_count": 3,
                        "child_module_count": 1,
                    },
                    {
                        "id": "pkg",
                        "parent_id": "root",
                        "name": "pkg",
                        "path": "pkg",
                        "recursive_unit_count": 3,
                        "child_module_count": 0,
                    },
                ],
            }
            metadata = {
                "project_graph_bootstrap": True,
                "generation": 7,
                "navigation_hash": "nav-1",
            }
            pair = [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "project_graph_bootstrap_7_nav",
                            "type": "function",
                            "function": {
                                "name": "ProjectArchitecture",
                                "arguments": json.dumps(
                                    {"module": "", "depth": 3, "bootstrap": True},
                                    sort_keys=True,
                                ),
                            },
                        }
                    ],
                    "metadata": metadata,
                },
                {
                    "role": "tool",
                    "tool_call_id": "project_graph_bootstrap_7_nav",
                    "content": json.dumps(payload),
                    "metadata": metadata,
                },
            ]
            return BootstrapUpdate(tuple(pair), payload, "nav-1")

    memory_runtime = FakeMemoryRuntime()
    work_mode = WorkModeManager(WorkMode.GENERAL, persist=memory_runtime.set_work_mode)
    graph_runtime = FakeGraphRuntime()
    messages = [{"role": "system", "content": "system"}]
    context = CommandContext(
        memory_runtime,
        None,
        messages,
        work_mode=work_mode,
        project_graph_runtime=graph_runtime,
    )
    async def choose_code(prompt):
        return "code"

    monkeypatch.setattr(handlers, "request_text", choose_code)

    result = asyncio.run(handlers.handle_mode_command(context, ""))

    assert result.messages is messages
    assert memory_runtime.work_mode == "code"
    assert graph_runtime.activate_called
    assert len(messages) == 3
    assert messages[-1]["metadata"]["project_graph_bootstrap"] is True
    output = capsys.readouterr().out
    assert "[项目图谱] Code 模式已就绪：2 个模块，3 个单位。" in output
    assert "[项目图谱] Bootstrap" in output
    assert "pkg" in output


def test_mode_code_does_not_repeat_initialization_when_already_active(monkeypatch, capsys):
    class FakeGraphRuntime:
        async def activate(self, progress):
            raise AssertionError("active Code mode must not initialize again")

    async def choose_code(prompt):
        return "code"

    work_mode = WorkModeManager(WorkMode.CODE)
    context = CommandContext(
        None,
        None,
        [{"role": "system", "content": "system"}],
        work_mode=work_mode,
        project_graph_runtime=FakeGraphRuntime(),
    )
    monkeypatch.setattr(handlers, "request_text", choose_code)

    asyncio.run(handlers.handle_mode_command(context, ""))

    output = capsys.readouterr().out
    assert "当前已处于 Code 模式" in output
    assert "Code 模式初始化开始" not in output


def test_history_message_formatting_skips_system_and_folds_tool_output():
    assert format_history_message({"role": "system", "content": "hidden"}) == ""
    assert format_history_message({"role": "user", "content": "hello"}) == "User: hello"
    assert format_history_message({"role": "assistant", "content": "hi"}) == "Assistant: hi"
    assert (
        format_history_message({"role": "tool", "metadata": {"tool_name": "ReadFile"}, "content": "large output"})
        == "Tool: [ReadFile] large output"
    )


def test_history_message_formatting_truncates_long_content():
    formatted = format_history_message({"role": "assistant", "content": "abcdef"}, max_chars_per_message=4)

    assert formatted == "Assistant: abc…"
