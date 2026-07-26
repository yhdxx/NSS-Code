from __future__ import annotations

from mycodingagent.commands.registry import CommandContext, CommandRegistry, CommandResult, CommandSpec
from mycodingagent.configuration import CONFIG
from mycodingagent.llm_runtime import client
from mycodingagent.memory.session_switch import has_conversation_content, save_current_session_if_needed
from mycodingagent.terminal_ui.confirm import (
    confirm_cross_workspace_action,
    confirm_cross_workspace_restore,
    confirm_delete_sessions,
)
from mycodingagent.terminal_ui.history import render_conversation_history
from mycodingagent.terminal_ui.session_selector import select_session_interactively
from multiAgent import MultiAgentStore
from multiAgent.context import run_summary_for_main_context


def mark_long_term_memory_pending(context: CommandContext, session_id: str) -> None:
    if not session_id or context.long_term_memory_runtime is None:
        return
    try:
        context.long_term_memory_runtime.mark_session_pending(session_id)
    except Exception as exc:  # pragma: no cover - memory extraction must not break commands
        print(f"长期记忆待抽取标记失败：{exc}", flush=True)


def build_command_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(
        CommandSpec(
            name="/resume",
            aliases=("resume", "恢复会话"),
            description="恢复历史会话；默认仅显示当前工作目录会话",
            usage="[session_id|--all|--help]",
            usages=(
                ("", "显示当前工作目录下的历史会话，并通过 ↑/↓ 选择恢复"),
                (" --all", "显示所有工作目录下的历史会话；跨目录恢复前会要求确认"),
                (" <session_id>", "直接恢复指定会话 id；可用于非交互终端"),
                (" --help", "显示 /resume 的完整参数说明"),
            ),
            examples=(
                "/resume",
                "/resume --all",
                "/resume <session_id>",
                "/resume --help",
            ),
            handler=handle_resume_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/fork",
            aliases=("fork", "分叉会话"),
            description="从历史会话创建分叉，并切换到新的分叉会话",
            usage="[session_id|--all|--help]",
            usages=(
                ("", "显示当前工作目录下的历史会话，并通过 ↑/↓ 选择分叉"),
                (" --all", "显示所有工作目录下的历史会话；跨目录分叉前会要求确认"),
                (" <session_id>", "直接分叉指定会话 id；可用于非交互终端"),
                (" --help", "显示 /fork 的完整参数说明"),
            ),
            examples=(
                "/fork",
                "/fork --all",
                "/fork <session_id>",
                "/fork --help",
            ),
            handler=handle_fork_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/clear",
            aliases=("clear", "清空会话"),
            description="保存当前会话，清空上下文，并启动新的空会话",
            usage="[--help]",
            usages=(
                ("", "保存当前会话后清空当前上下文，并立即启动新的空会话"),
                (" --help", "显示 /clear 的完整参数说明"),
            ),
            examples=(
                "/clear",
                "/clear --help",
            ),
            handler=handle_clear_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/delete",
            aliases=("delete", "删除会话"),
            description="删除本地历史会话；默认通过 ↑/↓ 选择删除",
            usage="[session_id|--all|--workspace-all|--all-workspaces|--expired|--help]",
            usages=(
                ("", "显示当前工作目录下的历史会话，并通过 ↑/↓ 选择删除"),
                (" --all", "显示所有工作目录下的历史会话；跨目录删除前会要求确认"),
                (" --workspace-all", "删除当前工作目录下的全部会话"),
                (" --all-workspaces", "删除全部工作目录下的全部会话"),
                (" <session_id>", "直接删除指定会话 id；可用于非交互终端"),
                (" --expired", "立即清理超过有效期未访问的会话"),
                (" --help", "显示 /delete 的完整参数说明"),
            ),
            examples=(
                "/delete",
                "/delete --all",
                "/delete --workspace-all",
                "/delete --all-workspaces",
                "/delete <session_id>",
                "/delete --expired",
                "/delete --help",
            ),
            handler=handle_delete_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/multiAgent",
            aliases=("multiAgent", "多智能体"),
            description="使用隔离的 plan/review/execute/test/review 多智能体工作流执行复杂任务",
            usage="[status|resume <run_id>|inspect <run_id>|<task>]",
            usages=(
                (" <task>", "创建并运行新的多智能体任务"),
                (" status", "列出最近未完成的多智能体任务"),
                (" resume <run_id>", "从持久化状态恢复指定任务"),
                (" inspect <run_id>", "查看任务摘要"),
            ),
            examples=(
                "/multiAgent 按上一轮计划修改代码",
                "/multiAgent status",
                "/multiAgent resume <run_id>",
                "/multiAgent inspect <run_id>",
            ),
            handler=handle_multi_agent_command,
        )
    )
    return registry


async def handle_multi_agent_command(context: CommandContext, arguments: str) -> CommandResult:
    store = context.multi_agent_store or MultiAgentStore()
    argument = arguments.strip()
    if not argument or argument in {"--help", "-h", "help"}:
        print(build_command_registry().match("/multiAgent")[0].help_text(), flush=True)
        return CommandResult()

    if argument == "status":
        runs = store.list_unfinished(limit=10)
        if not runs:
            print("没有未完成的多智能体任务。", flush=True)
            return CommandResult()
        for run in runs:
            print(f"{run.run_id} | {run.status.value} | {run.title or run.task[:80]}", flush=True)
        return CommandResult()

    if argument.startswith("inspect "):
        run_id = argument.split(maxsplit=1)[1].strip()
        run = store.load_run(run_id)
        if run is None:
            print(f"未找到多智能体任务：{run_id}", flush=True)
            return CommandResult()
        print(run_summary_for_main_context(run), flush=True)
        return CommandResult()

    if context.registry is None or context.api_client is None:
        print("多智能体运行缺少 registry 或 api_client，无法执行。", flush=True)
        return CommandResult()

    from multiAgent.orchestrator import MultiAgentOrchestrator

    orchestrator = MultiAgentOrchestrator(
        store=store,
        registry=context.registry,
        api_client=context.api_client,
        memory_runtime=context.memory_runtime,
        model=client.MODEL,
    )

    try:
        if argument.startswith("resume "):
            run_id = argument.split(maxsplit=1)[1].strip()
            run = await orchestrator.resume(run_id=run_id, main_messages=context.messages)
            user_content = f"/multiAgent resume {run_id}"
        else:
            run = await orchestrator.start(task=argument, main_messages=context.messages)
            user_content = f"/multiAgent {argument}"
    except ValueError as exc:
        print(str(exc), flush=True)
        return CommandResult()

    result_message = orchestrator.result_message(run)
    updated_messages = [
        *context.messages,
        {"role": "user", "content": user_content},
        result_message,
    ]
    print(result_message["content"], flush=True)
    return CommandResult(messages=updated_messages)


async def handle_resume_command(context: CommandContext, arguments: str) -> CommandResult:
    memory_runtime = context.memory_runtime
    if memory_runtime is None:
        print("记忆模块未启用，无法恢复会话。", flush=True)
        return CommandResult()
    resume_spec = build_command_registry().match("/resume")[0]
    if arguments.strip() in {"--help", "-h", "help"}:
        print(resume_spec.help_text(), flush=True)
        return CommandResult()
    await memory_runtime.drain()
    deleted_count = memory_runtime.cleanup_expired_sessions()
    if deleted_count:
        print(f"已清理 {deleted_count} 个超过 {CONFIG.memory.session_ttl_days} 天未访问的会话。", flush=True)
    current_session_id = save_current_session_if_needed(
        memory_runtime=memory_runtime,
        messages=context.messages,
        skill_runtime=context.skill_runtime,
        file_state_cache=context.file_state_cache,
    )
    await memory_runtime.drain()
    mark_long_term_memory_pending(context, current_session_id)
    include_all = arguments.strip() == "--all"
    resume_session_id = "" if include_all else arguments.strip()
    if not resume_session_id:
        resume_session_id = select_session_interactively(memory_runtime, include_all=include_all)
        if not resume_session_id:
            return CommandResult()
    if resume_session_id == current_session_id and has_conversation_content(context.messages):
        memory_runtime.touch_session(resume_session_id)
        render_conversation_history(context.messages)
        print(f"已恢复会话：{resume_session_id}（{len(context.messages)} 条消息）", flush=True)
        return CommandResult(messages=context.messages)
    state = memory_runtime.load_session(resume_session_id)
    if state is None:
        print(f"未找到会话：{resume_session_id}", flush=True)
        return CommandResult()
    if state.workspace_root and state.workspace_root != memory_runtime.workspace_root:
        if not confirm_cross_workspace_restore(state.workspace_root, memory_runtime.workspace_root):
            print("已取消跨工作目录恢复。", flush=True)
            return CommandResult()
    memory_runtime.load_lrfu_snapshot(resume_session_id, context.skill_runtime)
    memory_runtime.load_file_state_snapshot(
        resume_session_id,
        context.file_state_cache,
        context.workspace_tracker,
    )
    render_conversation_history(state.messages)
    print(f"已恢复会话：{resume_session_id}（{len(state.messages)} 条消息）", flush=True)
    return CommandResult(messages=state.messages)


async def handle_fork_command(context: CommandContext, arguments: str) -> CommandResult:
    memory_runtime = context.memory_runtime
    if memory_runtime is None:
        print("记忆模块未启用，无法分叉会话。", flush=True)
        return CommandResult()
    fork_spec = build_command_registry().match("/fork")[0]
    argument = arguments.strip()
    if argument in {"--help", "-h", "help"}:
        print(fork_spec.help_text(), flush=True)
        return CommandResult()

    await memory_runtime.drain()
    deleted_count = memory_runtime.cleanup_expired_sessions()
    if deleted_count:
        print(f"已清理 {deleted_count} 个超过 {CONFIG.memory.session_ttl_days} 天未访问的会话。", flush=True)

    current_session_id = save_current_session_if_needed(
        memory_runtime=memory_runtime,
        messages=context.messages,
        skill_runtime=context.skill_runtime,
        file_state_cache=context.file_state_cache,
    )
    await memory_runtime.drain()
    mark_long_term_memory_pending(context, current_session_id)

    include_all = argument == "--all"
    source_session_id = "" if include_all else argument
    if not source_session_id:
        source_session_id = select_session_interactively(memory_runtime, include_all=include_all, action="分叉")
        if not source_session_id:
            return CommandResult()

    source_state = memory_runtime.store.load_session(source_session_id)
    if source_state is None:
        print(f"未找到会话：{source_session_id}", flush=True)
        return CommandResult()
    if source_state.workspace_root and source_state.workspace_root != memory_runtime.workspace_root:
        if not confirm_cross_workspace_action("分叉", source_state.workspace_root, memory_runtime.workspace_root):
            print("已取消跨工作目录分叉。", flush=True)
            return CommandResult()

    fork_messages = source_state.messages
    if source_session_id == current_session_id and has_conversation_content(context.messages):
        fork_messages = context.messages
    fork_session_id = memory_runtime.fork_session(
        source_session_id,
        model=client.MODEL,
        messages=fork_messages,
    )
    if fork_session_id is None:
        print(f"未找到会话：{source_session_id}", flush=True)
        return CommandResult()

    memory_runtime.load_lrfu_snapshot(fork_session_id, context.skill_runtime)
    memory_runtime.load_file_state_snapshot(
        fork_session_id,
        context.file_state_cache,
        context.workspace_tracker,
    )
    render_conversation_history(fork_messages)
    print(
        f"已分叉会话：{fork_session_id}（源会话：{source_session_id}，{len(fork_messages)} 条消息）",
        flush=True,
    )
    return CommandResult(messages=fork_messages)


async def handle_clear_command(context: CommandContext, arguments: str) -> CommandResult:
    argument = arguments.strip()
    clear_spec = build_command_registry().match("/clear")[0]
    if argument in {"--help", "-h", "help"}:
        print(clear_spec.help_text(), flush=True)
        return CommandResult()
    if argument:
        print(clear_spec.help_text(), flush=True)
        return CommandResult()

    memory_runtime = context.memory_runtime
    if memory_runtime is None:
        print("记忆模块未启用，已清空当前对话。", flush=True)
        return CommandResult(messages=[])

    await memory_runtime.drain()
    saved_session_id = save_current_session_if_needed(
        memory_runtime=memory_runtime,
        messages=context.messages,
        skill_runtime=context.skill_runtime,
        file_state_cache=context.file_state_cache,
    )
    await memory_runtime.drain()
    mark_long_term_memory_pending(context, saved_session_id)
    memory_runtime.clear_current_session_id()
    new_session_id = memory_runtime.start_session(client.MODEL)
    await memory_runtime.drain()

    if saved_session_id:
        print(f"已保存当前会话：{saved_session_id}", flush=True)
    else:
        print("当前会话为空，无需保存。", flush=True)
    print(f"已清空上下文并启动新会话：{new_session_id}", flush=True)
    return CommandResult(messages=[])


async def handle_delete_command(context: CommandContext, arguments: str) -> CommandResult:
    memory_runtime = context.memory_runtime
    if memory_runtime is None:
        print("记忆模块未启用，无法删除会话。", flush=True)
        return CommandResult()
    delete_spec = build_command_registry().match("/delete")[0]
    argument = arguments.strip()
    if argument in {"--help", "-h", "help"}:
        print(delete_spec.help_text(), flush=True)
        return CommandResult()

    await memory_runtime.drain()
    deleted_count = memory_runtime.cleanup_expired_sessions()
    if argument == "--expired":
        print(f"已清理 {deleted_count} 个超过 {CONFIG.memory.session_ttl_days} 天未访问的会话。", flush=True)
        return CommandResult()
    if deleted_count:
        print(f"已清理 {deleted_count} 个超过 {CONFIG.memory.session_ttl_days} 天未访问的会话。", flush=True)

    current_session_id = save_current_session_if_needed(
        memory_runtime=memory_runtime,
        messages=context.messages,
        skill_runtime=context.skill_runtime,
        file_state_cache=context.file_state_cache,
    )
    await memory_runtime.drain()

    if argument in {"--workspace-all", "--all-workspaces"}:
        include_all = argument == "--all-workspaces"
        sessions = memory_runtime.list_sessions(limit=10_000, include_all=include_all)
        if not sessions:
            scope = "全部工作目录" if include_all else "当前工作目录"
            print(f"{scope}下没有可删除会话。", flush=True)
            return CommandResult()
        if not confirm_delete_sessions(sessions, include_all=include_all):
            print("已取消批量删除。", flush=True)
            return CommandResult()
        session_ids = [session.session_id for session in sessions]
        deleted = memory_runtime.delete_sessions(session_ids)
        scope = "全部工作目录" if include_all else "当前工作目录"
        print(f"已删除{scope}下 {deleted} 个会话。", flush=True)
        if current_session_id and current_session_id in session_ids:
            return CommandResult(messages=[])
        return CommandResult()

    include_all = argument == "--all"
    delete_session_id = "" if include_all else argument
    if not delete_session_id:
        delete_session_id = select_session_interactively(memory_runtime, limit=20, include_all=include_all, action="删除")
        if not delete_session_id:
            return CommandResult()

    state = memory_runtime.store.load_session(delete_session_id)
    if state is None:
        print(f"未找到会话：{delete_session_id}", flush=True)
        return CommandResult()
    if state.workspace_root and state.workspace_root != memory_runtime.workspace_root:
        if not confirm_cross_workspace_action("删除", state.workspace_root, memory_runtime.workspace_root):
            print("已取消跨工作目录删除。", flush=True)
            return CommandResult()

    deleted = memory_runtime.delete_session(delete_session_id)
    if not deleted:
        print(f"未找到会话：{delete_session_id}", flush=True)
        return CommandResult()
    print(f"已删除会话：{delete_session_id}", flush=True)
    if delete_session_id == current_session_id:
        return CommandResult(messages=[])
    return CommandResult()
