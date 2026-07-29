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
import pyfiglet  # 导入当前模块需要的依赖。

from openai import AsyncOpenAI  # 导入当前模块需要的依赖。

from mycodingagent.capability_discovery import CapabilityRouter
from mycodingagent.terminal_ui.input import read_user_prompt
from mycodingagent.commands import CommandContext
from mycodingagent.commands.handlers import build_command_registry
from mycodingagent.configuration import CONFIG  # 统一读取项目运行配置。
from mycodingagent.long_term_memory.runtime import LongTermMemoryRuntime
from mycodingagent.memory import MemoryRuntime
from mycodingagent.skill_runtime import SkillRuntime  # 管理开发者提供的 SKILL，并按需动态暴露给模型。
from mycodingagent.tool_runtime import create_default_registry  # 导入当前模块需要的依赖。
from mycodingagent.tool_runtime.bash import ensure_docker_image, get_docker_image  # 启动时确保 Bash 工具使用的 Docker 镜像已在本地可用。
from mycodingagent.tool_runtime.base import get_sandbox_root  # 读取当前沙盒根目录，供工作区变更监听使用。
from mycodingagent.tool_runtime.file_state_cache import FileStateCache  # 共享文件读取状态，判断用户是否修改了模型已读文件。
from mycodingagent.tool_runtime.mcp_discovery import register_mcp_discovery_tools
from mycodingagent.tool_runtime.mcp_execution import register_mcp_execution_tools
from mycodingagent.tool_runtime.workspace_change_tracker import WorkspaceChangeTracker  # 监听工作区文件变化并过滤模型自身写入。
from mycodingagent.mcp_integration import MCPClientManager, MCPConfigLoader
from mycodingagent.mcp_integration.hooks import CLIApprovalHook
from mycodingagent.mcp_integration.policy import MCPToolPermissionPolicy
from mycodingagent.llm_runtime import client  # 导入当前模块需要的依赖。
from multiAgent import MultiAgentStore
from multiAgent.tools import DelegateToMultiAgent, InspectSubAgentWork

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
    # 创建 OpenAI 客户端（复用连接）
    api_client = AsyncOpenAI(api_key=client.DEEPSEEK_API_KEY, base_url=client.BASE_URL)  # 保存配置值或中间计算结果。
    # 对话历史记录，跨轮次保持记忆
    messages: list[dict] = []  # 保存配置值或中间计算结果。
    registry = create_default_registry(  # 保存配置值或中间计算结果。
        file_state_cache=file_state_cache,
        workspace_tracker=workspace_tracker,
        memory_runtime=memory_runtime,
    )
    multi_agent_store = MultiAgentStore()
    registry.register(InspectSubAgentWork(multi_agent_store))
    registry.register(
        DelegateToMultiAgent(
            store=multi_agent_store,
            registry=registry,
            api_client=api_client,
            memory_runtime=memory_runtime,
            model=client.MODEL,
            main_messages_provider=lambda: messages,
        )
    )
    long_term_memory_runtime = None
    if memory_runtime is not None and CONFIG.long_term_memory.enabled:
        long_term_memory_runtime = LongTermMemoryRuntime(
            memory_runtime=memory_runtime,
            registry=registry,
            api_client=api_client,
            user_id=CONFIG.skills.user_id,
            storage_model=CONFIG.long_term_memory.storage_model or client.MODEL,
            query_model=CONFIG.long_term_memory.query_model or client.MODEL,
        )
    base_tool_schemas = registry.get_all_schemas("openai")  # 保存启动时已有的核心工具 schema；后续每轮保持稳定。
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
    skill_management_tool_names = {
        "search_tool",
        "Get_all_tool",
        "Get_tool_by_name",
        "search_skill_references",
        "Get_skill_reference",
        "invoke_skill",
    }
    skill_management_tool_schemas = [
        schema
        for schema in registry.get_all_schemas("openai")
        if schema.get("name") in skill_management_tool_names
    ]
    discovery_tool_schemas = [
        schema
        for schema in registry.get_all_schemas("openai")
        if schema.get("name") in discovery_tool_names
    ]
    core_tool_schemas = base_tool_schemas + skill_management_tool_schemas + discovery_tool_schemas
    tools = client.format_openai_tools(core_tool_schemas)  # 固定核心工具 schema；动态能力推荐进入 Runtime Context。
    command_registry = build_command_registry()
    if long_term_memory_runtime is not None:
        long_term_memory_runtime.schedule_startup_backfill()

    mcp_user_rounds = 0

    def get_messages() -> list[dict]:
        return messages

    def set_messages(new_messages: list[dict]) -> None:
        nonlocal messages
        messages = new_messages

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
                    registry=registry,
                    api_client=api_client,
                    multi_agent_store=multi_agent_store,
                    long_term_memory_runtime=long_term_memory_runtime,
                    capability_router=capability_router,
                    mcp_manager=mcp_manager,
                    tools=tools,
                    core_tool_schemas=core_tool_schemas,
                    get_messages=get_messages,
                    set_messages=set_messages,
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
                long_term_memory_runtime=long_term_memory_runtime,
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
            if mcp_manager is not None:
                mcp_user_rounds += 1
                if mcp_user_rounds % CONFIG.mcp.reconnect_server_step == 0:
                    mcp_manager.schedule_reconnect_unavailable_servers()
    finally:  # 执行无论是否异常都需要收尾的逻辑。
        if long_term_memory_runtime is not None and memory_runtime is not None:
            session_id = memory_runtime.get_current_session_id()
            if session_id and messages:
                memory_runtime.save_messages_now(session_id, messages)
                await memory_runtime.drain()
                await long_term_memory_runtime.extract_session_now(
                    session_id,
                    timeout_seconds=CONFIG.long_term_memory.graceful_exit_extract_timeout_seconds,
                )
            await long_term_memory_runtime.close()
        if memory_runtime is not None:
            await memory_runtime.close()
        if mcp_manager is not None:
            await mcp_manager.close()
        skill_runtime.close()  # 停止 SKILL 文件监听线程。
        workspace_tracker.close()  # 停止工作区文件监听线程。
        # 退出时关闭连接
        await api_client.close()  # 执行当前步骤的业务逻辑。
        print("\n连接已关闭，再见！")  # 执行当前步骤的业务逻辑。

if __name__ == "__main__":  # 根据条件决定是否执行后续分支。
    asyncio.run(main())  # 执行当前步骤的业务逻辑。
