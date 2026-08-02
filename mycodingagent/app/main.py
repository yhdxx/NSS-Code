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
import json
import shutil
import sys  # 判断标准输入是否为交互式终端，决定是否启用高危命令审批。
from pathlib import Path

import pyfiglet  # 导入当前模块需要的依赖。

from openai import AsyncOpenAI  # 导入当前模块需要的依赖。

from mycodingagent.capability_discovery import CapabilityRouter
from mycodingagent.code_intelligence import ProjectGraphService, WorkspaceCodeIndex
from mycodingagent.terminal_ui.input import read_user_prompt
from mycodingagent.terminal_ui.interrupt import InterruptWatcher, TerminalInputCoordinator
from mycodingagent.commands import CommandContext
from mycodingagent.commands.handlers import build_command_registry
from mycodingagent.configuration.settings import CONFIG, _USER_CONFIG_PATH
from mycodingagent.long_term_memory.runtime import LongTermMemoryRuntime
from mycodingagent.memory import MemoryRuntime
from mycodingagent.skill_runtime import SkillRuntime  # 管理开发者提供的 SKILL，并按需动态暴露给模型。
from mycodingagent.tool_runtime import create_default_registry  # 导入当前模块需要的依赖。
from mycodingagent.tool_runtime.bash import ensure_docker_image, get_docker_image  # 启动时确保 Bash 工具使用的 Docker 镜像已在本地可用。
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
from mycodingagent.tool_runtime.mcp_discovery import register_mcp_discovery_tools
from mycodingagent.tool_runtime.mcp_execution import register_mcp_execution_tools
from mycodingagent.tool_runtime.workspace_change_tracker import WorkspaceChangeTracker  # 监听工作区文件变化并过滤模型自身写入。
from mycodingagent.workspace.lease import WorkspaceLease, WorkspaceLeaseError
from mycodingagent.mcp_integration import MCPClientManager, MCPConfigLoader
from mycodingagent.mcp_integration.cache import MCPMetadataCache
from mycodingagent.mcp_integration.hooks import CLIApprovalHook, CLILaunchApprovalHook, MCPToolApprovalHook
from mycodingagent.mcp_integration.policy import MCPToolPermissionPolicy
from mycodingagent.llm_runtime import client  # 导入当前模块需要的依赖。
from mycodingagent.multi_agent import MultiAgentStore

# 启用 readline 支持，增强命令行编辑功能（退格、方向键等自动生效）
try:  # 开始可能抛出异常的保护代码块。
    import readline  # noqa: F401
except ImportError:  # 捕获并处理指定异常。
    pass  # Windows 可能没有 readline，但不影响基本功能




_cached_config_import = False  # 模块级标记，避免重复导入


def _create_config_template() -> None:
    """创建 ~/.mycodingagent/config.json 全量配置模板。"""
    template = {
        "_说明": "myCodingAgent 全量配置文件。修改任意字段后保存，下次启动即生效。详细说明见 ~/.mycodingagent/README.md。",
        "api": {
            "deepseek_api_key": "",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-pro"
        },
        "client": {
            "max_tool_rounds": 50,
            "max_display_string_chars": 12000,
            "max_tool_output_chars": 20000,
            "api_max_retries": 3,
            "api_retry_base_delay": 1.0,
            "debug": False,
            "step_token": True,
            "round_token": True,
            "conversation_token": True,
            "legacy_system_prompt": False
        },
        "multi_agent": {
            "max_agent_rounds": 50,
            "max_parallel_tasks": 5
        },
        "long_term_memory": {
            "enabled": True,
            "storage_model": "",
            "query_model": "",
            "query_recent_turns": 10,
            "max_memories": 50,
            "max_workflow_candidates": 5,
            "max_skill_candidates": 3,
            "skill_candidate_success_threshold": 3,
            "skill_candidate_prompt_cooldown_days": 7,
            "extraction_claim_timeout_seconds": 600,
            "graceful_exit_extract_timeout_seconds": 30,
            "startup_backfill_enabled": True
        },
        "memory": {
            "enabled": True,
            "output_context_compression": True,
            "default_context_window": 128000,
            "session_ttl_days": 90,
            "default_work_mode": "general",
            "workspace_snapshot_ttl_days": 30,
            "tool_preview_chars": 2000,
            "context_preview_threshold_tokens": 12000,
            "context_preview_tokens": 2000,
            "raw_tool_output_preview_chars": 1000,
            "raw_to_virtualized_ratio": 0.60,
            "budget_soft_ratio": 0.60,
            "budget_working_ratio": 0.80,
            "budget_emergency_ratio": 0.90,
            "hot_context_warning_ratio": 0.30,
            "hot_context_force_ratio": 0.40,
            "hot_context_retained_turns": 3,
            "hot_context_topic_drift_turns": 3,
            "hot_context_topic_similarity_threshold": 0.12,
            "archive_cold_context_ratio": 0.50,
            "current_turn_summary_max_per_message": 2,
            "current_turn_summary_max_per_turn": 5,
            "checkpoint_enabled": True,
            "checkpoint_soft_ratio": 0.65,
            "checkpoint_hard_ratio": 0.85,
            "snapshot_version": "1.0",
            "checkpoint_min_turns_between_rollovers": 3,
            "checkpoint_recent_delta_turns": 20,
            "reserved_reasoning_tokens": 8000,
            "reserved_output_tokens": 4000,
            "reserved_tool_tokens": 12000,
            "context_store_backend": "sqlite",
            "recent_rounds_for_average": 20,
            "recent_messages_after_summary": 12,
            "model_context_windows": {"deepseek-v4-flash": 1000000}
        },
        "sandbox": {
            "max_output_chars": 10000,
            "workspace_lease_enabled": True
        },
        "docker": {
            "image": "mycodingagent-sandbox:py312",
            "network": "bridge",
            "build_network": "host",
            "cpus": "2",
            "memory": "1g",
            "pids_limit": "256",
            "default_timeout": 120,
            "max_timeout": 600,
            "check_timeout": 30,
            "pull_timeout": 300
        },
        "skills": {
            "small_count": 8,
            "default_tool_names": ["coding-standards"],
            "prefetch_top_k": 3,
            "search_top_k": 8,
            "min_score": 0.18,
            "watcher_poll_interval": 2.0,
            "router_top_n": 10,
            "router_retrieval_top_k": 40,
            "router_cache_top_k": 40,
            "router_retrieval_min_ratio": 0.4,
            "router_user_weight": 0.15,
            "router_session_weight": 0.45,
            "router_retrieval_weight": 0.40,
            "router_pinned_bonus": 1.0,
            "lrfu_decay": 0.95,
            "skill_call_reward": 10.0,
            "session_activation_reward": 0.3,
            "user_skill_cache_max_entries": 1000,
            "session_skill_cache_max_entries": 200,
            "output_recall_skill": True,
            "vector_sync_batch_size": 2,
            "vector_sync_max_retries": 3
        },
        "embedding": {
            "provider": "bge_http",
            "model": "bge-m3",
            "endpoint": "http://127.0.0.1:11434/api/embed",
            "api_format": "ollama",
            "api_key": "",
            "timeout": 30.0,
            "query_instruction": "为这个句子生成表示以用于检索相关文章：",
            "normalize": True,
            "device": "",
            "batch_size": 16,
            "dimension": 1024,
            "fallback_to_hash": False,
            "hash_dimension": 256,
            "request_extra": {},
            "headers": {}
        },
        "milvus": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": "19530",
            "collection": "mycodingagent_skills",
            "token": "",
            "recreate_incompatible": True,
            "consistency_level": "Strong",
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "sparse_metric_type": "BM25",
            "sparse_inverted_index_algo": "DAAT_MAXSCORE",
            "rrf_k": 60,
            "text_max_bytes": 65535,
            "analyzer_params": {"type": "chinese"}
        },
        "mcp": {
            "enabled": True,
            "reconnect_server_step": 10
        }
    }
    _USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _USER_CONFIG_PATH.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sync_config_readme() -> None:
    """将仓库内的配置教程文档复制到 ~/.mycodingagent/README.md。"""
    readme_dest = _USER_CONFIG_PATH.parent / "README.md"
    source = Path(__file__).resolve().parents[2] / "docs" / "configuration.md"
    if source.exists():
        try:
            shutil.copy2(source, readme_dest)
        except OSError:
            pass


def _diagnose_and_ensure_config() -> None:
    """诊断 ~/.mycodingagent/config.json 并确保其可用。"""
    _USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _sync_config_readme()

    deepseek_key = CONFIG.api.deepseek_api_key.strip()

    if deepseek_key:
        return

    # ── 密钥不可用，进入诊断 ──
    print("未检测到 API 密钥（deepseek_api_key）。", flush=True)

    config_exists = _USER_CONFIG_PATH.exists()

    if not config_exists:
        _create_config_template()
        print(
            f"\n已创建配置文件：{_USER_CONFIG_PATH}",
            flush=True,
        )
        print(
            f"已同步配置教程：{_USER_CONFIG_PATH.parent / 'README.md'}\n"
            "\n请编辑配置文件填入 deepseek_api_key 后重新启动：\n"
            f"    {_USER_CONFIG_PATH}\n"
            "\n或通过环境变量配置：\n"
            "    export DEEPSEEK_API_KEY=<你的密钥>\n"
            "\n详细配置说明请阅读 ~/.mycodingagent/README.md",
            flush=True,
        )
        return

    # 文件存在 → 校验
    try:
        raw = _USER_CONFIG_PATH.read_text(encoding="utf-8")
    except (PermissionError, OSError) as exc:
        print(f"无法读取配置文件：{exc}", flush=True)
        print(
            "请检查文件权限，或通过环境变量配置：\n"
            "    export DEEPSEEK_API_KEY=<你的密钥>",
            flush=True,
        )
        return

    if not raw.strip():
        print(
            "配置文件存在但内容为空。\n"
            f"请编辑 {_USER_CONFIG_PATH} 填入配置后重新启动。\n"
            "\n或通过环境变量配置：\n"
            "    export DEEPSEEK_API_KEY=<你的密钥>",
            flush=True,
        )
        return

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"配置文件不是合法 JSON（{exc}），将删除并重建。", flush=True)
        try:
            _USER_CONFIG_PATH.unlink()
        except OSError:
            pass
        _create_config_template()
        print(
            "已重建配置模板，请编辑后重新启动。\n"
            f"    {_USER_CONFIG_PATH}\n"
            "或通过环境变量：export DEEPSEEK_API_KEY=<你的密钥>",
            flush=True,
        )
        return

    if not isinstance(parsed, dict):
        print("配置文件不是 JSON 对象，将删除并重建。", flush=True)
        try:
            _USER_CONFIG_PATH.unlink()
        except OSError:
            pass
        _create_config_template()
        print(
            "已重建配置模板，请编辑后重新启动。\n"
            f"    {_USER_CONFIG_PATH}\n"
            "或通过环境变量：export DEEPSEEK_API_KEY=<你的密钥>",
            flush=True,
        )
        return

    # JSON 格式正确，但缺少密钥
    print(
        "配置文件格式正确，但未找到 deepseek_api_key。\n"
        f"请编辑 {_USER_CONFIG_PATH}，在 api.deepseek_api_key 中填入密钥后重新启动。\n"
        "\n或通过环境变量配置：\n"
        "    export DEEPSEEK_API_KEY=<你的密钥>\n"
        "\n详细配置说明请阅读 ~/.mycodingagent/README.md",
        flush=True,
    )


async def main() -> None:  # 定义异步函数，供事件循环调用。

    # ── 配置诊断（在打印 ASCII art 之前完成）──
    _diagnose_and_ensure_config()
    if not CONFIG.api.deepseek_api_key.strip():
        return  # 诊断已打印指引，直接退出

    ascii_art = pyfiglet.figlet_format("MyCodingAgent")  # 保存配置值或中间计算结果。
    print(ascii_art)  # 执行当前步骤的业务逻辑。

    docker_image = get_docker_image()  # 读取 Bash 工具后续执行命令时会使用的统一 Docker 镜像。
    print(f"检查 Bash Docker 镜像：{docker_image}", flush=True)  # 启动阶段明确告诉用户正在准备命令执行环境。
    image_result = await ensure_docker_image(docker_image)  # 如果镜像不存在，会在这里执行 docker pull。
    if image_result.is_error:  # Docker 不可用、权限不足或镜像拉取失败时，不继续进入对话。
        print(image_result.output)  # 打印具体错误，方便用户修复 Docker 环境或镜像配置。
        return  # Bash 环境无法准备时直接退出，避免后续模型调用命令全部失败。
    print(image_result.output, flush=True)  # 镜像已就绪时打印确认信息。

    workspace_lease = WorkspaceLease(get_sandbox_root(), CONFIG.memory.db_path.parent)
    if CONFIG.sandbox.workspace_lease_enabled:
        try:
            workspace_lease.acquire()
        except WorkspaceLeaseError as exc:
            print(f"无法启动：{exc}", flush=True)
            return
    file_state_cache = FileStateCache()  # 记录模型读过的文件，用于识别已读文件的外部变更。
    workspace_tracker = WorkspaceChangeTracker(get_sandbox_root(), file_state_cache)  # 监听工作区内已读文件的外部变更。
    workspace_tracker.start()  # 启动后台监听线程；不可用时静默降级为不提示。
    memory_runtime = MemoryRuntime(model=client.MODEL, workspace_root=str(get_sandbox_root())) if CONFIG.memory.enabled else None
    code_index = WorkspaceCodeIndex(
        get_sandbox_root(), CONFIG.memory.db_path.with_name("code_index.sqlite3")
    )
    workspace_tracker.subscribe(code_index.mark_dirty)
    project_graph = ProjectGraphService(
        get_sandbox_root(),
        CONFIG.memory.db_path.with_name("project_graph.sqlite3"),
        code_index,
    )
    project_graph.set_work_mode_provider(
        lambda: memory_runtime.work_mode if memory_runtime is not None else CONFIG.memory.default_work_mode
    )
    project_graph.set_progress_callback(
        lambda message: print(f"[项目图谱] {message}", flush=True)
    )
    workspace_tracker.subscribe(project_graph.mark_dirty)
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
    # 创建 OpenAI 客户端（复用连接）
    api_client = AsyncOpenAI(api_key=client.DEEPSEEK_API_KEY, base_url=client.BASE_URL)  # 保存配置值或中间计算结果。

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
                "type": "function",
                "name": schema["name"],
                "description": schema["description"],
                "parameters": schema["input_schema"],
            })
        response = await api_client.chat.completions.create(
            model=client.MODEL,
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
            temperature=0,
            tools=schemas,
            tool_choice="required",
        )
        tool_calls = response.choices[0].message.tool_calls if response.choices else []
        if not tool_calls:
            return "approval"
        return {
            "SubmitBashLowRisk": "low",
            "SubmitBashApproval": "approval",
            "SubmitBashHighRisk": "high",
        }.get(tool_calls[0].function.name, "approval")
    # 对话历史记录，跨轮次保持记忆
    messages: list[dict] = []  # 保存配置值或中间计算结果。
    terminal_input = TerminalInputCoordinator()
    command_approval_hook = CLICommandApprovalHook(terminal_input) if sys.stdin.isatty() else None
    registry = create_default_registry(  # 保存配置值或中间计算结果。
        file_state_cache=file_state_cache,
        workspace_tracker=workspace_tracker,
        memory_runtime=memory_runtime,
        command_approval_hook=command_approval_hook,
        write_approval_hook=None,
        terminal_input_coordinator=terminal_input,
        project_graph_service=project_graph,
        bash_policy_evaluator=BashPolicyEvaluator(
            BashPolicyStore(CONFIG.memory.db_path),
            classify_bash_policy,
        ),
    )
    multi_agent_store = MultiAgentStore()
    long_term_memory_runtime = None
    if memory_runtime is not None and CONFIG.long_term_memory.enabled:
        long_term_memory_runtime = LongTermMemoryRuntime(
            memory_runtime=memory_runtime,
            registry=registry,
            api_client=api_client,
            user_id=CONFIG.skills.user_id,
            storage_model=CONFIG.long_term_memory.storage_model or client.MODEL,
            query_model=CONFIG.long_term_memory.query_model or "deepseek-v4-flash",
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
            ),
            metadata_cache=MCPMetadataCache(CONFIG.memory.db_path.with_name("mcp_cache.sqlite3")),
            launch_hook=CLILaunchApprovalHook(terminal_input) if sys.stdin.isatty() else None,
        )
        try:
            await mcp_manager.initialize()
        except ValueError as exc:
            print(f"MCP 配置错误：{exc}", flush=True)
        capability_router = CapabilityRouter(skill_runtime=skill_runtime, mcp_manager=mcp_manager)
        register_mcp_discovery_tools(registry, manager=mcp_manager, router=capability_router)
        register_mcp_execution_tools(
            registry,
            manager=mcp_manager,
            policy=MCPToolPermissionPolicy(),
            approval_hook=CLIApprovalHook(terminal_input) if sys.stdin.isatty() else MCPToolApprovalHook(),
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

    try:  # 开始可能抛出异常的保护代码块。
        while True:  # 在条件满足时持续循环。
            if memory_runtime is not None:
                rollover = await memory_runtime.await_pending_rollover()
                if rollover.performed and rollover.new_messages is not None:
                    messages = rollover.new_messages
            try:  # 开始可能抛出异常的保护代码块。
                print("----------------------------------------------\n\n")  # 执行当前步骤的业务逻辑。
                prompt = read_user_prompt(
                    "",
                    command_registry,
                    prompt_header="\033[1;97m ⌨️  User(输入exit退出对话)：\033[0m",
                )  # 保存配置值或中间计算结果。
                print("----------------------------------------------\n\n")  # 执行当前步骤的业务逻辑。
            except (EOFError, KeyboardInterrupt):  # 捕获并处理指定异常。
                # Ctrl+D 或 Ctrl+C 安全退出
                print()  # 执行当前步骤的业务逻辑。
                break  # 提前结束当前循环。
            if prompt.strip() == "exit":  # 根据条件决定是否执行后续分支。
                break  # 提前结束当前循环。
            if not prompt.strip():  # 根据条件决定是否执行后续分支。
                continue  # 空输入重新提示
            async with InterruptWatcher(terminal_input) as command_watcher:
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
                        cancel_event=command_watcher.triggered,
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
            try:  # 单轮对话内部的意外异常不应该终止整个 agent 进程；会话状态已在轮内持久化。
                async with InterruptWatcher(terminal_input) as turn_watcher:
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
                        project_graph=project_graph,
                        work_mode=memory_runtime.work_mode if memory_runtime is not None else CONFIG.memory.default_work_mode,
                        long_term_memory_runtime=long_term_memory_runtime,
                        cancel_event=turn_watcher.triggered,
                    )  # 结束上方的多行结构。
            except (EOFError, KeyboardInterrupt):  # 用户主动中断时保持原有退出语义。
                raise
            except Exception as exc:  # 其余异常打印后回到主循环，让用户可以继续对话或正常退出。
                print(f"\n本轮执行出错：{type(exc).__name__}: {exc}", flush=True)
                if CONFIG.client.debug:
                    import traceback

                    traceback.print_exc()
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
        if long_term_memory_runtime is not None and memory_runtime is not None:
            session_id = memory_runtime.get_current_session_id()
            if session_id and messages:
                memory_runtime.save_messages_now(session_id, messages)
                await memory_runtime.drain()
                long_term_memory_runtime.schedule_deferred_extraction(session_id)
            await long_term_memory_runtime.close()
        if memory_runtime is not None:
            await memory_runtime.close()
        if mcp_manager is not None:
            await mcp_manager.close()
        skill_runtime.close()  # 停止 SKILL 文件监听线程。
        workspace_tracker.unsubscribe(code_index.mark_dirty)
        workspace_tracker.unsubscribe(project_graph.mark_dirty)
        workspace_tracker.close()  # 停止工作区文件监听线程。
        if CONFIG.sandbox.workspace_lease_enabled:
            workspace_lease.release()
        # 退出时关闭连接
        await api_client.close()  # 执行当前步骤的业务逻辑。
        print("\n连接已关闭，再见！")  # 执行当前步骤的业务逻辑。

if __name__ == "__main__":  # 根据条件决定是否执行后续分支。
    asyncio.run(main())  # 执行当前步骤的业务逻辑。
