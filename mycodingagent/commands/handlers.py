from __future__ import annotations

import sys

from mycodingagent.commands.registry import CommandContext, CommandRegistry, CommandResult, CommandSpec
from mycodingagent.configuration import CONFIG
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
from mycodingagent.terminal_ui.application import TerminalCancelled, request_selection, request_text
from mycodingagent.terminal_ui.output import clear_terminal
from mycodingagent.terminal_ui.output import render_project_graph_bootstrap_tree
from mycodingagent.terminal_ui.session_selector import select_session_interactively
from mycodingagent.multi_agent import MultiAgentStore
from mycodingagent.multi_agent.context import run_summary_for_main_context
from mycodingagent.work_mode import WorkMode


def mark_long_term_memory_pending(context: CommandContext, session_id: str) -> None:
    if not session_id or context.long_term_memory_runtime is None:
        return
    try:
        context.long_term_memory_runtime.mark_session_pending(session_id)
    except Exception as exc:  # pragma: no cover - memory extraction must not break commands
        print(f"长期记忆待抽取标记失败：{exc}", flush=True)


def _current_model_name(context: CommandContext) -> str:
    model_manager = context.model_manager
    if model_manager is None:
        return ""
    try:
        return str(model_manager.active_model)
    except Exception:
        return ""


async def _choose_from_list(prompt: str, options: list[str]) -> int | None:
    return await request_selection(prompt, options)


async def _select_model_profile(context: CommandContext) -> tuple[str, str | None] | None:
    model_manager = context.model_manager
    if model_manager is None:
        print("模型管理器未启用，无法切换模型。", flush=True)
        return None
    try:
        model_manager.reload()
        grouped = model_manager.profiles_by_provider()
    except Exception as exc:
        print(f"读取模型配置失败：{exc}", flush=True)
        return None
    if not grouped:
        print("没有找到已配置 API 的推理模型 profile。请先编辑 ~/.mycodingagent/config.json。", flush=True)
        return None
    providers = sorted(grouped)
    provider_index = await _choose_from_list("请选择厂商：", providers)
    if provider_index is None:
        print("已取消模型切换。", flush=True)
        return None
    provider_name = providers[provider_index]
    profiles = sorted(grouped[provider_name], key=lambda item: (item.model, item.key))
    profile_labels = [f"{profile.model}  ({profile.key})" for profile in profiles]
    profile_index = await _choose_from_list(f"请选择 {provider_name} 模型：", profile_labels)
    if profile_index is None:
        print("已取消模型切换。", flush=True)
        return None
    profile = profiles[profile_index]
    reasoning: str | None = None
    try:
        provider = model_manager.provider(profile.key)
        reasoning_options = provider.reasoning_options(profile.model)
    except Exception as exc:
        print(f"读取思考模式失败，跳过该步骤：{exc}", flush=True)
        reasoning_options = []
    if reasoning_options:
        labels = [
            f"{option.label} ({option.name})" + (f" - {option.description}" if option.description else "")
            for option in reasoning_options
        ]
        reasoning_index = await _choose_from_list("请选择思考强度：", labels)
        if reasoning_index is None:
            print("已取消模型切换。", flush=True)
            return None
        reasoning = reasoning_options[reasoning_index].name
    return profile.key, reasoning


async def handle_model_command(context: CommandContext, arguments: str) -> CommandResult:
    selected = await _select_model_profile(context)
    if selected is None:
        return CommandResult(messages=context.messages)
    profile_key, reasoning = selected
    try:
        context.model_manager.switch_active(profile_key, reasoning=reasoning)
    except Exception as exc:
        print(f"切换主模型失败：{exc}", flush=True)
        return CommandResult(messages=context.messages)
    print(
        f"主模型已切换为 {context.model_manager.active_profile.provider}/{context.model_manager.active_model}"
        f"（profile: {context.model_manager.active_profile_key}）。",
        flush=True,
    )
    return CommandResult(messages=context.messages)


async def handle_long_mem_model_storage_command(context: CommandContext, arguments: str) -> CommandResult:
    return await _handle_long_mem_model_command(context, target="storage", label="长期记忆存储")


async def handle_long_mem_model_search_command(context: CommandContext, arguments: str) -> CommandResult:
    return await _handle_long_mem_model_command(context, target="search", label="长期记忆检索")


async def _handle_long_mem_model_command(context: CommandContext, *, target: str, label: str) -> CommandResult:
    selected = await _select_model_profile(context)
    if selected is None:
        return CommandResult(messages=context.messages)
    profile_key, reasoning = selected
    try:
        context.model_manager.switch_long_term_memory(target, profile_key, reasoning=reasoning)
    except Exception as exc:
        print(f"切换{label}模型失败：{exc}", flush=True)
        return CommandResult(messages=context.messages)
    profile = context.model_manager.profile(profile_key)
    print(f"{label}模型已切换为 {profile.provider}/{profile.model}（profile: {profile.key}）。", flush=True)
    return CommandResult(messages=context.messages)


def build_command_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(
        CommandSpec(
            name="/model",
            aliases=("model", "模型"),
            description="交互选择并切换当前主推理模型",
            usages=(("", "选择厂商、模型和可用思考强度"),),
            handler=handle_model_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/long_mem_model_storage",
            aliases=("long_mem_model_storage",),
            description="交互选择长期记忆存储/抽取模型",
            usages=(("", "选择厂商、模型和可用思考强度"),),
            handler=handle_long_mem_model_storage_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/long_mem_model_search",
            aliases=("long_mem_model_search",),
            description="交互选择长期记忆检索模型",
            usages=(("", "选择厂商、模型和可用思考强度"),),
            handler=handle_long_mem_model_search_command,
        )
    )
    registry.register(
        CommandSpec(
            name="/plan",
            aliases=("plan", "计划模式"),
            description="进入只禁止工作区写入与 Bash 的计划模式",
            handler=handle_plan_command,
        )
    )
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


async def handle_plan_command(context: CommandContext, arguments: str) -> CommandResult:
    if arguments.strip():
        print("用法：/plan", flush=True)
        return CommandResult()
    plan_runtime = context.plan_runtime
    if plan_runtime is None:
        print("Plan 运行时未启用。", flush=True)
        return CommandResult()
    plan_runtime.enter_plan_mode()
    print("已进入 Plan 模式。工作区写入与 Bash 已关闭。", flush=True)
    return CommandResult(messages=context.messages)


async def handle_mode_command(context: CommandContext, arguments: str) -> CommandResult:
    work_mode = context.work_mode
    graph_runtime = context.project_graph_runtime
    if work_mode is None or graph_runtime is None:
        print("工作模式运行时未启用。", flush=True)
        return CommandResult()
    try:
        answer = (await request_text(
            f"当前工作模式：{work_mode.current.value}。请选择 General 或 Code [general/code]："
        )).strip().lower()
    except (TerminalCancelled, EOFError, KeyboardInterrupt):
        print("已取消模式切换。", flush=True)
        return CommandResult()
    if answer not in {"general", "code"}:
        print("已取消模式切换；请输入 general 或 code。", flush=True)
        return CommandResult()
    selected = WorkMode.parse(answer)
    if selected is WorkMode.GENERAL:
        await graph_runtime.deactivate()
        print("工作模式已切换为 General。", flush=True)
        return CommandResult(messages=context.messages)
    if work_mode.current is WorkMode.CODE:
        print("当前已处于 Code 模式。", flush=True)
        return CommandResult(messages=context.messages)
    await _activate_code_mode(context, context.messages, force=work_mode.current is WorkMode.GENERAL)
    return CommandResult(messages=context.messages)


async def _activate_code_mode(
    context: CommandContext,
    messages: list[dict],
    *,
    force: bool,
) -> bool:
    graph_runtime = context.project_graph_runtime
    if graph_runtime is None:
        return False
    print("[项目图谱] Code 模式初始化开始。", flush=True)
    try:
        status = await graph_runtime.activate(
            lambda message: print(f"[项目图谱] {message}", flush=True)
        )
        print(
            "[项目图谱] Code 模式已就绪："
            f"{status.get('modules', 0)} 个模块，{status.get('units', 0)} 个单位。",
            flush=True,
        )
        update = await graph_runtime.prepare_bootstrap(messages, force=force)
        if update is not None:
            messages.extend(update.messages)
            render_project_graph_bootstrap_tree(update.payload)
        return True
    except Exception as exc:
        if context.work_mode is not None and context.work_mode.current is not WorkMode.GENERAL:
            await graph_runtime.deactivate()
        print(f"[项目图谱] 初始化失败：{type(exc).__name__}: {exc}", flush=True)
        return False


async def handle_rewind_command(context: CommandContext, arguments: str) -> CommandResult:
    memory_runtime = context.memory_runtime
    if memory_runtime is None:
        print("记忆模块未启用，无法回退。", flush=True)
        return CommandResult()
    checkpoints = memory_runtime.list_workspace_checkpoints()
    if not checkpoints:
        print("当前会话没有可用的工作区 checkpoint。", flush=True)
        return CommandResult()
    checkpoint_id = await select_checkpoint_interactively(checkpoints)
    if not checkpoint_id:
        print("已取消回退。", flush=True)
        return CommandResult()
    scope = await select_rewind_scope_interactively()
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
            if not await confirm_force_rewind(result.conflicts):
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
        clear_terminal()
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
            argument = (await request_text(
                "请输入多智能体任务，或 status / resume <run_id> / inspect <run_id>："
            )).strip()
        except (TerminalCancelled, EOFError, KeyboardInterrupt):
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

    if context.registry is None or context.model_manager is None:
        print("多智能体运行缺少 registry 或 model_manager，无法执行。", flush=True)
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
        model_manager=context.model_manager,
        memory_runtime=context.memory_runtime,
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
        resume_session_id = await select_session_interactively(memory_runtime, include_all=include_all)
        if not resume_session_id:
            return CommandResult()
    if resume_session_id == current_session_id and has_conversation_content(context.messages):
        if remove_trailing_incomplete_tool_call(context.messages):
            memory_runtime.save_messages_now(resume_session_id, context.messages)
        memory_runtime.touch_session(resume_session_id)
        clear_terminal()
        render_conversation_history(context.messages)
        print(f"已恢复会话：{resume_session_id}（{len(context.messages)} 条消息）", flush=True)
        return CommandResult(messages=context.messages)
    state = memory_runtime.load_session(resume_session_id)
    if state is None:
        print(f"未找到会话：{resume_session_id}", flush=True)
        return CommandResult()
    if state.workspace_root and state.workspace_root != memory_runtime.workspace_root:
        if not await confirm_cross_workspace_restore(state.workspace_root, memory_runtime.workspace_root):
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
    if context.work_mode is not None and context.project_graph_runtime is not None:
        requested_mode = WorkMode.parse(state.work_mode)
        if requested_mode is WorkMode.CODE:
            await _activate_code_mode(context, state.messages, force=context.work_mode.current is WorkMode.GENERAL)
        elif context.work_mode.current is WorkMode.CODE:
            await context.project_graph_runtime.deactivate()
    clear_terminal()
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
        source_session_id = await select_session_interactively(memory_runtime, include_all=include_all, action="分叉")
        if not source_session_id:
            return CommandResult()

    source_state = memory_runtime.store.load_session(source_session_id)
    if source_state is None:
        print(f"未找到会话：{source_session_id}", flush=True)
        return CommandResult()
    if source_state.workspace_root and source_state.workspace_root != memory_runtime.workspace_root:
        if not await confirm_cross_workspace_action("分叉", source_state.workspace_root, memory_runtime.workspace_root):
            print("已取消跨工作目录分叉。", flush=True)
            return CommandResult()

    fork_messages = source_state.messages
    if source_session_id == current_session_id and has_conversation_content(context.messages):
        fork_messages = context.messages
    if remove_trailing_incomplete_tool_call(fork_messages):
        memory_runtime.save_messages_now(source_session_id, fork_messages)
    fork_session_id = memory_runtime.fork_session(
        source_session_id,
        model=_current_model_name(context),
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
    if context.work_mode is not None and context.project_graph_runtime is not None:
        requested_mode = WorkMode.parse(source_state.work_mode)
        if requested_mode is WorkMode.CODE:
            await _activate_code_mode(context, fork_messages, force=context.work_mode.current is WorkMode.GENERAL)
        elif context.work_mode.current is WorkMode.CODE:
            await context.project_graph_runtime.deactivate()
    clear_terminal()
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
        clear_terminal()
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
    if context.plan_runtime is not None:
        context.plan_runtime.reset_current_session()
    memory_runtime.clear_current_session_id()
    new_session_id = memory_runtime.start_session(_current_model_name(context))
    await memory_runtime.drain()

    if saved_session_id:
        clear_terminal()
        print(f"已保存当前会话：{saved_session_id}", flush=True)
    else:
        clear_terminal()
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
        if not await confirm_delete_sessions(sessions, include_all=include_all):
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
        delete_session_id = await select_session_interactively(
            memory_runtime,
            limit=20,
            include_all=include_all,
            action="删除",
        )
        if not delete_session_id:
            return CommandResult()

    state = memory_runtime.store.load_session(delete_session_id)
    if state is None:
        print(f"未找到会话：{delete_session_id}", flush=True)
        return CommandResult()
    if state.workspace_root and state.workspace_root != memory_runtime.workspace_root:
        if not await confirm_cross_workspace_action("删除", state.workspace_root, memory_runtime.workspace_root):
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
