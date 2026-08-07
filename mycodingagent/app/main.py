# 用户在任意目录下输入 myAgent 都能进入到编码智能体中。
# 要求：
# 1. 启动 agent 时，告诉模型可以调用哪些工具；当前没有 skill 的情况下，只需要告诉模型六大基础编码工具。
# 2. 启动 agent 时，将当前工作目录作为沙箱环境。
# 3. 用户提出需求后，智能体根据需求执行命令。
# 4. 单次任务里智能体可以循环调用工具 `agent.loop()`，但存在循环轮次上限，防止死循环。
# 5. 每次将工具调用结果返回模型。
# 6. 重复循环，直到模型 `finish_reason` 为 `stop`，结束当前任务。
import asyncio  # 导入当前模块需要的依赖。
import json
import sys  # 判断标准输入是否为交互式终端，决定是否启用高危命令审批。
import traceback
from pathlib import Path
from typing import Any, Awaitable

import pyfiglet  # 导入当前模块需要的依赖。

from mycodingagent.approval import ApprovalRuntime
from mycodingagent.capability_discovery import CapabilityRouter
from mycodingagent.code_intelligence import ProjectGraphRuntime, ProjectGraphService, WorkspaceCodeIndex
from mycodingagent.workspace_runtime import WorkspaceRuntime
from mycodingagent.terminal_ui.application import TerminalApplication, TerminalCancelled
from mycodingagent.terminal_ui.output import render_project_graph_bootstrap_tree
from mycodingagent.commands import CommandContext
from mycodingagent.commands.handlers import build_command_registry
from mycodingagent.configuration.bootstrap import USER_CONFIG_PATH, USER_CONFIG_README_PATH
from mycodingagent.configuration.settings import CONFIG
from mycodingagent.long_term_memory.runtime import LongTermMemoryRuntime
from mycodingagent.long_term_memory.store import SQLiteLongTermMemoryStore
from mycodingagent.media_runtime import MediaModelRuntime
from mycodingagent.web_fetch_runtime import WebFetchRuntime
from mycodingagent.network_access import NetworkAccessRuntime
from mycodingagent.managed_network import ManagedNetworkRuntime
from mycodingagent.memory import MemoryRuntime
from mycodingagent.memory.stores import SQLiteMemoryStore
from mycodingagent.skill_runtime import SkillRuntime  # 管理开发者提供的 SKILL，并按需动态暴露给模型。
from mycodingagent.sqlite_utils import IncompatibleSchemaError
from mycodingagent.tool_runtime import create_default_registry  # 导入当前模块需要的依赖。
from mycodingagent.tool_runtime.bash import (
    check_docker_swap_limit_support,
    ensure_docker_image,
    get_docker_image,
)
from mycodingagent.tool_runtime.base import get_sandbox_root  # 读取当前沙盒根目录，供工作区变更监听使用。
from mycodingagent.tool_runtime.command_policy import CLICommandApprovalHook  # 高危 Bash 命令执行前征求用户同意。
from mycodingagent.tool_runtime.command_policy import (
    BashPolicyEvaluator,
    BashPolicyEvidence,
    BashPolicyStore,
    SubmitBashApproval,
    SubmitBashHighRisk,
    SubmitBashLowRisk,
)
from mycodingagent.tool_runtime.file_state_cache import FileStateCache  # 共享文件读取状态，判断用户是否修改了模型已读文件。
from mycodingagent.tool_runtime.playwright_direct import register_discovered_playwright_tools
from mycodingagent.tool_runtime.mcp_discovery import register_mcp_discovery_tools
from mycodingagent.tool_runtime.mcp_execution import register_mcp_execution_tools
from mycodingagent.tool_runtime.workspace_change_tracker import WorkspaceChangeTracker  # 监听工作区文件变化并过滤模型自身写入。
from mycodingagent.workspace.lease import WorkspaceLease, WorkspaceLeaseError
from mycodingagent.workspace.state import workspace_state_dir, workspace_state_path
from mycodingagent.mcp_integration import MCPClientManager, MCPConfigLoader
from mycodingagent.mcp_integration.cache import MCPMetadataCache
from mycodingagent.mcp_integration.hooks import CLIApprovalHook, CLILaunchApprovalHook, MCPToolApprovalHook
from mycodingagent.mcp_integration.policy import MCPToolPermissionPolicy
from mycodingagent.llm_runtime import client  # 导入当前模块需要的依赖。
from mycodingagent.llm_runtime.model_manager import ModelManager
from mycodingagent.multi_agent import MultiAgentStore
from mycodingagent.work_mode import WorkMode, WorkModeManager
from mycodingagent.plan_runtime import CreatePlan, PlanRuntime, UpdatePlanStep
from mycodingagent.app.shutdown import (
    close_with_network_dependency,
    spawn_runtime_cleanup,
    spawn_stale_runtime_cleanup,
)


class StartupConfigurationError(RuntimeError):
    pass


def _exit_plan_mode_from_terminal(plan_runtime: PlanRuntime) -> bool:
    if not plan_runtime.is_planning:
        return False
    plan_runtime.exit_plan_mode()
    return True


def _configuration_error_message(errors: list[str]) -> str:
    return (
        "启动配置无效。\n"
        f"请编辑配置文件：{USER_CONFIG_PATH}\n"
        f"配置教程已同步到：{USER_CONFIG_README_PATH}\n\n"
        "最小可用配置：\n"
        "  model.active                         当前主推理模型 profile key\n"
        "  model.providers.<provider>.api       该厂商统一 API Key\n"
        "  model.profiles.<key>.provider        厂商，例如 deepseek/qwen/openai/anthropic\n"
        "  model.profiles.<key>.model           模型名称\n\n"
        "常用模型组合配置：\n"
        "  model.long_term_memory.storage    长期记忆存储/抽取模型 profile\n"
        "  model.long_term_memory.search     长期记忆检索模型 profile\n"
        "  embedding.provider/model/endpoint 嵌入模型与端点\n"
        "  milvus.host/port/collection       Skill 向量索引存储\n\n"
        "具体问题：\n"
        + "\n".join(f"  - {error}" for error in errors)
    )


async def main() -> int:  # 定义异步函数，供事件循环调用。
    terminal = TerminalApplication()
    await terminal.start()
    startup_error: str | None = None
    try:
        try:
            await _run(terminal)
        except (IncompatibleSchemaError, StartupConfigurationError, WorkspaceLeaseError) as exc:
            startup_error = f"无法启动：{exc}"
        except Exception as exc:
            startup_error = f"无法启动：{type(exc).__name__}: {exc}"
            if CONFIG.client.debug:
                startup_error += "\n" + traceback.format_exc()
    finally:
        await asyncio.sleep(0)
        await terminal.close()
    if startup_error is not None:
        print(startup_error, file=sys.stderr, flush=True)
        return 1
    return 0


async def _run(terminal: TerminalApplication) -> None:
    model_manager = ModelManager()
    config_errors = [
        *model_manager.validation_errors(
            require_long_term_memory=CONFIG.long_term_memory.enabled,
        ),
        *CONFIG.embedding.validation_errors(),
        *CONFIG.approval.validation_errors(),
    ]
    if config_errors:
        await model_manager.close()
        raise StartupConfigurationError(_configuration_error_message(config_errors))

    ascii_art = pyfiglet.figlet_format("MyCodingAgent")  # 保存配置值或中间计算结果。
    print(ascii_art)  # 执行当前步骤的业务逻辑。

    docker_image = get_docker_image()  # 读取 Bash 工具后续执行命令时会使用的统一 Docker 镜像。
    print(f"检查 Bash Docker 镜像：{docker_image}", flush=True)  # 启动阶段明确告诉用户正在准备命令执行环境。
    image_result = await ensure_docker_image(docker_image)  # 如果镜像不存在，会在这里执行 docker pull。
    if image_result.is_error:  # Docker 不可用、权限不足或镜像拉取失败时，不继续进入对话。
        print(image_result.output)  # 打印具体错误，方便用户修复 Docker 环境或镜像配置。
        await model_manager.close()
        return  # Bash 环境无法准备时直接退出，避免后续模型调用命令全部失败。
    print(image_result.output, flush=True)  # 镜像已就绪时打印确认信息。
    swap_limit_notice = await check_docker_swap_limit_support()
    if swap_limit_notice:
        print(f"Docker 资源限制提示：{swap_limit_notice}", flush=True)

    workspace_root = get_sandbox_root()
    media_runtime = MediaModelRuntime(CONFIG.model, sandbox_root=workspace_root)
    network_access = NetworkAccessRuntime(enabled=CONFIG.network.enabled)
    managed_network = ManagedNetworkRuntime(
        CONFIG.network,
        network_access,
        workspace_root=workspace_root,
    )
    network_status = await managed_network.initialize()
    if not network_status.ready:
        print(f"Runtime 托管网络未就绪：{network_status.reason}", flush=True)
        await media_runtime.close()
        await model_manager.close()
        return
    print(
        "Runtime 托管网络已就绪："
        f"公网{'开启' if network_access.enabled else '关闭'}，"
        f"上游代理={managed_network.display_upstream()}，容器直连已禁用。",
        flush=True,
    )
    terminal.set_network_enabled(network_access.enabled)
    audio_availability = media_runtime.audio_availability()
    vision_availability = media_runtime.vision_availability()
    if not audio_availability.enabled:
        print(f"音频转写工具未启用：{audio_availability.reason}", flush=True)
    if not vision_availability.enabled:
        print(f"视觉识别工具未启用：{vision_availability.reason}", flush=True)

    project_state_dir = workspace_state_dir(workspace_root)
    workspace_runtime = WorkspaceRuntime(workspace_root, managed_network)
    workspace_lease = WorkspaceLease(workspace_root, project_state_dir)
    if CONFIG.sandbox.workspace_lease_enabled:
        try:
            workspace_lease.acquire()
        except WorkspaceLeaseError:
            await managed_network.close()
            await media_runtime.close()
            await model_manager.close()
            raise
        spawn_stale_runtime_cleanup(
            workspace_root=workspace_root,
            excluded_runtime_ids=(managed_network.runtime_id, workspace_runtime.runtime_id),
        )
    workspace_runtime_error = await workspace_runtime.initialize()
    if not workspace_runtime_error:
        workspace_runtime_error = await workspace_runtime.ensure_container()
    if workspace_runtime_error:
        print(f"工作区运行容器未就绪：{workspace_runtime_error}", flush=True)
    web_fetch_runtime = WebFetchRuntime(
        CONFIG.web_fetch,
        network_access=network_access,
        proxy_url=managed_network.proxy_url,
    )
    file_state_cache = FileStateCache()  # 记录模型读过的文件，用于识别已读文件的外部变更。
    workspace_tracker = WorkspaceChangeTracker(get_sandbox_root(), file_state_cache)  # 监听工作区内已读文件的外部变更。
    workspace_tracker.start()  # 启动后台监听线程；不可用时静默降级为不提示。
    memory_runtime = (
        MemoryRuntime(
            model=model_manager.active_model,
            workspace_root=str(workspace_root),
            store=SQLiteMemoryStore(workspace_state_path(workspace_root, "sessions.sqlite3")),
        )
        if CONFIG.memory.enabled
        else None
    )

    def current_plan_session_id() -> str:
        if memory_runtime is None:
            return "runtime"
        return memory_runtime.get_current_session_id() or memory_runtime.start_session(model_manager.active_model)

    plan_runtime = PlanRuntime(
        store=memory_runtime.store if memory_runtime is not None else None,
        session_id=current_plan_session_id,
    )
    plan_runtime.bind_mode_listener(
        lambda mode: terminal.set_interaction_mode(mode.value)
    )
    approval_runtime = ApprovalRuntime(CONFIG.approval.mode)
    code_index = WorkspaceCodeIndex(
        workspace_root, workspace_state_path(workspace_root, "code_index.sqlite3")
    )
    project_graph = ProjectGraphService(
        workspace_root,
        workspace_state_path(workspace_root, "project_graph.sqlite3"),
        code_index,
    )
    requested_work_mode = (
        memory_runtime.work_mode if memory_runtime is not None else CONFIG.memory.default_work_mode
    )
    work_mode = WorkModeManager(
        WorkMode.GENERAL,
        persist=memory_runtime.set_work_mode if memory_runtime is not None else None,
    )
    project_graph_runtime = ProjectGraphRuntime(project_graph, code_index, work_mode)
    workspace_tracker.subscribe(project_graph_runtime.mark_dirty)
    if memory_runtime is not None:
        deleted_count = memory_runtime.cleanup_expired_sessions()
        if deleted_count:
            print(f"已清理 {deleted_count} 个超过 {CONFIG.memory.session_ttl_days} 天未访问的会话。", flush=True)
        expired_checkpoints, expired_blobs = memory_runtime.cleanup_expired_workspace_snapshots()
        if expired_checkpoints or expired_blobs:
            print(
                f"已清理 {expired_checkpoints} 个过期 workspace checkpoint 和 {expired_blobs} 个 snapshot blob。",
                flush=True,
            )
    async def classify_bash_policy(evidence: BashPolicyEvidence):
        """Classify one command name/event through one no-argument tool."""
        prompt = (
            Path(__file__).resolve().parents[1]
            / "multi_agent"
            / "prompts"
            / "bash_command_classification"
            / "SYSTEM.md"
        ).read_text(encoding="utf-8")
        schemas = []
        for tool_cls in (SubmitBashLowRisk, SubmitBashApproval, SubmitBashHighRisk):
            tool = tool_cls(lambda _level: None)
            schema = tool.get_schema()
            schemas.append({
                "name": schema["name"],
                "description": schema["description"],
                "parameters": schema["input_schema"],
            })
        response = await model_manager.active_provider().stream_chat(
            client.ChatRequest(
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "policy_key": evidence.policy_key,
                                "entry_type": evidence.entry_type,
                                "name": evidence.name,
                                "source_text": evidence.source_text,
                                "reason": evidence.reason,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                tools=client.format_openai_tools(schemas),
                display=False,
                output_label="bash_policy",
                tool_choice="required",
                temperature=0,
            )
        )
        tool_calls = response.tool_calls
        if not tool_calls:
            return "approval"
        return {
            "SubmitBashLowRisk": "low",
            "SubmitBashApproval": "approval",
            "SubmitBashHighRisk": "high",
        }.get(tool_calls[0].tool_name, "approval")
    # 对话历史记录，跨轮次保持记忆
    messages: list[dict] = []  # 保存配置值或中间计算结果。
    command_approval_hook = (
        CLICommandApprovalHook(terminal, approval_runtime=approval_runtime)
        if sys.stdin.isatty()
        else None
    )
    registry = create_default_registry(  # 保存配置值或中间计算结果。
        file_state_cache=file_state_cache,
        workspace_tracker=workspace_tracker,
        memory_runtime=memory_runtime,
        command_approval_hook=command_approval_hook,
        terminal_input=terminal,
        project_graph_service=project_graph_runtime,
        bash_policy_evaluator=BashPolicyEvaluator(
            BashPolicyStore(CONFIG.memory.db_path),
            classify_bash_policy,
        ),
        media_runtime=media_runtime,
        web_fetch_runtime=web_fetch_runtime if CONFIG.web_fetch.enabled else None,
        workspace_runtime=None if workspace_runtime_error else workspace_runtime,
    )
    registry.register(CreatePlan(plan_runtime))
    registry.register(UpdatePlanStep(plan_runtime))
    multi_agent_store = MultiAgentStore(workspace_state_path(workspace_root, "multi_agent.sqlite3"))
    long_term_memory_runtime = None
    if memory_runtime is not None and CONFIG.long_term_memory.enabled:
        long_term_memory_runtime = LongTermMemoryRuntime(
            memory_runtime=memory_runtime,
            registry=registry,
            model_manager=model_manager,
            user_id=CONFIG.skills.user_id,
            store=SQLiteLongTermMemoryStore(workspace_state_path(workspace_root, "project_memory.sqlite3")),
            global_store=SQLiteLongTermMemoryStore(CONFIG.memory.db_path),
        )
    base_tool_schemas = registry.get_all_schemas("openai")  # 保存启动时已有的核心工具 schema；后续每轮保持稳定。
    skill_runtime = SkillRuntime(  # 同时加载内置预设 SKILL 和额外 SKILL 目录；不再自动监听当前工作区 skills 目录。
        skills_root=CONFIG.skills.root,
        skill_roots=CONFIG.skills.roots,
        registry=registry,
        summary_provider_getter=model_manager.active_provider,
    )  # 结束上方的多行结构。
    await skill_runtime.initialize()  # 启动时同步 SKILL，并注册 search_skill/skill 工具执行入口。
    if long_term_memory_runtime is not None:
        long_term_memory_runtime.set_skill_materializer(skill_runtime.materialize_dynamic_skill)
    mcp_manager: MCPClientManager | None = None
    playwright_direct_tool_names: set[str] = set()
    capability_router: CapabilityRouter | None = None
    if CONFIG.mcp.enabled:
        mcp_manager = MCPClientManager(
            config_loader=MCPConfigLoader(
                project_path=CONFIG.mcp.project_config_path,
                user_path=CONFIG.mcp.user_config_path,
                secret_overrides={"TAVILY_API_KEY": CONFIG.search.tavily_api_key},
            ),
            metadata_cache=MCPMetadataCache(workspace_state_path(workspace_root, "mcp_cache.sqlite3")),
            launch_hook=(
                CLILaunchApprovalHook(terminal, approval_runtime=approval_runtime)
                if sys.stdin.isatty()
                else None
            ),
            network_access=network_access,
            network_runtime=managed_network,
            playwright_network="" if workspace_runtime_error else workspace_runtime.network_name,
            playwright_output_dir=(
                None if workspace_runtime_error else workspace_runtime.playwright_output_dir
            ),
            playwright_output_container_path=str(workspace_runtime.playwright_output_container_path),
            workspace_root=workspace_root,
        )
        try:
            await mcp_manager.initialize()
        except ValueError as exc:
            print(f"MCP 配置错误：{exc}", flush=True)
        capability_router = CapabilityRouter(skill_runtime=skill_runtime, mcp_manager=mcp_manager)
        mcp_approval_hook = (
            CLIApprovalHook(terminal, approval_runtime=approval_runtime)
            if sys.stdin.isatty()
            else MCPToolApprovalHook()
        )
        if "playwright" in mcp_manager.server_configs:
            summary = await mcp_manager.refresh_server("playwright")
            if summary is not None and summary.available:
                count = register_discovered_playwright_tools(
                    registry,
                    manager=mcp_manager,
                    policy=MCPToolPermissionPolicy(),
                    approval_hook=mcp_approval_hook,
                )
                playwright_direct_tool_names = {
                    tool.name
                    for tool in registry.list_tools()
                    if bool(getattr(tool, "is_playwright_tool", False))
                }
                print(f"已加载 Playwright 直接工具：{count} 个", flush=True)
            else:
                error = summary.error if summary is not None else "无法初始化"
                print(f"Playwright 直接工具未加载：{error}", flush=True)
        register_mcp_discovery_tools(registry, manager=mcp_manager, router=capability_router)
        register_mcp_execution_tools(
            registry,
            manager=mcp_manager,
            policy=MCPToolPermissionPolicy(),
            approval_hook=mcp_approval_hook,
        )
        print(f"已配置 MCP Server：{mcp_manager.server_count()} 个", flush=True)
    else:
        capability_router = CapabilityRouter(skill_runtime=skill_runtime, mcp_manager=None)
    discovery_tool_names = {
        "list_mcp_servers",
        "search_mcp_servers",
        "list_mcp_tools",
        "search_mcp_tools",
        "list_mcp_resources",
        "search_mcp_resources",
        "list_mcp_prompts",
        "search_mcp_prompts",
        "call_mcp_tool",
        "read_mcp_resource",
        "get_mcp_prompt",
    }
    skill_management_tool_names = {
        "search_skill",
        "list_dynamic_skills",
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
    playwright_direct_tool_schemas = [
        schema
        for schema in registry.get_all_schemas("openai")
        if schema.get("name") in playwright_direct_tool_names
    ]
    core_tool_schemas = (
        base_tool_schemas
        + playwright_direct_tool_schemas
        + skill_management_tool_schemas
        + discovery_tool_schemas
    )
    tools = client.format_openai_tools(core_tool_schemas)  # 固定核心工具 schema；动态能力推荐进入 Runtime Context。
    messages = client.create_initial_messages(
        registry,
        skill_runtime=skill_runtime,
        capability_router=capability_router,
        memory_runtime=memory_runtime,
    )
    command_registry = build_command_registry()
    if long_term_memory_runtime is not None:
        long_term_memory_runtime.schedule_startup_backfill()

    if WorkMode.parse(requested_work_mode) is WorkMode.CODE:
        print("[项目图谱] Code 模式初始化开始。", flush=True)
        try:
            status = await project_graph_runtime.activate(
                lambda message: print(f"[项目图谱] {message}", flush=True)
            )
            print(
                "[项目图谱] Code 模式已就绪："
                f"{status.get('modules', 0)} 个模块，{status.get('units', 0)} 个单位。",
                flush=True,
            )
            update = await project_graph_runtime.prepare_bootstrap(messages, force=True)
            if update is not None:
                messages.extend(update.messages)
                render_project_graph_bootstrap_tree(update.payload)
        except Exception as exc:
            if memory_runtime is not None:
                memory_runtime.set_work_mode(WorkMode.GENERAL.value)
            print(f"[项目图谱] 初始化失败：{type(exc).__name__}: {exc}", flush=True)

    terminal.mark_ready()
    terminal.bind_shift_tab_handler(
        lambda: _exit_plan_mode_from_terminal(plan_runtime)
    )

    mcp_user_rounds = 0

    automatic_prompt: str | None = None
    try:  # 开始可能抛出异常的保护代码块。
        while True:  # 在条件满足时持续循环。
            if memory_runtime is not None and automatic_prompt is None:
                rollover = await memory_runtime.await_pending_rollover()
                if rollover.performed and rollover.new_messages is not None:
                    messages = rollover.new_messages
            if automatic_prompt is not None:
                prompt = automatic_prompt
                automatic_prompt = None
                terminal.commit_runtime_user_message(prompt)
            else:
                try:  # 开始可能抛出异常的保护代码块。
                    prompt = await terminal.read_message(
                        command_registry,
                        prompt_header="User (输入 exit 退出对话)",
                    )  # 保存配置值或中间计算结果。
                except (EOFError, KeyboardInterrupt, TerminalCancelled):  # 捕获并处理指定异常。
                    # Ctrl+D 或 Ctrl+C 安全退出
                    print()  # 执行当前步骤的业务逻辑。
                    break  # 提前结束当前循环。
            if prompt.strip() == "exit":  # 根据条件决定是否执行后续分支。
                break  # 提前结束当前循环。
            if not prompt.strip():  # 根据条件决定是否执行后续分支。
                continue  # 空输入重新提示
            command_cancel = asyncio.Event()
            terminal.bind_cancel_event(command_cancel)
            try:
                command_result = await command_registry.execute(
                    prompt,
                    CommandContext(
                        memory_runtime=memory_runtime,
                        skill_runtime=skill_runtime,
                        messages=messages,
                        file_state_cache=file_state_cache,
                        workspace_tracker=workspace_tracker,
                        registry=registry,
                        model_manager=model_manager,
                        multi_agent_store=multi_agent_store,
                        long_term_memory_runtime=long_term_memory_runtime,
                        cancel_event=command_cancel,
                        work_mode=work_mode,
                        project_graph_runtime=project_graph_runtime,
                        plan_runtime=plan_runtime,
                        approval_runtime=approval_runtime,
                        network_access=network_access,
                        mcp_manager=mcp_manager,
                        terminal=terminal,
                    ),
                )
            finally:
                terminal.bind_cancel_event(None)
            if command_result.handled:
                if command_result.messages is not None:
                    messages = command_result.messages
                    if not messages:
                        messages = client.create_initial_messages(
                            registry,
                            skill_runtime=skill_runtime,
                            capability_router=capability_router,
                            memory_runtime=memory_runtime,
                        )
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
                    plan_runtime.restore_current_session()
                    if plan_runtime.proposed_plan() is not None:
                        messages = await client.resume_pending_plan_decision(
                            messages,
                            plan_runtime=plan_runtime,
                            project_graph=project_graph_runtime,
                            work_mode=work_mode.current.value,
                        )
                        if memory_runtime is not None:
                            session_id = memory_runtime.get_current_session_id()
                            if session_id:
                                memory_runtime.save_messages_now(session_id, messages)
                if command_result.should_exit:
                    break
                continue

            # 携带已初始化的系统消息和历史消息进行对话。
            try:  # 单轮对话内部的意外异常不应该终止整个 agent 进程；会话状态已在轮内持久化。
                turn_cancel = asyncio.Event()
                terminal.bind_cancel_event(turn_cancel)
                try:
                    _, messages = await client.ask_model(  # 保存配置值或中间计算结果。
                        model_manager,
                        prompt,
                        registry,
                        tools,
                        messages,
                        skill_runtime=skill_runtime,
                        core_tool_schemas=core_tool_schemas,
                        workspace_tracker=workspace_tracker,
                        memory_runtime=memory_runtime,
                        capability_router=capability_router,
                        project_graph=project_graph_runtime,
                        work_mode=work_mode.current.value,
                        long_term_memory_runtime=long_term_memory_runtime,
                        cancel_event=turn_cancel,
                        follow_up_event=terminal.follow_up_signal,
                        plan_runtime=plan_runtime,
                        network_access=network_access,
                    )  # 结束上方的多行结构。
                finally:
                    terminal.bind_cancel_event(None)
            except (EOFError, KeyboardInterrupt):  # 用户主动中断时保持原有退出语义。
                raise
            except Exception as exc:  # 其余异常打印后回到主循环，让用户可以继续对话或正常退出。
                print(f"\n本轮执行出错：{type(exc).__name__}: {exc}", flush=True)
                if CONFIG.client.debug:
                    import traceback

                    traceback.print_exc()
                continue
            pending_prompt = plan_runtime.take_pending_prompt()
            if pending_prompt is not None:
                automatic_prompt = pending_prompt
                continue
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
        session_id = ""
        if long_term_memory_runtime is not None and memory_runtime is not None:
            session_id = memory_runtime.get_current_session_id() or ""
            if session_id and messages:
                memory_runtime.save_messages_now(session_id, messages)
                long_term_memory_runtime.schedule_deferred_extraction(session_id)

        workspace_tracker.unsubscribe(project_graph_runtime.mark_dirty)
        workspace_tracker.close()  # 停止工作区文件监听线程。
        skill_runtime.close()  # 停止 SKILL 文件监听线程。
        if CONFIG.sandbox.workspace_lease_enabled:
            workspace_lease.release()
        workspace_runtime.detach()
        graph_task = project_graph_runtime.begin_shutdown()

        resources: list[tuple[str, Awaitable[Any]]] = []
        # MCP only depends on the proxy. All other local resources can close
        # concurrently with MCP, keeping exit latency bounded by the slowest
        # independent cleanup rather than the sum of their durations.
        resources.extend(
            [
                ("media_runtime", media_runtime.close()),
                ("web_fetch_runtime", web_fetch_runtime.close()),
                ("model_manager", model_manager.close()),
            ]
        )
        if long_term_memory_runtime is not None:
            resources.append(("long_term_memory", long_term_memory_runtime.close()))
        if memory_runtime is not None:
            resources.append(("memory_runtime", memory_runtime.close_for_exit()))
        if graph_task is not None:
            resources.append(("project_graph", graph_task))
        # Stop proxy traffic as soon as MCP is closed. Other resources keep
        # closing concurrently and do not delay either dependency edge.
        close_errors = await close_with_network_dependency(
            mcp_close=mcp_manager.close() if mcp_manager is not None else None,
            independent_resources=resources,
            network_resources=[("managed_network", managed_network.close_local())],
        )
        cleanup_started = spawn_runtime_cleanup(
            runtime_id=managed_network.runtime_id,
            network_name=managed_network.network_name,
            workspace_root=workspace_root,
        )
        if CONFIG.client.debug:
            for error in close_errors:
                print(f"退出清理提示：{error}", file=sys.stderr, flush=True)
            if not cleanup_started:
                print("退出清理提示：无法启动 Docker 后台清理进程。", file=sys.stderr, flush=True)
        print("\n会话已保存，后台资源正在清理。再见！")

if __name__ == "__main__":  # 根据条件决定是否执行后续分支。
    raise SystemExit(asyncio.run(main()))  # 执行当前步骤的业务逻辑。
