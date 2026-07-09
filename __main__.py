# 用户在任意目录下输入 myAgent 都能进入到编码智能体中。
# 要求：
# 1. 启动 agent 时，告诉模型可以调用哪些工具；当前没有 skill 的情况下，只需要告诉模型六大基础编码工具。
# 2. 启动 agent 时，将当前工作目录作为沙箱环境。
# 3. 用户提出需求后，智能体根据需求执行命令。
# 4. 单次任务里智能体可以循环调用工具 `agent.loop()`，但存在循环轮次上限，防止死循环。
# 5. 每次将工具调用结果返回模型。
# 6. 重复循环，直到模型 `finish_reason` 为 `stop`，结束当前任务。
import os  # 导入当前模块需要的依赖。

for env_key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:  # 遍历集合中的元素。
    os.environ.pop(env_key, None)  # 执行当前步骤的业务逻辑。

import asyncio  # 导入当前模块需要的依赖。
import codecs
import select
import sys
import termios
import tty
import pyfiglet  # 导入当前模块需要的依赖。

from openai import AsyncOpenAI  # 导入当前模块需要的依赖。

from capabilities import CapabilityRouter
from cli_input import read_char_from_fd, read_escape_sequence_from_fd, read_user_prompt, render_screen, safe_render_columns
from commands import CommandContext, CommandRegistry, CommandResult, CommandSpec
from config import CONFIG  # 统一读取项目运行配置。
from conversation_history import render_conversation_history
from memory import MemoryRuntime, SessionListItem
from session_switch import has_conversation_content, save_current_session_if_needed
from skills import SkillRuntime  # 管理开发者提供的 SKILL，并按需动态暴露给模型。
from tools import create_default_registry  # 导入当前模块需要的依赖。
from tools.bash import ensure_docker_image, get_docker_image  # 启动时确保 Bash 工具使用的 Docker 镜像已在本地可用。
from tools.base import get_sandbox_root  # 读取当前沙盒根目录，供工作区变更监听使用。
from tools.file_state_cache import FileStateCache  # 共享文件读取状态，判断用户是否修改了模型已读文件。
from tools.mcp_discovery import register_mcp_discovery_tools
from tools.mcp_execution import register_mcp_execution_tools
from tools.workspace_change_tracker import WorkspaceChangeTracker  # 监听工作区文件变化并过滤模型自身写入。
from mcp_client import MCPClientManager, MCPConfigLoader
from mcp_client.hooks import CLIApprovalHook
from mcp_client.policy import MCPToolPermissionPolicy
import client  # 导入当前模块需要的依赖。

# 启用 readline 支持，增强命令行编辑功能（退格、方向键等自动生效）
try:  # 开始可能抛出异常的保护代码块。
    import readline  # noqa: F401
except ImportError:  # 捕获并处理指定异常。
    pass  # Windows 可能没有 readline，但不影响基本功能


async def main() -> None:  # 定义异步函数，供事件循环调用。

    ascii_art = pyfiglet.figlet_format("MyCodingAgent")  # 保存配置值或中间计算结果。
    print(ascii_art)  # 执行当前步骤的业务逻辑。

    docker_image = get_docker_image()  # 读取 Bash 工具后续执行命令时会使用的统一 Docker 镜像。
    print(f"检查 Bash Docker 镜像：{docker_image}", flush=True)  # 启动阶段明确告诉用户正在准备命令执行环境。
    image_result = await ensure_docker_image(docker_image)  # 如果镜像不存在，会在这里执行 docker pull。
    if image_result.is_error:  # Docker 不可用、权限不足或镜像拉取失败时，不继续进入对话。
        print(image_result.output)  # 打印具体错误，方便用户修复 Docker 环境或镜像配置。
        return  # Bash 环境无法准备时直接退出，避免后续模型调用命令全部失败。
    print(image_result.output, flush=True)  # 镜像已就绪时打印确认信息。

    file_state_cache = FileStateCache()  # 记录模型读过的文件，用于识别已读文件的外部变更。
    workspace_tracker = WorkspaceChangeTracker(get_sandbox_root(), file_state_cache)  # 监听工作区内已读文件的外部变更。
    workspace_tracker.start()  # 启动后台监听线程；不可用时静默降级为不提示。
    memory_runtime = MemoryRuntime(model=client.MODEL, workspace_root=str(get_sandbox_root())) if CONFIG.memory.enabled else None
    if memory_runtime is not None:
        deleted_count = memory_runtime.cleanup_expired_sessions()
        if deleted_count:
            print(f"已清理 {deleted_count} 个超过 {CONFIG.memory.session_ttl_days} 天未访问的会话。", flush=True)
    registry = create_default_registry(  # 保存配置值或中间计算结果。
        file_state_cache=file_state_cache,
        workspace_tracker=workspace_tracker,
        memory_runtime=memory_runtime,
    )
    base_tool_schemas = registry.get_all_schemas("openai")  # 保存核心工具 schema，后续每轮基于它动态追加 SKILL。
    skill_runtime = SkillRuntime(  # 同时加载内置预设 SKILL 和额外 SKILL 目录；不再自动监听当前工作区 skills 目录。
        skills_root=CONFIG.skills.root,
        skill_roots=CONFIG.skills.roots,
        registry=registry,
    )  # 结束上方的多行结构。
    skill_report = await skill_runtime.initialize()  # 启动时同步 SKILL，并注册 search_tool/skill 工具执行入口。
    print(skill_report.summary(), flush=True)  # 输出本次 SKILL 索引变化情况。
    mcp_manager: MCPClientManager | None = None
    capability_router: CapabilityRouter | None = None
    if CONFIG.mcp.enabled:
        mcp_manager = MCPClientManager(
            config_loader=MCPConfigLoader(
                project_path=CONFIG.mcp.project_config_path,
                user_path=CONFIG.mcp.user_config_path,
                env_path_var=CONFIG.mcp.env_config_var,
            )
        )
        try:
            await mcp_manager.initialize()
        except ValueError as exc:
            print(f"MCP config error: {exc}", flush=True)
        capability_router = CapabilityRouter(skill_runtime=skill_runtime, mcp_manager=mcp_manager)
        register_mcp_discovery_tools(registry, manager=mcp_manager, router=capability_router)
        register_mcp_execution_tools(
            registry,
            manager=mcp_manager,
            policy=MCPToolPermissionPolicy(),
            approval_hook=CLIApprovalHook(),
        )
        print(f"MCP servers configured: {mcp_manager.server_count()}", flush=True)
    else:
        capability_router = CapabilityRouter(skill_runtime=skill_runtime, mcp_manager=None)
    discovery_tool_names = {
        "list_servers",
        "search_servers",
        "list_tools",
        "search_tools",
        "list_resources",
        "search_resources",
        "list_prompts",
        "search_prompts",
        "call_tool",
        "read_resource",
        "get_prompt",
    }
    discovery_tool_schemas = [
        schema
        for schema in registry.get_all_schemas("openai")
        if schema.get("name") in discovery_tool_names
    ]
    core_tool_schemas = base_tool_schemas + discovery_tool_schemas
    tools = client.format_openai_tools(core_tool_schemas)  # 无 SKILL runtime 时的兜底工具 schema；实际对话每轮会动态构造。
    command_registry = build_command_registry()

    # 创建 OpenAI 客户端（复用连接）
    api_client = AsyncOpenAI(api_key=client.DEEPSEEK_API_KEY, base_url=client.BASE_URL)  # 保存配置值或中间计算结果。

    # 对话历史记录，跨轮次保持记忆
    messages: list[dict] = []  # 保存配置值或中间计算结果。

    try:  # 开始可能抛出异常的保护代码块。
        while True:  # 在条件满足时持续循环。
            if memory_runtime is not None:
                rollover = await memory_runtime.await_pending_rollover()
                if rollover.performed and rollover.new_messages is not None:
                    messages = rollover.new_messages
            try:  # 开始可能抛出异常的保护代码块。
                print("----------------------------------------------\n\n")  # 执行当前步骤的业务逻辑。
                prompt = read_user_prompt("\001\033[7m\002 ⌨️  User(输入exit退出对话)： \001\033[0m\002", command_registry)  # 保存配置值或中间计算结果。

                # 重置颜色（readline 模式下用 \001\002 包裹后，这里不需要额外 print）
                # print 还是会输出，但作为安全兜底保留
                print("----------------------------------------------\n\n")  # 执行当前步骤的业务逻辑。
            except (EOFError, KeyboardInterrupt):  # 捕获并处理指定异常。
                # Ctrl+D 或 Ctrl+C 安全退出
                print()  # 执行当前步骤的业务逻辑。
                break  # 提前结束当前循环。
            if prompt.strip() == "exit":  # 根据条件决定是否执行后续分支。
                break  # 提前结束当前循环。
            if not prompt.strip():  # 根据条件决定是否执行后续分支。
                continue  # 空输入重新提示
            command_result = await command_registry.execute(
                prompt,
                CommandContext(
                    memory_runtime=memory_runtime,
                    skill_runtime=skill_runtime,
                    messages=messages,
                    file_state_cache=file_state_cache,
                    workspace_tracker=workspace_tracker,
                ),
            )
            if command_result.handled:
                if command_result.messages is not None:
                    messages = command_result.messages
                    if memory_runtime is not None:
                        rollover = await memory_runtime.on_turn_completed(
                            messages=messages,
                            skill_runtime=skill_runtime,
                            file_state_cache=file_state_cache,
                            workspace_tracker=workspace_tracker,
                            system_prompt_source=messages[0] if messages else None,
                        )
                        if rollover.performed and rollover.new_messages is not None:
                            messages = rollover.new_messages
                if command_result.should_exit:
                    break
                continue

            # 携带历史消息进行对话，并获取更新后的消息列表
            # 注意：首次对话不传 messages（None），让 ask_deepseek 自动注入系统提示词 "H-Agent"
            _, messages = await client.ask_deepseek(  # 保存配置值或中间计算结果。
                api_client,
                prompt,
                registry,
                tools,
                messages or None,
                skill_runtime=skill_runtime,
                core_tool_schemas=core_tool_schemas,
                workspace_tracker=workspace_tracker,
                memory_runtime=memory_runtime,
                capability_router=capability_router,
            )  # 结束上方的多行结构。
            if memory_runtime is not None:
                rollover = await memory_runtime.on_turn_completed(
                    messages=messages,
                    skill_runtime=skill_runtime,
                    file_state_cache=file_state_cache,
                    workspace_tracker=workspace_tracker,
                    system_prompt_source=messages[0] if messages else None,
                    tools=tools,
                    current_prompt=prompt,
                )
                if rollover.performed and rollover.new_messages is not None:
                    messages = rollover.new_messages
    finally:  # 执行无论是否异常都需要收尾的逻辑。
        if memory_runtime is not None:
            await memory_runtime.close()
        if mcp_manager is not None:
            await mcp_manager.close()
        skill_runtime.close()  # 停止 SKILL 文件监听线程。
        workspace_tracker.close()  # 停止工作区文件监听线程。
        # 退出时关闭连接
        await api_client.close()  # 执行当前步骤的业务逻辑。
        print("\n连接已关闭，再见！")  # 执行当前步骤的业务逻辑。

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
    return registry


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


def select_session_interactively(
    memory_runtime: MemoryRuntime,
    *,
    limit: int = 20,
    include_all: bool = False,
    action: str = "恢复",
) -> str:
    sessions = memory_runtime.list_sessions(limit=limit, include_all=include_all)
    if not sessions:
        if include_all:
            print(f"暂无可{action}会话。", flush=True)
        else:
            command = command_for_session_action(action)
            print(f"当前工作目录下没有历史会话。可使用 {command} --all 查看其他工作目录会话。", flush=True)
            migrated_sessions = memory_runtime.list_migrated_workspace_sessions(limit=limit)
            if migrated_sessions:
                print(f"检测到可能来自迁移前同一项目的会话，可使用 {command} --all 查看。", flush=True)
        return ""
    if not sys.stdin.isatty():
        command = command_for_session_action(action)
        print(f"当前终端不支持方向键选择，使用 {command} <session_id> {action}指定会话。", flush=True)
        print_session_options(sessions, include_workspace=include_all)
        return ""

    selected = 0
    hidden_cursor = False
    rendered_selector_rows = 0
    input_fd = sys.stdin.fileno()
    decoder = codecs.getincrementaldecoder(sys.stdin.encoding or "utf-8")()
    try:
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(input_fd)
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
        hidden_cursor = True
        rendered_selector_rows = render_session_selector(
            sessions,
            selected,
            previous_row_count=rendered_selector_rows,
            include_workspace=include_all,
            action=action,
        )
        while True:
            char = read_char_from_fd(input_fd, decoder)
            if char in {"\r", "\n"}:
                clear_session_selector(rendered_selector_rows)
                return sessions[selected].session_id
            if char == "\x03":
                clear_session_selector(rendered_selector_rows)
                print(f"已取消{action}会话。", flush=True)
                return ""
            if char == "\x1b":
                seq = read_escape_sequence_from_fd(input_fd, decoder, timeout=0.5)
                if not seq:
                    clear_session_selector(rendered_selector_rows)
                    print(f"已取消{action}会话。", flush=True)
                    return ""
                if seq == "[A":
                    selected = (selected - 1) % len(sessions)
                elif seq == "[B":
                    selected = (selected + 1) % len(sessions)
                else:
                    clear_session_selector(rendered_selector_rows)
                    print(f"已取消{action}会话。", flush=True)
                    return ""
                rendered_selector_rows = render_session_selector(
                    sessions,
                    selected,
                    previous_row_count=rendered_selector_rows,
                    include_workspace=include_all,
                    action=action,
                )
    finally:
        if "old_settings" in locals():
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        decoder.reset()
        if hidden_cursor:
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()


def render_session_selector(
    sessions: list[SessionListItem],
    selected: int,
    *,
    previous_row_count: int = 0,
    include_workspace: bool = False,
    action: str = "恢复",
) -> int:
    if previous_row_count > 0:
        clear_session_selector(previous_row_count)
    logical_lines = [f"请选择要{action}的会话（↑/↓ 选择，Enter 确认，Esc/Ctrl+C 取消）："]
    logical_lines.extend(
        format_session_option(session, selected=index == selected, include_workspace=include_workspace)
        for index, session in enumerate(sessions)
    )
    screen = render_screen(logical_lines, safe_render_columns())
    sys.stdout.write("\r")
    sys.stdout.write("\r\n".join(screen.lines))
    if len(screen.lines) > 1:
        sys.stdout.write(f"\033[{len(screen.lines) - 1}A")
    sys.stdout.write("\r")
    sys.stdout.flush()
    return len(screen.lines)


def clear_session_selector(rendered_row_count: int) -> None:
    if rendered_row_count <= 0:
        return
    sys.stdout.write("\r")
    for index in range(rendered_row_count):
        sys.stdout.write("\033[2K")
        if index < rendered_row_count - 1:
            sys.stdout.write("\033[1B")
    if rendered_row_count > 1:
        sys.stdout.write(f"\033[{rendered_row_count - 1}A")
    sys.stdout.write("\r")
    sys.stdout.flush()


def print_session_options(sessions: list[SessionListItem], *, include_workspace: bool = False) -> None:
    for session in sessions:
        print(format_session_option(session, selected=False, include_workspace=include_workspace), flush=True)


def command_for_session_action(action: str) -> str:
    return {
        "恢复": "/resume",
        "分叉": "/fork",
        "清空": "/clear",
        "删除": "/delete",
    }.get(action, "/resume")


def format_session_option(session: SessionListItem, *, selected: bool, include_workspace: bool = False) -> str:
    marker = ">" if selected else " "
    short_id = session.session_id[:8]
    workspace = f" [{session.workspace_label or session.workspace_root}]" if include_workspace else ""
    return f"{marker} [{short_id}]{workspace} {session.preview}（{session.message_count} 条消息）"


def confirm_cross_workspace_restore(source_workspace: str, current_workspace: str) -> bool:
    return confirm_cross_workspace_action("恢复", source_workspace, current_workspace)


def confirm_delete_sessions(sessions: list[SessionListItem], *, include_all: bool) -> bool:
    scope = "全部工作目录" if include_all else "当前工作目录"
    print(f"将删除{scope}下 {len(sessions)} 个会话：", flush=True)
    print_session_options(sessions[:10], include_workspace=include_all)
    if len(sessions) > 10:
        print(f"  ... 另有 {len(sessions) - 10} 个会话未列出", flush=True)
    answer = input(f"确认删除{scope}下全部会话？输入 y 确认，其它任意键取消：").strip().lower()
    return answer in {"y", "yes"}


def confirm_cross_workspace_action(action: str, source_workspace: str, current_workspace: str) -> bool:
    print("该会话来自其他工作目录：", flush=True)
    print(f"  来源：{source_workspace}", flush=True)
    print(f"  当前：{current_workspace}", flush=True)
    if action == "恢复":
        print("恢复后会加载历史对话，并按当前工作目录重新检查文件状态。", flush=True)
    elif action == "分叉":
        print("分叉后会复制历史对话到新会话，并按当前工作目录重新检查文件状态。", flush=True)
    else:
        print("删除后该会话及其关联消息、工具输出、压缩快照会从本地移除。", flush=True)
    answer = input(f"确认{action}？输入 y 确认，其它任意键取消：").strip().lower()
    return answer in {"y", "yes"}

if __name__ == "__main__":  # 根据条件决定是否执行后续分支。
    asyncio.run(main())  # 执行当前步骤的业务逻辑。
