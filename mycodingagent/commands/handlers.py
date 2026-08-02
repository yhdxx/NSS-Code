from __future__ import annotations

import asyncio
import sys

from mycodingagent.commands.registry import CommandContext, CommandRegistry, CommandResult, CommandSpec
from mycodingagent.configuration import CONFIG
from mycodingagent.llm_runtime import client
from mycodingagent.memory.session_switch import has_conversation_content, save_current_session_if_needed
from mycodingagent.memory.message_filters import remove_trailing_incomplete_tool_call
from mycodingagent.terminal_ui.confirm import (
    confirm_force_rewind,
    confirm_cross_workspace_action,
    confirm_cross_workspace_restore,
    confirm_delete_sessions,
)
from mycodingagent.terminal_ui.checkpoint_selector import (
    select_checkpoint_interactively,
    select_rewind_scope_interactively,
)
from mycodingagent.terminal_ui.history import render_conversation_history
from mycodingagent.terminal_ui.interrupt import PromptCancelled, coordinated_input
from mycodingagent.terminal_ui.session_selector import select_session_interactively
from mycodingagent.multi_agent import MultiAgentStore
from mycodingagent.multi_agent.context import run_summary_for_main_context


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
            name="/mode",
            aliases=("mode", "工作模式"),
            description="交互选择 General 或 Code 工作模式",
            usages=(("", "显示并选择 General 或 Code"),),
            handler=handle_mode_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/rewind",
            aliases=("rewind", "回退"),
            description="选择用户轮次，并恢复该轮前的代码、会话或两者",
            usages=(("", "先选择轮次 ID，再选择 code/conversation/both 范围"),),
            handler=handle_rewind_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/resume",
            aliases=("resume", "恢复会话"),
            description="选择并恢复当前工作目录的历史会话",
            handler=handle_resume_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/fork",
            aliases=("fork", "分叉会话"),
            description="选择历史会话创建分叉，并切换到新会话",
            handler=handle_fork_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/clear",
            aliases=("clear", "清空会话"),
            description="保存当前会话，清空上下文，并启动新的空会话",
            handler=handle_clear_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/delete",
            aliases=("delete", "删除会话"),
            description="选择并删除当前工作目录的历史会话",
            handler=handle_delete_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/multiAgent",
            aliases=("/multiagent", "multiAgent", "multiagent", "多智能体"),
            description="输入任务或操作后启动多智能体工作流",
            handler=handle_multi_agent_command,
        )
    )
    return registry


async def handle_mode_command(context: CommandContext, arguments: str) -> CommandResult:
    memory_runtime = context.memory_runtime
    if memory_runtime is None:
        print("记忆模块未启用，无法持久化工作模式。", flush=True)
        return CommandResult()
    try:
        answer = coordinated_input(
            f"当前工作模式：{memory_runtime.work_mode}。请选择 General 或 Code [general/code]："
        ).strip().lower()
    except (PromptCancelled, EOFError, KeyboardInterrupt):
        print("已取消模式切换。", flush=True)
        return CommandResult()
    if answer not in {"general", "code"}:
        print("已取消模式切换；请输入 general 或 code。", flush=True)
        return CommandResult()
    memory_runtime.set_work_mode(answer)
    print(f"工作模式已切换为 {answer.title()}。", flush=True)
    if answer == "code" and context.registry is not None:
        graph_tool = context.registry.get("ProjectArchitecture")
        graph_service = getattr(graph_tool, "_service", None)
        build_graph = getattr(graph_service, "status", None)
        if callable(build_graph):
            print("[项目图谱] Code 模式初始化开始。", flush=True)
            try:
                status = await asyncio.to_thread(build_graph)
                print(
                    "[项目图谱] Code 模式已就绪："
                    f"{status.get('modules', 0)} 个模块，{status.get('units', 0)} 个单位。",
                    flush=True,
                )
            except Exception as exc:
                print(f"[项目图谱] 初始化失败：{type(exc).__name__}: {exc}", flush=True)
    return CommandResult(messages=context.messages)


async def handle_rewind_command(context: CommandContext, arguments: str) -> CommandResult:
    memory_runtime = context.memory_runtime
    if memory_runtime is None:
        print("记忆模块未启用，无法回退。", flush=True)
        return CommandResult()
    checkpoints = memory_runtime.list_workspace_checkpoints()
    if not checkpoints:
        print("当前会话没有可用的工作区 checkpoint。", flush=True)
        return CommandResult()
    checkpoint_id = select_checkpoint_interactively(checkpoints)
    if not checkpoint_id:
        print("已取消回退。", flush=True)
        return CommandResult()
    scope = select_rewind_scope_interactively()
    if not scope:
        print("已取消回退。", flush=True)
        return CommandResult()
    selected = next((item for item in checkpoints if item.checkpoint_id == checkpoint_id), None)
    if selected is None:
        print(f"未找到 checkpoint：{checkpoint_id}", flush=True)
        return CommandResult()

    updated_messages = context.messages
    if scope in {"code", "both"}:
        result = memory_runtime.rewind_workspace(checkpoint_id)
        if result.conflicts:
            if not confirm_force_rewind(result.conflicts):
                print("已取消回退，未覆盖外部修改。", flush=True)
                return CommandResult()
            result = memory_runtime.rewind_workspace(checkpoint_id, force=True)
        if result.errors:
            print("回退失败：" + "; ".join(result.errors), flush=True)
            return CommandResult()
        print(f"已恢复 {len(result.restored)} 个文件。", flush=True)
    if scope in {"conversation", "both"}:
        updated_messages = context.messages[: selected.message_index]
        session_id = memory_runtime.get_current_session_id()
        if session_id:
            memory_runtime.save_messages_now(session_id, updated_messages)
        render_conversation_history(updated_messages)
        print(f"已恢复会话（{len(updated_messages)} 条消息）。", flush=True)
    return CommandResult(messages=updated_messages)


async def handle_multi_agent_command(context: CommandContext, arguments: str) -> CommandResult:
    store = context.multi_agent_store or MultiAgentStore()
    argument = arguments.strip()
    if not argument:
        if not sys.stdin.isatty():
            print("当前终端不支持交互输入多智能体任务。", flush=True)
            return CommandResult()
        try:
            argument = coordinated_input(
                "请输入多智能体任务，或 status / resume <run_id> / inspect <run_id>："
            ).strip()
        except (PromptCancelled, EOFError, KeyboardInterrupt):
            print("已取消多智能体操作。", flush=True)
            return CommandResult()
    use_worktree = argument.startswith("--worktree ")
    if use_worktree:
        argument = argument[len("--worktree ") :].strip()
    if not argument:
        print("已取消多智能体操作。", flush=True)
        return CommandResult()
    if argument in {"--help", "-h", "help"}:
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

    from mycodingagent.multi_agent.orchestrator import MultiAgentOrchestrator
    from mycodingagent.multi_agent.models import RunStatus
    from mycodingagent.multi_agent.worktree import WorktreeManager

    worktree_manager = None
    worktree_handle = None
    if use_worktree:
        worktree_manager = WorktreeManager(CONFIG.sandbox.root, store.path.parent)
        try:
            worktree_handle = await worktree_manager.create()
        except ValueError as exc:
            print(str(exc), flush=True)
            return CommandResult()

    orchestrator = MultiAgentOrchestrator(
        store=store,
        registry=context.registry,
        api_client=context.api_client,
        memory_runtime=context.memory_runtime,
        model=client.MODEL,
        cancel_event=context.cancel_event,
        workspace_root=worktree_handle.path if worktree_handle is not None else None,
    )

    try:
        if argument.startswith("resume "):
            run_id = argument.split(maxsplit=1)[1].strip()
            run = await orchestrator.resume(run_id=run_id, main_messages=context.messages)
            user_content = f"/multiAgent resume {run_id}"
        else:
            if worktree_handle is None:
                run = await orchestrator.start(task=argument, main_messages=context.messages)
            else:
                with context.registry.retarget_sandbox(worktree_handle.path):
                    run = await orchestrator.start(task=argument, main_messages=context.messages)
            user_content = f"/multiAgent {argument}"
    except ValueError as exc:
        print(str(exc), flush=True)
        return CommandResult()

    if worktree_manager is not None and worktree_handle is not None:
        if run.status == RunStatus.COMPLETED:
            delivery = await worktree_manager.deliver(worktree_handle)
            if delivery.delivered:
                print("已将 worktree 变更交付到当前工作区。", flush=True)
            else:
                print(f"worktree 交付未完成：{delivery.error}", flush=True)
                print(f"已保留：{delivery.preserved_path}", flush=True)
        else:
            print(f"任务未完成，worktree 已保留：{worktree_handle.path}", flush=True)

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
        if remove_trailing_incomplete_tool_call(context.messages):
            memory_runtime.save_messages_now(resume_session_id, context.messages)
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
    if remove_trailing_incomplete_tool_call(state.messages):
        memory_runtime.save_messages_now(resume_session_id, state.messages)
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
    if remove_trailing_incomplete_tool_call(fork_messages):
        memory_runtime.save_messages_now(source_session_id, fork_messages)
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
