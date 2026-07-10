# myCodingAgent 函数级项目框架图

> 本文档由当前源码 AST 生成。每次代码修改后必须同步更新，确保项目、模块、类、函数和依赖关系可审计。

## 1. 项目总览

- 项目：`myCodingAgent`
- 运行时代码：`mycodingagent/`
- 插件资产：`skills/`，仅保存独立 Skill 定义、脚本和资源。
- 启动入口：根目录 `__main__.py` -> `mycodingagent.app.main.main()`。
- 架构原则：应用层负责组装；业务模块依赖 Protocol；基础设施适配器依赖具体 SDK、数据库和工具框架。
- 上下文模型：冷历史虚拟化 + 跨多轮热工作阶段；模型或 Runtime 在安全回合边界提交阶段。
- 多智能体模式：`direct`、`audit_only`、`implementation` 三条明确工作流。

## 2. 顶层目录

```text
mycodingagent/
├── app/  # 应用启动、依赖组装、资源生命周期和交互主循环。
├── capability_discovery/  # Skill 与 MCP 能力推荐，依赖抽象能力源。
├── commands/  # CLI 命令注册、解析和命令处理。
├── configuration/  # 环境变量解析与不可变应用配置。
├── llm_runtime/  # 模型请求、流式响应、工具循环、Prompt 上下文和 Token 统计。
├── mcp_integration/  # MCP 配置、连接、元数据发现、调用和审批策略。
├── memory/  # 会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
├── multi_agent/  # 多智能体领域模型、角色、编排状态机和基础设施适配器。
├── relevance/  # 跨模块复用的相关性和使用频率排序算法。
├── skill_runtime/  # Skill 发现、索引、检索、路由、缓存与运行时生命周期。
├── terminal_ui/  # 终端输入、历史展示、会话选择与确认交互。
├── tool_runtime/  # 工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
├── workspace/  # 工作区身份、文件缓存和工作区状态。
skills/                 # 独立 Skill 插件资产，不属于核心运行时包
tests/                  # 单元、集成和架构边界测试
```

## 3. 跨模块依赖图

```text
app -> capability_discovery, commands, configuration, llm_runtime, mcp_integration, memory, multi_agent, skill_runtime, terminal_ui, tool_runtime, workspace
capability_discovery -> relevance
commands -> configuration, llm_runtime, memory, terminal_ui
llm_runtime -> configuration, memory, tool_runtime
memory -> configuration, workspace
multi_agent -> llm_runtime, tool_runtime
skill_runtime -> configuration, relevance, tool_runtime
terminal_ui -> commands, memory
tool_runtime -> capability_discovery, configuration, mcp_integration, memory, skill_runtime, workspace
```

- 架构测试要求核心运行时依赖图无循环。
- `app` 是组合根，负责实例化并连接具体实现。
- `memory/context_epoch.py` 依赖 `ContextEpochStore` Protocol，不依赖 SQLite 实现。
- `tool_runtime/CommitWorkingContext` 依赖 `ContextEpochControl` Protocol，不依赖 `MemoryRuntime` 实现。
- `multi_agent/orchestration` 不直接导入 LLM 或 Tool 具体实现。

## 4. 核心运行流程

### 4.1 跨多轮上下文

```text
用户 query1 -> 建立 ContextEpoch -> 文件/工具结果保持 RAW
相关 query2/query3 -> 复用同一热工作阶段和稳定 Prompt 前缀
  ├── 热区 >= 30% -> HOT WORKING CONTEXT NOTICE
  ├── 模型调用 CommitWorkingContext -> pending_commit
  └── 热区 >= 40% -> Runtime 自动 pending_commit
完整回合结束 -> 提交旧阶段 -> 创建新阶段 -> 旧工具输出 metadata 虚拟化
需要精确信息 -> SearchRecoverableContext / RecoverContext
```

### 4.2 多智能体

```text
用户输入 -> Router
  ├── direct -> DirectResponder -> 主 Agent 回答
  ├── audit_only -> Planner -> Auditor workers -> merge -> Optimizer proposal -> 总结
  └── implementation -> Audit -> Optimize/Approve -> Plan -> Executors -> Validator -> Repair -> 总结
所有路径 -> JsonRunJournal -> get_multicoding_run 可查询
```

## 5. 函数级模块索引

### `mycodingagent/__init__.py`

- 模块：`mycodingagent`
- 职责：myCodingAgent core runtime package.
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/app/__init__.py`

- 模块：`mycodingagent.app`
- 职责：Application bootstrap and lifecycle.
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/app/main.py`

- 模块：`mycodingagent.app.main`
- 职责：应用启动、依赖组装、资源生命周期和交互主循环。
- 内部依赖：`mycodingagent.capability_discovery`, `mycodingagent.commands`, `mycodingagent.commands.handlers`, `mycodingagent.configuration`, `mycodingagent.llm_runtime`, `mycodingagent.mcp_integration`, `mycodingagent.mcp_integration.hooks`, `mycodingagent.mcp_integration.policy`, `mycodingagent.memory`, `mycodingagent.multi_agent`, `mycodingagent.multi_agent.infrastructure.direct_responder`, `mycodingagent.multi_agent.infrastructure.history_tool`, `mycodingagent.multi_agent.infrastructure.run_journal`, `mycodingagent.multi_agent.infrastructure.runner`, `mycodingagent.skill_runtime`, `mycodingagent.terminal_ui.input`, `mycodingagent.tool_runtime`, `mycodingagent.tool_runtime.base`, `mycodingagent.tool_runtime.bash`, `mycodingagent.tool_runtime.file_state_cache`, `mycodingagent.tool_runtime.mcp_discovery`, `mycodingagent.tool_runtime.mcp_execution`, `mycodingagent.tool_runtime.workspace_change_tracker`, `mycodingagent.workspace.identity`
- 函数 `async main() -> None`（L56）：执行模块级业务逻辑。；调用：`AgentRunner`, `AsyncOpenAI`, `CLIApprovalHook`, `CLIArchitectureApprovalHook`, `CLIRuntimeEventHook`, `CapabilityRouter`, `CommandContext`, `FileStateCache`, `GetMultiAgentRun`, `JsonRunJournal`, `LLMDirectResponder`, `MCPClientManager`, `MCPConfigLoader`, `MCPToolPermissionPolicy`, `MemoryRuntime`, `MultiCodingController`, `MultiCodingOrchestrator`, `SkillRuntime`, `WorkspaceChangeTracker`, `api_client.close`, `build_command_registry`, `client.ask_deepseek`, `client.format_openai_tools`, `command_registry.execute`, `create_default_registry`, `ensure_docker_image`, `get_docker_image`, `get_sandbox_root`, `mcp_manager.close`, `mcp_manager.initialize`, `mcp_manager.schedule_reconnect_unavailable_servers`, `mcp_manager.server_count`, `memory_runtime.await_pending_rollover`, `memory_runtime.cleanup_expired_sessions`, `memory_runtime.close`, `memory_runtime.on_turn_completed`, `multicoding_controller.run`, `print`, `prompt.strip`, `pyfiglet.figlet_format`, `read_user_prompt`, `register_mcp_discovery_tools`, `register_mcp_execution_tools`, `registry.get_all_schemas`, `registry.register`, `schema.get`, `skill_report.summary`, `skill_runtime.close`, `skill_runtime.initialize`, `str`, `workspace_fingerprint`, `workspace_tracker.close`, `workspace_tracker.start`

### `mycodingagent/capability_discovery/__init__.py`

- 模块：`mycodingagent.capability_discovery`
- 职责：Skill 与 MCP 能力推荐，依赖抽象能力源。
- 内部依赖：`mycodingagent.capability_discovery.router`
- 定义：无公开类或函数。

### `mycodingagent/capability_discovery/contracts.py`

- 模块：`mycodingagent.capability_discovery.contracts`
- 职责：Skill 与 MCP 能力推荐，依赖抽象能力源。
- 内部依赖：无
- 类 `class MCPServerView(Protocol)`（L6）：封装该模块的状态与行为。
- 类 `class SkillCapabilitySource(Protocol)`（L20）：封装该模块的状态与行为。
  - `async build_tools_for_prompt_async(self, prompt: str, core_tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]`（L24）；调用：无
  - `search_records_for_capability(self, query: str, *, top_k: int) -> list[Any]`（L30）；调用：无
- 类 `class MCPServerSource(Protocol)`（L33）：封装该模块的状态与行为。
  - `server_count(self) -> int`（L34）；调用：无
  - `available_count(self) -> int`（L36）；调用：无
  - `list_servers(self) -> list[MCPServerView]`（L38）；调用：无

### `mycodingagent/capability_discovery/models.py`

- 模块：`mycodingagent.capability_discovery.models`
- 职责：Skill 与 MCP 能力推荐，依赖抽象能力源。
- 内部依赖：无
- 类 `class CapabilityRecommendation`（L11）：封装该模块的状态与行为。
  - `to_payload(self) -> dict[str, Any]`（L19）；调用：`asdict`, `round`
- 类 `class CapabilityResult`（L26）：封装该模块的状态与行为。
  - `to_runtime_payload(self) -> dict[str, Any]`（L36）；调用：`item.to_payload`

### `mycodingagent/capability_discovery/retrieval.py`

- 模块：`mycodingagent.capability_discovery.retrieval`
- 职责：Skill 与 MCP 能力推荐，依赖抽象能力源。
- 内部依赖：`mycodingagent.capability_discovery.contracts`
- 类 `class ServerRetrievalScore`（L12）：封装该模块的状态与行为。
- 类 `class LexicalServerSignal`（L18）：封装该模块的状态与行为。
  - `score(self, query: str, servers: list[MCPServerView]) -> list[ServerRetrievalScore]`（L19）；调用：`ServerRetrievalScore`, `_tokens`, `_weighted_terms`, `join`, `len`, `max`, `min`, `query.lower`, `query_tokens.intersection`, `reasons.append`, `results.append`, `results.sort`, `sorted`, `term.lower`, `tuple`
- 函数 `_tokens(text: str) -> set[str]`（L45）：执行模块级业务逻辑。；调用：`TOKEN_RE.findall`, `item.lower`
- 函数 `_weighted_terms(server: MCPServerView) -> list[tuple[str, float]]`（L49）：执行模块级业务逻辑。；调用：`terms.extend`

### `mycodingagent/capability_discovery/router.py`

- 模块：`mycodingagent.capability_discovery.router`
- 职责：Skill 与 MCP 能力推荐，依赖抽象能力源。
- 内部依赖：`mycodingagent.capability_discovery.contracts`, `mycodingagent.capability_discovery.models`, `mycodingagent.capability_discovery.retrieval`, `mycodingagent.relevance.lrfu`
- 类 `class CapabilityRouterConfig`（L13）：封装该模块的状态与行为。
- 类 `class CapabilityRouter`（L21）：封装该模块的状态与行为。
  - `__init__(self, *, skill_runtime: SkillCapabilitySource | None = None, mcp_manager: MCPServerSource | None = None, config: CapabilityRouterConfig | None = None) -> None`（L22）；调用：`CapabilityRouterConfig`, `LRFUCache`, `LexicalServerSignal`
  - `async route(self, prompt: str) -> CapabilityResult`（L36）；调用：`CapabilityResult`, `recommendations.extend`, `recommendations.sort`, `self._mcp_recommendations`, `self._skill_recommendations`, `self.mcp_manager.available_count`, `self.mcp_manager.server_count`, `tuple`
  - `record_mcp_server_use(self, server: str, *, reward: float = 1.0) -> None`（L55）；调用：`self._server_lrfu.touch`
  - `async build_tools_for_prompt(self, prompt: str, core_tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]`（L59）；调用：`self.skill_runtime.build_tools_for_prompt_async`
  - `async _skill_recommendations(self, prompt: str) -> list[CapabilityRecommendation]`（L68）；调用：`CapabilityRecommendation`, `float`, `min`, `recommendations.append`, `runtime.search_records_for_capability`, `str`
  - `_mcp_recommendations(self, prompt: str) -> list[CapabilityRecommendation]`（L94）；调用：`CapabilityRecommendation`, `by_name.get`, `by_name.values`, `max`, `self._lexical_signal.score`, `self._server_lrfu.top_candidates`, `self.mcp_manager.list_servers`, `server_by_name.get`, `sorted`

### `mycodingagent/commands/__init__.py`

- 模块：`mycodingagent.commands`
- 职责：CLI 命令注册、解析和命令处理。
- 内部依赖：`mycodingagent.commands.registry`
- 定义：无公开类或函数。

### `mycodingagent/commands/handlers.py`

- 模块：`mycodingagent.commands.handlers`
- 职责：CLI 命令注册、解析和命令处理。
- 内部依赖：`mycodingagent.commands.registry`, `mycodingagent.configuration`, `mycodingagent.llm_runtime`, `mycodingagent.memory.session_switch`, `mycodingagent.terminal_ui.confirm`, `mycodingagent.terminal_ui.history`, `mycodingagent.terminal_ui.session_selector`
- 函数 `build_command_registry() -> CommandRegistry`（L16）：执行模块级业务逻辑。；调用：`CommandRegistry`, `CommandSpec`, `registry.register`
- 函数 `async handle_multicoding_command(context: CommandContext, arguments: str) -> CommandResult`（L129）：执行模块级业务逻辑。；调用：`CommandResult`, `arguments.strip`, `build_command_registry`, `controller.disable`, `controller.enable`, `controller.status_text`, `lower`, `match`, `print`, `spec.help_text`
- 函数 `async handle_resume_command(context: CommandContext, arguments: str) -> CommandResult`（L158）：执行模块级业务逻辑。；调用：`CommandResult`, `arguments.strip`, `build_command_registry`, `confirm_cross_workspace_restore`, `has_conversation_content`, `len`, `match`, `memory_runtime.cleanup_expired_sessions`, `memory_runtime.drain`, `memory_runtime.load_file_state_snapshot`, `memory_runtime.load_lrfu_snapshot`, `memory_runtime.load_session`, `memory_runtime.touch_session`, `print`, `render_conversation_history`, `resume_spec.help_text`, `save_current_session_if_needed`, `select_session_interactively`
- 函数 `async handle_fork_command(context: CommandContext, arguments: str) -> CommandResult`（L207）：执行模块级业务逻辑。；调用：`CommandResult`, `arguments.strip`, `build_command_registry`, `confirm_cross_workspace_action`, `fork_spec.help_text`, `has_conversation_content`, `len`, `match`, `memory_runtime.cleanup_expired_sessions`, `memory_runtime.drain`, `memory_runtime.fork_session`, `memory_runtime.load_file_state_snapshot`, `memory_runtime.load_lrfu_snapshot`, `memory_runtime.store.load_session`, `print`, `render_conversation_history`, `save_current_session_if_needed`, `select_session_interactively`
- 函数 `async handle_clear_command(context: CommandContext, arguments: str) -> CommandResult`（L273）：执行模块级业务逻辑。；调用：`CommandResult`, `arguments.strip`, `build_command_registry`, `clear_spec.help_text`, `match`, `memory_runtime.clear_current_session_id`, `memory_runtime.drain`, `memory_runtime.start_session`, `print`, `save_current_session_if_needed`
- 函数 `async handle_delete_command(context: CommandContext, arguments: str) -> CommandResult`（L308）：执行模块级业务逻辑。；调用：`CommandResult`, `arguments.strip`, `build_command_registry`, `confirm_cross_workspace_action`, `confirm_delete_sessions`, `delete_spec.help_text`, `match`, `memory_runtime.cleanup_expired_sessions`, `memory_runtime.delete_session`, `memory_runtime.delete_sessions`, `memory_runtime.drain`, `memory_runtime.list_sessions`, `memory_runtime.store.load_session`, `print`, `save_current_session_if_needed`, `select_session_interactively`

### `mycodingagent/commands/registry.py`

- 模块：`mycodingagent.commands.registry`
- 职责：CLI 命令注册、解析和命令处理。
- 内部依赖：无
- 类 `class CommandContext`（L8）：封装该模块的状态与行为。
- 类 `class CommandResult`（L18）：封装该模块的状态与行为。
- 类 `class CommandSpec`（L28）：封装该模块的状态与行为。
  - `names(self) -> tuple[str, ...]`（L37）；调用：无
  - `help_text(self) -> str`（L40）；调用：`join`, `lines.append`, `lines.extend`
- 类 `class CommandRegistry`（L55）：封装该模块的状态与行为。
  - `__init__(self) -> None`（L56）；调用：无
  - `register(self, spec: CommandSpec) -> None`（L59）；调用：无
  - `suggestions(self, buffer: str) -> list[CommandSpec]`（L62）；调用：`any`, `char.isspace`, `list`, `self._commands.values`, `spec.name.startswith`, `text.startswith`
  - `exact_command(self, buffer: str) -> CommandSpec | None`（L70）；调用：`buffer.strip`, `self._commands.get`, `text.split`, `text.startswith`
  - `match(self, text: str) -> tuple[CommandSpec, str] | None`（L77）；调用：`len`, `self._commands.values`, `spec.names`, `strip`, `stripped.startswith`, `text.strip`
  - `async execute(self, text: str, context: CommandContext) -> CommandResult`（L87）；调用：`CommandResult`, `self.match`, `spec.handler`

### `mycodingagent/configuration/__init__.py`

- 模块：`mycodingagent.configuration`
- 职责：Environment-backed application settings.
- 内部依赖：`mycodingagent.configuration.settings`
- 定义：无公开类或函数。

### `mycodingagent/configuration/settings.py`

- 模块：`mycodingagent.configuration.settings`
- 职责：环境变量解析与不可变应用配置。
- 内部依赖：无
- 函数 `_env_int(name: str, default: int) -> int`（L9）：执行模块级业务逻辑。；调用：`int`, `os.getenv`
- 函数 `_env_float(name: str, default: float) -> float`（L19）：执行模块级业务逻辑。；调用：`float`, `os.getenv`
- 函数 `_env_bool(name: str, default: bool) -> bool`（L29）：执行模块级业务逻辑。；调用：`lower`, `os.getenv`, `raw_value.strip`
- 函数 `_env_path(name: str, default: Path | None = None) -> Path | None`（L36）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `os.getenv`
- 函数 `_env_paths(name: str) -> tuple[Path, ...]`（L43）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `item.strip`, `os.getenv`, `raw_value.split`, `tuple`
- 函数 `_env_list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]`（L50）：执行模块级业务逻辑。；调用：`item.strip`, `os.getenv`, `raw_value.split`, `tuple`
- 函数 `_default_user_id() -> str`（L57）：执行模块级业务逻辑。；调用：`os.getenv`
- 函数 `_env_json_dict(name: str, default: dict) -> dict`（L66）：执行模块级业务逻辑。；调用：`isinstance`, `json.loads`, `os.getenv`
- 函数 `_default_builtin_skills_root() -> Path`（L77）：执行模块级业务逻辑。；调用：`Path`, `resolve`
- 函数 `_default_workspace_skills_root() -> Path`（L81）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `os.getcwd`, `os.getenv`
- 函数 `_default_memory_db_path() -> Path`（L91）：执行模块级业务逻辑。；调用：`Path`, `Path.home`, `expanduser`, `os.getenv`
- 函数 `_default_mcp_user_config_path() -> Path`（L101）：执行模块级业务逻辑。；调用：`Path.home`
- 函数 `_default_mcp_project_config_path() -> Path`（L105）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `os.getcwd`, `os.getenv`
- 函数 `_dedupe_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]`（L109）：执行模块级业务逻辑。；调用：`path.expanduser`, `resolve`, `result.append`, `seen.add`, `set`, `str`, `tuple`
- 类 `class ApiConfig`（L122）：封装该模块的状态与行为。
- 类 `class ClientConfig`（L131）：封装该模块的状态与行为。
- 类 `class MultiCodingConfig`（L145）：封装该模块的状态与行为。
- 类 `class MemoryConfig`（L167）：封装该模块的状态与行为。
  - `context_window_for(self, model: str) -> int`（L221）；调用：`isinstance`, `self.model_context_windows.get`
- 类 `class SandboxConfig`（L229）：封装该模块的状态与行为。
- 类 `class DockerConfig`（L251）：封装该模块的状态与行为。
- 类 `class SkillConfig`（L272）：封装该模块的状态与行为。
  - `root(self) -> Path`（L336）；调用：无
  - `roots(self) -> tuple[Path, ...]`（L340）；调用：`_dedupe_paths`
- 类 `class EmbeddingConfig`（L345）：封装该模块的状态与行为。
- 类 `class MilvusConfig`（L363）：封装该模块的状态与行为。
  - `uri(self) -> str`（L393）；调用：`os.getenv`
- 类 `class MCPConfig`（L398）：封装该模块的状态与行为。
- 类 `class AppConfig`（L421）：封装该模块的状态与行为。

### `mycodingagent/llm_runtime/__init__.py`

- 模块：`mycodingagent.llm_runtime`
- 职责：Model gateway, streaming, prompt context, and agent loop.
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/llm_runtime/client.py`

- 模块：`mycodingagent.llm_runtime.client`
- 职责：模型请求、流式响应、工具循环、Prompt 上下文和 Token 统计。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.llm_runtime.context`, `mycodingagent.memory`, `mycodingagent.memory.budget`, `mycodingagent.memory.message_filters`, `mycodingagent.tool_runtime`
- 类 `class PendingToolCall`（L44）：封装该模块的状态与行为。
- 类 `class PromptDebugSnapshot`（L51）：封装该模块的状态与行为。
- 函数 `stable_json_hash(value: Any) -> str`（L77）：执行模块级业务逻辑。；调用：`hashlib.sha256`, `hexdigest`, `json.dumps`, `payload.encode`
- 函数 `estimated_json_tokens(value: Any) -> int`（L82）：执行模块级业务逻辑。；调用：`estimate_tokens`, `json.dumps`
- 函数 `api_usage_to_dict(usage: Any) -> dict[str, int]`（L86）：执行模块级业务逻辑。；调用：`getattr`, `int`
- 函数 `add_usage_to_summary(summary: TokenUsageSummary, values: dict[str, int]) -> None`（L103）：执行模块级业务逻辑。；调用：`TokenUsageRecord`, `summary.add`
- 函数 `format_token_summary(label: str, summary: TokenUsageSummary) -> str`（L118）：执行模块级业务逻辑。；调用：无
- 函数 `split_prompt_debug_sections(model_messages: list[dict[str, Any]], temporary_system_messages: list[dict[str, Any]], tools: list[dict[str, Any]], current_turn_start: int | None = None) -> dict[str, Any]`（L126）：执行模块级业务逻辑。；调用：`get`, `len`, `max`, `min`, `range`
- 函数 `build_prompt_debug_snapshot(*, model_messages: list[dict[str, Any]], temporary_system_messages: list[dict[str, Any]], tools: list[dict[str, Any]], current_turn_start: int | None = None, rendered_prompt: RenderedPrompt | None = None) -> PromptDebugSnapshot`（L153）：执行模块级业务逻辑。；调用：`PromptDebugSnapshot`, `estimated_json_tokens`, `len`, `split_prompt_debug_sections`, `stable_json_hash`
- 函数 `first_changed_prompt_debug_section(previous: PromptDebugSnapshot | None, current: PromptDebugSnapshot) -> str`（L203）：执行模块级业务逻辑。；调用：无
- 函数 `print_prompt_debug(*, snapshot: PromptDebugSnapshot, first_changed_section: str) -> None`（L223）：执行模块级业务逻辑。；调用：`print_token_block`
- 函数 `print_prompt_debug_with_previous(snapshot: PromptDebugSnapshot) -> None`（L246）：执行模块级业务逻辑。；调用：`first_changed_prompt_debug_section`, `print_prompt_debug`
- 函数 `print_token_block(*lines: str) -> None`（L253）：执行模块级业务逻辑。；调用：`print`
- 函数 `context_budget_state_from_snapshot(snapshot: Any) -> ContextBudgetState`（L260）：执行模块级业务逻辑。；调用：`ContextBudgetState`, `float`, `getattr`, `str`
- 函数 `format_openai_tools(raw_tools: list[dict[str, Any]]) -> list[dict[str, Any]]`（L269）：执行模块级业务逻辑。；调用：`tool.get`, `tools.append`
- 函数 `pretty_arguments(raw_args: str) -> str`（L291）：执行模块级业务逻辑。；调用：`format_argument_mapping`, `isinstance`, `json.dumps`, `json.loads`, `raw_args.strip`
- 函数 `format_argument_mapping(arguments: dict[str, Any]) -> str`（L304）：执行模块级业务逻辑。；调用：`arguments.items`, `indent_multiline_text`, `join`, `json.dumps`, `lines.append`, `should_render_multiline`, `truncate_display_string`
- 函数 `should_render_multiline(key: str, value: Any) -> bool`（L320）：执行模块级业务逻辑。；调用：`isinstance`, `len`
- 函数 `truncate_display_string(value: str) -> str`（L331）：执行模块级业务逻辑。；调用：`len`
- 函数 `indent_multiline_text(value: str, prefix: str = '    ') -> str`（L338）：执行模块级业务逻辑。；调用：`join`, `lines.append`, `value.endswith`, `value.splitlines`
- 函数 `skill_tool_notice(tool_name: str, args: dict[str, Any], skill_runtime: Any | None = None) -> str`（L347）：执行模块级业务逻辑。；调用：`args.get`, `compact_notice_value`, `get_skill_record_for_notice`, `join`, `lines.append`, `tool_name.startswith`
- 函数 `get_skill_record_for_notice(skill_runtime: Any | None, tool_name: str) -> Any | None`（L384）：执行模块级业务逻辑。；调用：`callable`, `get_record`, `getattr`
- 函数 `compact_notice_value(value: Any, limit: int = 120) -> str`（L396）：执行模块级业务逻辑。；调用：`isinstance`, `join`, `json.dumps`, `len`, `value.split`
- 函数 `parse_tool_arguments(raw_args: str) -> dict[str, Any]`（L408）：执行模块级业务逻辑。；调用：`isinstance`, `json.loads`
- 函数 `compact_tool_metadata_value(value: Any, limit: int = 160) -> str`（L416）：执行模块级业务逻辑。；调用：`isinstance`, `join`, `json.dumps`, `len`, `split`, `str`
- 函数 `tool_call_metadata(tool_name: str, raw_args: str, output: str) -> dict[str, Any]`（L423）：执行模块级业务逻辑。；调用：`args.get`, `compact_tool_metadata_value`, `isinstance`, `json.loads`, `metadata.setdefault`, `output.lstrip`, `parse_tool_arguments`, `payload.get`, `startswith`
- 函数 `async execute_local_tool(registry: ToolRegistry, tool_name: str, raw_args: str, skill_runtime: Any | None = None) -> str`（L458）：执行模块级业务逻辑。；调用：`isinstance`, `json.loads`, `print`, `registry.get`, `skill_tool_notice`, `tool.execute`, `tool.params_model.model_validate`
- 函数 `async stream_one_round(client: AsyncOpenAI, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, display: bool = True, output_label: str = '模型') -> tuple[str, list[PendingToolCall], Any]`（L487）：执行模块级业务逻辑。；调用：`PendingToolCall`, `client.chat.completions.create`, `content_parts.append`, `getattr`, `hasattr`, `join`, `pending_tool_calls.setdefault`, `pretty_arguments`, `print`, `sorted`
- 函数 `async ask_deepseek(client: AsyncOpenAI, prompt: str, registry: ToolRegistry, tools: list[dict[str, Any]], messages: list[dict[str, Any]] | None = None, skill_runtime: Any | None = None, core_tool_schemas: list[dict[str, Any]] | None = None, workspace_tracker: Any | None = None, memory_runtime: MemoryRuntime | None = None, capability_router: Any | None = None) -> tuple[str, list[dict[str, Any]]]`（L569）：执行模块级业务逻辑。；调用：`PromptRenderer.render_current_user_message`, `RuntimeContextBuilder`, `TokenUsageSummary`, `add_usage_to_summary`, `api_usage_to_dict`, `assistant_text.startswith`, `begin_turn`, `build`, `build_prompt_debug_snapshot`, `build_round_tools`, `callable`, `capability_router.route`, `context_budget_state_from_snapshot`, `end_skill_turn`, `end_turn`, `enumerate`, `execute_local_tool`, `format_token_summary`, `getattr`, `is_skill_related_tool`, `join`, `len`, `lines.append`, `list`, `memory_runtime.load_token_usage_summary`, `memory_runtime.prepare_messages_for_model`, `memory_runtime.prompt_budget_snapshot`, `memory_runtime.record_token_usage`, `memory_runtime.save_file_state_snapshot`, `memory_runtime.save_lrfu_snapshot`, `memory_runtime.save_messages`, `memory_runtime.save_messages_now`, `memory_runtime.save_tool_output`, `memory_runtime.start_session`, `memory_runtime.tool_output_prompt_content`, `messages.append`, `parts.append`, `persistent_assistant_tool_message`, `print_prompt_debug_with_previous`, `print_token_block`, `print_turn_token_summary`, `range`, `render_current_turn_for_model`, `replace`, `round_messages.append`, `save_session_state`, `seen_tool_failures.add`, `set`, `should_generate_summary`, `skill_runtime.system_hint`, `stream_one_round`, `summarize_engineering_state`, `tool_call.arguments.strip`, `tool_call_metadata`, `tool_output.startswith`, `truncate_tool_output`
- 函数 `should_generate_summary(memory_runtime: MemoryRuntime, messages: list[dict[str, Any]], tools: list[dict[str, Any]], prompt: str) -> bool`（L966）：执行模块级业务逻辑。；调用：`memory_runtime.prompt_budget_snapshot`
- 函数 `async summarize_engineering_state(client: AsyncOpenAI, model: str, messages: list[dict[str, Any]]) -> str`（L982）：执行模块级业务逻辑。；调用：`client.chat.completions.create`, `json.dumps`, `prompt_path.read_text`
- 函数 `truncate_tool_output(output: str) -> str`（L1018）：执行模块级业务逻辑。；调用：`len`
- 函数 `build_turn_temporary_system_messages(workspace_tracker: Any | None) -> list[dict[str, Any]]`（L1025）：执行模块级业务逻辑。；调用：无
- 函数 `with_workspace_change_notice(messages: list[dict[str, Any]], workspace_tracker: Any | None) -> list[dict[str, Any]]`（L1029）：执行模块级业务逻辑。；调用：`list`
- 函数 `with_turn_temporary_system_messages(messages: list[dict[str, Any]], temporary_system_messages: list[dict[str, Any]]) -> list[dict[str, Any]]`（L1033）：执行模块级业务逻辑。；调用：`get`, `list`
- 函数 `workspace_change_notice_content(workspace_tracker: Any | None) -> str`（L1043）：执行模块级业务逻辑。；调用：无
- 函数 `async build_round_tools(prompt: str, default_tools: list[dict[str, Any]], skill_runtime: Any | None, core_tool_schemas: list[dict[str, Any]] | None, capability_router: Any | None = None) -> list[dict[str, Any]]`（L1047）：执行模块级业务逻辑。；调用：`capability_router.build_tools_for_prompt`, `format_openai_tools`, `skill_runtime.build_tools_for_prompt_async`
- 函数 `async main() -> None`（L1063）：执行模块级业务逻辑。；调用：`AsyncOpenAI`, `ask_deepseek`, `client.close`, `create_default_registry`, `format_openai_tools`, `print`, `registry.get_all_schemas`

### `mycodingagent/llm_runtime/context.py`

- 模块：`mycodingagent.llm_runtime.context`
- 职责：模型请求、流式响应、工具循环、Prompt 上下文和 Token 统计。
- 内部依赖：`mycodingagent.memory.budget`
- 类 `class WorkspaceChanges`（L16）：封装该模块的状态与行为。
- 类 `class ContextBudgetState`（L22）：封装该模块的状态与行为。
- 类 `class RuntimeContextMetadata`（L30）：封装该模块的状态与行为。
- 类 `class RuntimeContext`（L36）：封装该模块的状态与行为。
  - `to_payload(self) -> dict[str, Any]`（L45）；调用：`asdict`
- 类 `class RenderedPrompt`（L50）：封装该模块的状态与行为。
- 类 `class RuntimeContextBuilder`（L63）：封装该模块的状态与行为。
  - `__init__(self, *, workspace_tracker: Any | None = None, context_budget: ContextBudgetState | None = None, capabilities: Any | None = None, task_snapshot: str | None = None, recovery_hint: str | None = RECOVERY_HINT) -> None`（L64）；调用：无
  - `build(self) -> RuntimeContext`（L79）；调用：`RuntimeContext`, `self._capability_payload`, `self._workspace_changes`
  - `_workspace_changes(self) -> WorkspaceChanges`（L88）；调用：`WorkspaceChanges`, `callable`, `consume`, `getattr`, `int`, `str`, `tuple`
  - `_capability_payload(self) -> dict[str, Any] | None`（L97）；调用：`callable`, `getattr`, `isinstance`, `to_runtime_payload`
- 类 `class PromptRenderer`（L108）：封装该模块的状态与行为。
  - `render_current_user_message(runtime_context: RuntimeContext, user_prompt: str) -> RenderedPrompt`（L110）；调用：`RenderedPrompt`, `estimate_tokens`, `hashlib.sha256`, `hexdigest`, `json.dumps`, `runtime_context.to_payload`, `runtime_context_json.encode`
- 函数 `render_current_turn_for_model(messages: list[dict[str, Any]], *, current_turn_start: int, rendered_prompt: RenderedPrompt) -> list[dict[str, Any]]`（L141）：执行模块级业务逻辑。；调用：`dict`, `get`, `len`, `range`
- 函数 `is_rendered_runtime_prompt(content: str) -> bool`（L157）：执行模块级业务逻辑。；调用：无
- 函数 `extract_user_request_from_rendered_prompt(content: str) -> str | None`（L161）：执行模块级业务逻辑。；调用：`content.find`, `is_rendered_runtime_prompt`, `len`, `strip`

### `mycodingagent/mcp_integration/__init__.py`

- 模块：`mycodingagent.mcp_integration`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：`mycodingagent.mcp_integration.config`, `mycodingagent.mcp_integration.execution`, `mycodingagent.mcp_integration.manager`, `mycodingagent.mcp_integration.models`
- 定义：无公开类或函数。

### `mycodingagent/mcp_integration/cache.py`

- 模块：`mycodingagent.mcp_integration.cache`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：`mycodingagent.mcp_integration.config`, `mycodingagent.mcp_integration.models`
- 类 `class MCPMetadataEntry`（L11）：封装该模块的状态与行为。
  - `summary(self) -> MCPServerSummary`（L21）；调用：`MCPServerSummary`, `len`
- 类 `class MCPMetadataCache`（L39）：封装该模块的状态与行为。
  - `__init__(self) -> None`（L40）；调用：无
  - `sync_configs(self, configs: dict[str, MCPServerConfig]) -> None`（L43）；调用：`MCPMetadataEntry`, `configs.items`, `self._entries.get`
  - `get(self, server: str) -> MCPMetadataEntry | None`（L53）；调用：`self._entries.get`
  - `servers(self) -> list[MCPServerSummary]`（L56）；调用：`entry.summary`, `self._entries.values`, `sorted`
  - `update_discovery(self, server: str, *, tools: list[MCPItemSummary] | None = None, resources: list[MCPItemSummary] | None = None, prompts: list[MCPItemSummary] | None = None, connected: bool = True, error: str = '') -> None`（L59）；调用：`self._entries.get`, `time.time`
  - `mark_error(self, server: str, error: str) -> None`（L83）；调用：`self._entries.get`, `time.time`
  - `mark_available(self, server: str) -> None`（L92）；调用：`self._entries.get`, `time.time`
  - `unavailable_servers(self) -> list[str]`（L100）；调用：`self._entries.values`, `sorted`

### `mycodingagent/mcp_integration/config.py`

- 模块：`mycodingagent.mcp_integration.config`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：无
- 类 `class MCPPermissionConfig`（L11）：封装该模块的状态与行为。
- 类 `class MCPServerConfig`（L19）：封装该模块的状态与行为。
  - `searchable_terms(self) -> tuple[str, ...]`（L34）；调用：`tuple`
- 类 `class MCPConfigLoader`（L47）：Load project, user, and explicit MCP server configuration files.
  - `__init__(self, *, project_path: Path | None = None, user_path: Path | None = None, env_path_var: str = 'MYCODINGAGENT_MCP_CONFIG') -> None`（L50）；调用：`Path.cwd`, `Path.home`
  - `load(self) -> dict[str, MCPServerConfig]`（L61）；调用：`merged.items`, `merged.update`, `self._load_path`, `self.config_paths`
  - `config_paths(self) -> list[Path]`（L68）；调用：`Path`, `expanduser`, `os.getenv`, `paths.append`
  - `_load_path(self, path: Path) -> dict[str, MCPServerConfig]`（L75）；调用：`ValueError`, `_server_config_from_dict`, `isinstance`, `json.loads`, `path.exists`, `path.read_text`, `raw.get`, `servers.items`, `str`
- 函数 `_server_config_from_dict(name: str, data: dict[str, Any]) -> MCPServerConfig | None`（L95）：执行模块级业务逻辑。；调用：`MCPServerConfig`, `ValueError`, `_permission_config`, `_string_tuple`, `bool`, `data.get`, `dict`, `items`, `str`, `strip`
- 函数 `_string_tuple(value: Any) -> tuple[str, ...]`（L116）：执行模块级业务逻辑。；调用：`isinstance`, `str`, `strip`, `tuple`
- 函数 `_permission_config(value: Any) -> MCPPermissionConfig`（L126）：执行模块级业务逻辑。；调用：`MCPPermissionConfig`, `_string_tuple`, `bool`, `isinstance`, `value.get`

### `mycodingagent/mcp_integration/execution.py`

- 模块：`mycodingagent.mcp_integration.execution`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：`mycodingagent.mcp_integration.models`
- 函数 `normalize_mcp_result(*, server: str, operation: str, name: str, result: Any) -> MCPExecutionResult`（L9）：执行模块级业务逻辑。；调用：`MCPExecutionResult`, `_content_metadata`, `append`, `bool`, `getattr`, `isinstance`, `join`, `json.dumps`, `metadata.setdefault`, `other_parts.append`, `str`, `text_parts.append`
- 函数 `_content_metadata(item: Any) -> dict[str, Any]`（L71）：执行模块级业务逻辑。；调用：`getattr`, `str`, `type`

### `mycodingagent/mcp_integration/hooks.py`

- 模块：`mycodingagent.mcp_integration.hooks`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：`mycodingagent.mcp_integration.policy`
- 类 `class MCPToolApprovalHook`（L11）：封装该模块的状态与行为。
  - `async approve(self, request: MCPApprovalRequest) -> MCPApprovalDecision`（L12）；调用：`MCPApprovalDecision`
- 类 `class CLIApprovalHook(MCPToolApprovalHook)`（L17）：封装该模块的状态与行为。
  - `async approve(self, request: MCPApprovalRequest) -> MCPApprovalDecision`（L20）；调用：`MCPApprovalDecision`, `input`, `json.dumps`, `len`, `lower`, `print`, `strip`

### `mycodingagent/mcp_integration/manager.py`

- 模块：`mycodingagent.mcp_integration.manager`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：`mycodingagent.mcp_integration.cache`, `mycodingagent.mcp_integration.config`, `mycodingagent.mcp_integration.execution`, `mycodingagent.mcp_integration.models`
- 类 `class MCPClientManager`（L14）：Own real MCP protocol connections, discovery metadata, and protocol calls.
  - `__init__(self, *, config_loader: MCPConfigLoader | None = None, metadata_cache: MCPMetadataCache | None = None) -> None`（L17）；调用：`MCPConfigLoader`, `MCPMetadataCache`
  - `async initialize(self) -> None`（L30）；调用：`self.reload_config`
  - `reload_config(self) -> None`（L33）；调用：`self.config_loader.load`, `self.metadata_cache.sync_configs`
  - `async close(self) -> None`（L37）；调用：`contextlib.suppress`, `list`, `self._close_session`, `self._reconnect_task.cancel`, `self._reconnect_task.done`
  - `server_count(self) -> int`（L45）；调用：`len`
  - `connected_count(self) -> int`（L48）；调用：`self.available_count`
  - `available_count(self) -> int`（L51）；调用：`self.metadata_cache.servers`, `sum`
  - `list_servers(self) -> list[MCPServerSummary]`（L54）；调用：`self.metadata_cache.servers`
  - `async refresh_server(self, server: str) -> MCPServerSummary | None`（L57）；调用：`entry.summary`, `self._ensure_session`, `self._list_prompts_from_session`, `self._list_resources_from_session`, `self._list_tools_from_session`, `self._mark_server_unavailable`, `self.metadata_cache.get`, `self.metadata_cache.update_discovery`, `str`
  - `async list_tools(self, server: str) -> dict[str, Any]`（L78）；调用：`item.to_payload`, `self._ensure_discovered`, `self.metadata_cache.get`, `summary.to_payload`
  - `async list_resources(self, server: str) -> dict[str, Any]`（L87）；调用：`item.to_payload`, `self._ensure_discovered`, `self.metadata_cache.get`, `summary.to_payload`
  - `async list_prompts(self, server: str) -> dict[str, Any]`（L96）；调用：`item.to_payload`, `self._ensure_discovered`, `self.metadata_cache.get`, `summary.to_payload`
  - `async call_tool(self, server: str, tool: str, arguments: dict[str, Any] | None = None) -> MCPExecutionResult`（L105）；调用：`MCPExecutionResult`, `normalize_mcp_result`, `self._ensure_session`, `self._mark_server_unavailable`, `self._unavailable_result`, `session.call_tool`, `str`
  - `async read_resource(self, server: str, uri: str) -> MCPExecutionResult`（L119）；调用：`MCPExecutionResult`, `normalize_mcp_result`, `self._ensure_session`, `self._mark_server_unavailable`, `self._unavailable_result`, `session.read_resource`, `str`
  - `async get_prompt(self, server: str, prompt: str, arguments: dict[str, Any] | None = None) -> MCPExecutionResult`（L133）；调用：`MCPExecutionResult`, `normalize_mcp_result`, `self._ensure_session`, `self._mark_server_unavailable`, `self._unavailable_result`, `session.get_prompt`, `str`
  - `unavailable_servers(self) -> list[str]`（L147）；调用：`self.metadata_cache.unavailable_servers`
  - `schedule_reconnect_unavailable_servers(self) -> asyncio.Task | None`（L150）；调用：`asyncio.create_task`, `self._reconnect_task.done`, `self.reconnect_unavailable_servers`, `self.unavailable_servers`
  - `async reconnect_unavailable_servers(self) -> list[MCPServerSummary]`（L158）；调用：`restored.append`, `self.refresh_server`, `self.unavailable_servers`
  - `async _ensure_discovered(self, server: str) -> MCPServerSummary | None`（L166）；调用：`entry.summary`, `self.metadata_cache.get`, `self.refresh_server`
  - `async _ensure_session(self, server: str) -> Any`（L174）；调用：`ClientSession`, `RuntimeError`, `StdioServerParameters`, `contextlib.suppress`, `env.setdefault`, `env.update`, `list`, `os.environ.copy`, `self._sessions.get`, `session.initialize`, `session_context.__aenter__`, `session_context.__aexit__`, `stdio_client`, `stdio_context.__aenter__`, `stdio_context.__aexit__`
  - `async _close_session(self, server: str) -> None`（L207）；调用：`contextlib.suppress`, `self._session_contexts.pop`, `self._sessions.pop`, `session_context.__aexit__`, `stdio_context.__aexit__`
  - `async _mark_server_unavailable(self, server: str, error: str) -> None`（L218）；调用：`self._close_session`, `self.metadata_cache.mark_error`
  - `_unavailable_result(self, server: str, *, operation: str, name: str) -> MCPExecutionResult | None`（L222）；调用：`MCPExecutionResult`, `self.metadata_cache.get`
  - `async _list_tools_from_session(self, server: str) -> list[MCPItemSummary]`（L236）；调用：`_item_summary`, `getattr`, `self._ensure_session`, `session.list_tools`
  - `async _list_resources_from_session(self, server: str) -> list[MCPItemSummary]`（L241）；调用：`_item_summary`, `contextlib.suppress`, `getattr`, `self._ensure_session`, `session.list_resources`
  - `async _list_prompts_from_session(self, server: str) -> list[MCPItemSummary]`（L248）；调用：`_item_summary`, `contextlib.suppress`, `getattr`, `self._ensure_session`, `session.list_prompts`
- 函数 `_item_summary(item: Any) -> MCPItemSummary`（L256）：执行模块级业务逻辑。；调用：`MCPItemSummary`, `getattr`, `str`

### `mycodingagent/mcp_integration/models.py`

- 模块：`mycodingagent.mcp_integration.models`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：无
- 类 `class MCPItemSummary`（L8）：封装该模块的状态与行为。
  - `to_payload(self) -> dict[str, Any]`（L13）；调用：`asdict`
- 类 `class MCPServerSummary`（L18）：封装该模块的状态与行为。
  - `to_payload(self) -> dict[str, Any]`（L33）；调用：`asdict`
- 类 `class MCPExecutionResult`（L38）：封装该模块的状态与行为。
  - `to_payload(self) -> dict[str, Any]`（L47）；调用：`asdict`

### `mycodingagent/mcp_integration/policy.py`

- 模块：`mycodingagent.mcp_integration.policy`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：`mycodingagent.mcp_integration.config`
- 类 `class MCPApprovalRequest`（L16）：封装该模块的状态与行为。
- 类 `class MCPApprovalDecision`（L25）：封装该模块的状态与行为。
- 类 `class MCPToolPermissionPolicy`（L30）：封装该模块的状态与行为。
  - `classify(self, *, server_config: MCPServerConfig | None, tool_name: str) -> MCPToolRisk`（L31）；调用：`_matches`, `any`, `lower`, `normalized.startswith`, `tool_name.strip`
  - `requires_approval(self, risk: MCPToolRisk) -> bool`（L51）；调用：无
- 函数 `_matches(tool_name: str, configured: tuple[str, ...]) -> bool`（L55）：执行模块级业务逻辑。；调用：`any`, `item.strip`, `lower`

### `mycodingagent/memory/__init__.py`

- 模块：`mycodingagent.memory`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.memory.budget`, `mycodingagent.memory.checkpoint`, `mycodingagent.memory.compressor`, `mycodingagent.memory.context_epoch`, `mycodingagent.memory.context_objects`, `mycodingagent.memory.models`, `mycodingagent.memory.runtime`, `mycodingagent.memory.stores`
- 定义：无公开类或函数。

### `mycodingagent/memory/budget.py`

- 模块：`mycodingagent.memory.budget`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：无
- 类 `class BudgetStage(str, Enum)`（L9）：封装该模块的状态与行为。
- 类 `class PromptBudgetSnapshot`（L17）：封装该模块的状态与行为。
  - `to_prompt_text(self) -> str`（L28）；调用：无
- 类 `class PromptBudgetManager`（L43）：封装该模块的状态与行为。
  - `__init__(self, *, context_window: int, soft_ratio: float, working_ratio: float, emergency_ratio: float, reserved_reasoning_tokens: int, reserved_output_tokens: int, reserved_tool_tokens: int) -> None`（L44）；调用：无
  - `snapshot(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, current_prompt: str = '', extra_tokens: int = 0) -> PromptBudgetSnapshot`（L63）；调用：`PromptBudgetSnapshot`, `estimate_tokens`, `max`, `self.stage_for_usage`
  - `stage_for_usage(self, usage_ratio: float) -> BudgetStage`（L93）；调用：无
- 函数 `estimate_tokens(value: Any) -> int`（L103）：执行模块级业务逻辑。；调用：`isinstance`, `json.dumps`, `len`, `max`

### `mycodingagent/memory/checkpoint.py`

- 模块：`mycodingagent.memory.checkpoint`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.memory.budget`, `mycodingagent.memory.models`
- 类 `class TurnState`（L31）：封装该模块的状态与行为。
- 类 `class CheckpointDecision`（L40）：封装该模块的状态与行为。
- 类 `class RolloverResult`（L47）：封装该模块的状态与行为。
- 类 `class SnapshotGenerator(Protocol)`（L54）：封装该模块的状态与行为。
  - `generate_delta(self, *, session_id: str, previous_snapshot: ConversationSnapshot | None, new_messages: list[dict[str, Any]], runtime_state: dict[str, Any], turn_start_index: int, turn_end_index: int) -> SnapshotDelta`（L55）；调用：无
  - `merge_snapshot(self, *, session_id: str, previous_snapshot: ConversationSnapshot | None, delta: SnapshotDelta, runtime_state: dict[str, Any]) -> ConversationSnapshot`（L67）；调用：无
- 类 `class StructuredSnapshotGenerator`（L78）：封装该模块的状态与行为。
  - `generate_delta(self, *, session_id: str, previous_snapshot: ConversationSnapshot | None, new_messages: list[dict[str, Any]], runtime_state: dict[str, Any], turn_start_index: int, turn_end_index: int) -> SnapshotDelta`（L79）；调用：`SnapshotDelta`, `conclusions.append`, `context_refs.append`, `context_refs.extend`, `dedupe`, `extract_context_refs`, `extracted_action_lines`, `isinstance`, `looks_like_decision`, `message.get`, `message_text`, `metadata.get`, `runtime_state.get`, `str`, `target.append`, `truncate`, `user_intentions.append`, `uuid4`
  - `merge_snapshot(self, *, session_id: str, previous_snapshot: ConversationSnapshot | None, delta: SnapshotDelta, runtime_state: dict[str, Any]) -> ConversationSnapshot`（L132）；调用：`ConversationSnapshot`, `build_summary`, `dict`, `infer_project_status`, `memory_state.update`, `merge_lists`, `runtime_state.get`, `uuid4`, `workspace_state.update`
- 类 `class CheckpointManager`（L185）：封装该模块的状态与行为。
  - `__init__(self, *, memory_runtime: Any, prompt_budget_manager: Any, snapshot_generator: SnapshotGenerator | None = None) -> None`（L186）；调用：`StructuredSnapshotGenerator`
  - `should_checkpoint(self, turn_state: TurnState, budget_snapshot: PromptBudgetSnapshot) -> CheckpointDecision`（L199）；调用：`CheckpointDecision`, `max`
  - `create_session_delta(self, session_id: str, messages: list[dict[str, Any]], previous_checkpoint_index: int | None = None, runtime_state: dict[str, Any] | None = None) -> SnapshotDelta`（L219）；调用：`len`, `max`, `min`, `self.memory_runtime.store.get_latest_snapshot_for_session`, `self.snapshot_generator.generate_delta`
  - `create_incremental_snapshot(self, previous_snapshot: ConversationSnapshot | None, delta: SnapshotDelta, runtime_state: dict[str, Any] | None = None) -> ConversationSnapshot`（L240）；调用：`self.snapshot_generator.merge_snapshot`
  - `checkpoint_session(self, *, session_id: str, messages: list[dict[str, Any]], runtime_state: dict[str, Any], trigger_reason: str, usage_ratio: float) -> ConversationSnapshot`（L253）；调用：`CheckpointRecord`, `len`, `self._latest_runtime_snapshot`, `self.create_incremental_snapshot`, `self.create_session_delta`, `self.memory_runtime.store.save_checkpoint_record`, `self.memory_runtime.store.save_conversation_snapshot`, `self.memory_runtime.store.save_snapshot_delta`, `uuid4`
  - `rollover_session(self, *, session_id: str, snapshot: ConversationSnapshot, system_prompt_source: dict[str, Any] | None) -> RolloverResult`（L281）；调用：`RolloverResult`, `copy_system_message`, `format_snapshot_prompt`, `len`, `self.memory_runtime.store.ensure_session`, `self.memory_runtime.store.mark_session_historical`, `self.memory_runtime.store.save_messages`, `uuid4`
  - `restore_session_snapshot(self, session_id: str) -> ConversationSnapshot | None`（L316）；调用：`self.memory_runtime.store.get_conversation_snapshot`, `self.memory_runtime.store.get_historical_session`, `self.memory_runtime.store.touch_historical_session`
  - `_latest_runtime_snapshot(self, session_id: str) -> ConversationSnapshot | None`（L323）；调用：`getattr`, `self.memory_runtime.store.get_conversation_snapshot`, `self.memory_runtime.store.get_latest_snapshot_for_session`
- 函数 `format_snapshot_prompt(snapshot: ConversationSnapshot) -> str`（L332）：执行模块级业务逻辑。；调用：`asdict`, `join`, `json.dumps`, `lines.append`, `payload.get`
- 函数 `copy_system_message(system_prompt_source: dict[str, Any] | None) -> dict[str, Any]`（L340）：执行模块级业务逻辑。；调用：`system_prompt_source.get`
- 函数 `message_text(message: dict[str, Any]) -> str`（L346）：执行模块级业务逻辑。；调用：`content.strip`, `isinstance`, `json.dumps`, `message.get`
- 函数 `extracted_action_lines(text: str) -> list[str]`（L353）：执行模块级业务逻辑。；调用：`lines.append`, `raw_line.strip`, `text.splitlines`
- 函数 `looks_like_decision(line: str) -> bool`（L362）：执行模块级业务逻辑。；调用：`any`, `line.lower`
- 函数 `extract_context_refs(text: str) -> list[str]`（L367）：执行模块级业务逻辑。；调用：`line.split`, `refs.append`, `strip`, `text.splitlines`
- 函数 `infer_project_status(delta: SnapshotDelta, previous_snapshot: ConversationSnapshot | None) -> str`（L375）：执行模块级业务逻辑。；调用：无
- 函数 `build_summary(user_intentions: list[str], conclusions: list[str], project_status: str) -> str`（L385）：执行模块级业务逻辑。；调用：`join`, `parts.append`
- 函数 `merge_lists(existing: list[str], incoming: list[str], *, limit: int = 80) -> list[str]`（L395）：执行模块级业务逻辑。；调用：`dedupe`
- 函数 `dedupe(items: list[str]) -> list[str]`（L399）：执行模块级业务逻辑。；调用：`join`, `result.append`, `seen.add`, `set`, `split`, `str`
- 函数 `truncate(text: str, limit: int) -> str`（L411）：执行模块级业务逻辑。；调用：`join`, `len`, `text.split`

### `mycodingagent/memory/compressor.py`

- 模块：`mycodingagent.memory.compressor`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.memory.models`
- 类 `class ToolOutputRef`（L23）：封装该模块的状态与行为。
- 类 `class ContextCompressor`（L31）：封装该模块的状态与行为。
  - `__init__(self, *, context_window: int | None = None, tool_preview_chars: int | None = None, recent_rounds_for_average: int | None = None, recent_messages_after_summary: int | None = None) -> None`（L32）；调用：无
  - `compress_messages(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, current_prompt: str = '', tool_output_refs: dict[str, ToolOutputRef] | None = None, summary_text: str = '') -> CompressionResult`（L45）；调用：`CompressionResult`, `dict`, `estimate_size`, `json.dumps`, `len`, `max`, `sanitize_message_for_model`, `self._preview_tool_outputs`, `self._summarized_context`, `self.predict_next_context_size`
  - `should_compress(self, messages: list[dict[str, Any]]) -> bool`（L101）；调用：`self.predict_next_context_size`
  - `predict_next_context_size(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, current_prompt: str = '') -> int`（L104）；调用：`estimate_size`, `len`, `self.average_recent_output_size`
  - `average_recent_output_size(self, messages: list[dict[str, Any]]) -> int`（L118）；调用：`estimate_size`, `int`, `len`, `message.get`, `sum`
  - `_preview_tool_outputs(self, messages: list[dict[str, Any]], refs: dict[str, ToolOutputRef], *, reproducible_only: bool) -> list[dict[str, Any]]`（L128）；调用：`dict`, `get`, `message.get`, `refs.get`, `refs.values`, `result.append`, `sorted`, `tool_output_reference_text`
  - `_summarized_context(self, messages: list[dict[str, Any]], summary_text: str) -> list[dict[str, Any]]`（L156）；调用：`message.get`
- 函数 `estimate_size(value: Any) -> int`（L166）：执行模块级业务逻辑。；调用：`json.dumps`, `len`
- 函数 `sanitize_message_for_model(message: dict[str, Any]) -> dict[str, Any]`（L170）：执行模块级业务逻辑。；调用：`message.items`
- 函数 `is_reproducible_tool(tool_name: str, output: str = '') -> bool`（L175）：执行模块级业务逻辑。；调用：`output.startswith`
- 函数 `tool_output_reference_text(ref: ToolOutputRef) -> str`（L183）：执行模块级业务逻辑。；调用：`lower`, `str`

### `mycodingagent/memory/context_epoch.py`

- 模块：`mycodingagent.memory.context_epoch`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.memory.budget`, `mycodingagent.memory.models`
- 类 `class ContextEpochStore(Protocol)`（L11）：封装该模块的状态与行为。
  - `save_context_epoch(self, state: ContextEpochState) -> None`（L12）；调用：无
  - `load_active_context_epoch(self, session_id: str) -> ContextEpochState | None`（L15）；调用：无
- 类 `class ContextEpochManager`（L19）：封装该模块的状态与行为。
  - `__init__(self, *, store: ContextEpochStore, context_window: int, warning_ratio: float, force_ratio: float) -> None`（L20）；调用：无
  - `remember(self, state: ContextEpochState) -> ContextEpochState`（L34）；调用：无
  - `get(self, session_id: str) -> ContextEpochState | None`（L38）；调用：`self._states.get`, `self.remember`, `self.store.load_active_context_epoch`
  - `ensure(self, *, session_id: str, messages: list[dict[str, Any]], current_turn_start: int | None = None) -> ContextEpochState`（L45）；调用：`last_user_message_index`, `len`, `max`, `min`, `self.create`, `self.get`
  - `create(self, *, session_id: str, start_message_index: int) -> ContextEpochState`（L63）；调用：`ContextEpochState`, `max`, `self.remember`, `self.store.save_context_epoch`, `uuid4`
  - `request_commit(self, *, session_id: str, reason: str, summary: str, retain_context_ids: list[str] | None = None, active_files: list[str] | None = None, next_context_hint: str = '', trigger: str = 'model') -> ContextEpochState`（L73）；调用：`ValueError`, `dedupe_strings`, `join`, `next_context_hint.strip`, `reason.split`, `self.get`, `self.store.save_context_epoch`, `summary.strip`
  - `finalize(self, *, session_id: str, end_message_index: int, pending_tool_call: bool) -> tuple[ContextEpochState, ContextEpochState] | None`（L116）；调用：`max`, `self.create`, `self.get`, `self.store.save_context_epoch`, `time`
  - `snapshot(self, *, session_id: str, messages: list[dict[str, Any]], current_turn_start: int | None = None) -> HotContextBudgetSnapshot`（L134）；调用：`HotContextBudgetSnapshot`, `estimate_tokens`, `len`, `max`, `min`, `self.ensure`
  - `delete(self, session_id: str) -> None`（L160）；调用：`self._states.pop`
- 函数 `last_user_message_index(messages: list[dict[str, Any]]) -> int | None`（L164）：执行模块级业务逻辑。；调用：`get`, `len`, `range`
- 函数 `dedupe_strings(values: list[str]) -> list[str]`（L171）：执行模块级业务逻辑。；调用：`result.append`, `seen.add`, `set`, `value.strip`
- 函数 `collect_context_epoch_files(messages: list[dict[str, Any]], start_message_index: int) -> list[str]`（L183）：执行模块级业务逻辑。；调用：`dedupe_strings`, `files.append`, `files.extend`, `isinstance`, `max`, `message.get`, `metadata.get`, `str`
- 函数 `automatic_context_epoch_summary(messages: list[dict[str, Any]], start_message_index: int) -> str`（L200）：执行模块级业务逻辑。；调用：`len`, `max`, `message.get`, `str`, `strip`
- 函数 `format_hot_context_notice(snapshot: HotContextBudgetSnapshot) -> str`（L214）：执行模块级业务逻辑。；调用：`lower`, `str`
- 函数 `format_context_epoch_commit_report(committed: ContextEpochState, next_state: ContextEpochState) -> str`（L231）：执行模块级业务逻辑。；调用：无

### `mycodingagent/memory/context_objects.py`

- 模块：`mycodingagent.memory.context_objects`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：无
- 类 `class ContextContentType(str, Enum)`（L12）：封装该模块的状态与行为。
- 类 `class ContextLifecycleState(str, Enum)`（L19）：封装该模块的状态与行为。
- 类 `class RecoverableContextObject`（L27）：封装该模块的状态与行为。
  - `to_dict(self) -> dict[str, Any]`（L48）；调用：`asdict`
  - `from_dict(cls, payload: dict[str, Any]) -> RecoverableContextObject`（L55）；调用：`ContextContentType`, `ContextLifecycleState`, `cls`, `data.get`, `dict`
- 函数 `build_recoverable_context(*, session_id: str, tool_call_id: str, tool_name: str, arguments_json: str, content: str, reproducible: bool, token_count: int, metadata: dict[str, Any] | None = None) -> RecoverableContextObject`（L64）：执行模块级业务逻辑。；调用：`RecoverableContextObject`, `extract_entities`, `extract_keywords`, `extract_related_files`, `infer_content_type`, `len`, `short_summary_for_tool_output`, `uuid4`
- 函数 `infer_content_type(content: str) -> ContextContentType`（L97）：执行模块级业务逻辑。；调用：`content.lstrip`, `json.loads`, `stripped.startswith`
- 函数 `short_summary_for_tool_output(tool_name: str, arguments_json: str, content: str) -> str`（L110）：执行模块级业务逻辑。；调用：`args.get`, `isinstance`, `json.loads`, `len`, `str`
- 函数 `extract_related_files(arguments_json: str, content: str) -> list[str]`（L125）：执行模块级业务逻辑。；调用：`args.get`, `candidates.append`, `candidates.extend`, `dedupe_keep_order`, `isinstance`, `json.loads`, `re.findall`
- 函数 `extract_keywords(tool_name: str, arguments_json: str, content: str) -> list[str]`（L140）：执行模块级业务逻辑。；调用：`dedupe_keep_order`, `re.findall`, `word.lower`, `words.extend`
- 函数 `extract_entities(content: str) -> list[str]`（L148）：执行模块级业务逻辑。；调用：`dedupe_keep_order`, `re.findall`
- 函数 `dedupe_keep_order(values: list[str]) -> list[str]`（L153）：执行模块级业务逻辑。；调用：`result.append`, `seen.add`, `set`, `value.strip`

### `mycodingagent/memory/context_store.py`

- 模块：`mycodingagent.memory.context_store`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.memory.context_objects`
- 类 `class ExternalContextStore(Protocol)`（L8）：封装该模块的状态与行为。
  - `save_context(self, context: RecoverableContextObject, content: str) -> str`（L9）；调用：无
  - `load_context(self, context_id: str) -> str | None`（L12）；调用：无
  - `load_partial_context(self, context_id: str, *, offset: int = 0, limit: int = 12000) -> tuple[str, int | None] | None`（L15）；调用：无
  - `delete_context(self, context_id: str) -> bool`（L18）；调用：无
  - `query_metadata(self, context_id: str) -> RecoverableContextObject | None`（L21）；调用：无
  - `search_metadata(self, session_id: str, query: str = '', *, limit: int = 20) -> list[RecoverableContextObject]`（L24）；调用：无

### `mycodingagent/memory/contracts.py`

- 模块：`mycodingagent.memory.contracts`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.memory.models`
- 类 `class ContextEpochControl(Protocol)`（L8）：封装该模块的状态与行为。
  - `get_current_session_id(self) -> str | None`（L9）；调用：无
  - `request_context_epoch_commit(self, *, reason: str, summary: str, retain_context_ids: list[str] | None = None, active_files: list[str] | None = None, next_context_hint: str = '', trigger: str = 'model', session_id: str | None = None) -> ContextEpochState`（L12）；调用：无

### `mycodingagent/memory/message_filters.py`

- 模块：`mycodingagent.memory.message_filters`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：无
- 函数 `is_skill_related_tool(tool_name: str) -> bool`（L15）：执行模块级业务逻辑。；调用：`tool_name.startswith`
- 函数 `persistent_assistant_tool_message(assistant_message: dict[str, Any]) -> dict[str, Any] | None`（L19）：执行模块级业务逻辑。；调用：`assistant_message.get`, `list`

### `mycodingagent/memory/models.py`

- 模块：`mycodingagent.memory.models`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：无
- 类 `class MemoryScope(str, Enum)`（L10）：封装该模块的状态与行为。
- 类 `class ContextEpochStatus(str, Enum)`（L16）：封装该模块的状态与行为。
- 类 `class ContextEpochState`（L23）：封装该模块的状态与行为。
- 类 `class HotContextBudgetSnapshot`（L40）：封装该模块的状态与行为。
- 类 `class MemoryEntry`（L52）：封装该模块的状态与行为。
- 类 `class MemoryQuery`（L62）：封装该模块的状态与行为。
- 类 `class CompressionResult`（L70）：封装该模块的状态与行为。
- 类 `class TokenUsageRecord`（L77）：封装该模块的状态与行为。
- 类 `class TokenUsageSummary`（L94）：封装该模块的状态与行为。
  - `add(self, record: TokenUsageRecord) -> None`（L102）；调用：无
- 类 `class ToolOutputRecord`（L112）：封装该模块的状态与行为。
- 类 `class ToolInvocationMetadata`（L125）：封装该模块的状态与行为。
- 类 `class HistoricalTurn`（L153）：封装该模块的状态与行为。
- 类 `class ConversationSnapshot`（L164）：封装该模块的状态与行为。
- 类 `class SnapshotDelta`（L182）：封装该模块的状态与行为。
- 类 `class CheckpointRecord`（L197）：封装该模块的状态与行为。
- 类 `class HistoricalSessionRef`（L208）：封装该模块的状态与行为。
- 类 `class SessionState`（L219）：封装该模块的状态与行为。
- 类 `class SessionListItem`（L235）：封装该模块的状态与行为。

### `mycodingagent/memory/runtime.py`

- 模块：`mycodingagent.memory.runtime`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.memory.budget`, `mycodingagent.memory.checkpoint`, `mycodingagent.memory.compressor`, `mycodingagent.memory.context_epoch`, `mycodingagent.memory.context_objects`, `mycodingagent.memory.message_filters`, `mycodingagent.memory.models`, `mycodingagent.memory.stores`, `mycodingagent.memory.working_context`, `mycodingagent.workspace.identity`
- 类 `class MemoryWriteTask`（L53）：封装该模块的状态与行为。
- 类 `class ContextMode(str, Enum)`（L58）：封装该模块的状态与行为。
- 类 `class ContextRenderDecision`（L64）：封装该模块的状态与行为。
- 类 `class MemoryRuntime`（L73）：封装该模块的状态与行为。
  - `__init__(self, *, store: SQLiteMemoryStore | None = None, compressor: ContextCompressor | None = None, model: str | None = None, workspace_root: str | None = None) -> None`（L74）；调用：`CONFIG.memory.context_window_for`, `CheckpointManager`, `ContextCompressor`, `ContextEpochManager`, `PromptBudgetManager`, `SQLiteMemoryStore`, `WorkingContext`, `self.start_async_writer`, `threading.Lock`, `workspace_fingerprint`, `workspace_label`, `workspace_root_text`
  - `start_async_writer(self) -> None`（L130）；调用：`asyncio.Queue`, `asyncio.get_running_loop`, `loop.create_task`, `self._run_writer`
  - `async _run_writer(self) -> None`（L140）；调用：`asyncio.get_running_loop`, `loop.run_in_executor`, `self._record_writer_error`, `self._write_queue.get`, `self._write_queue.task_done`
  - `async drain(self) -> None`（L153）；调用：`self._write_queue.join`
  - `async close(self) -> None`（L157）；调用：`contextlib.suppress`, `len`, `print`, `self._worker_task.cancel`, `self.await_pending_rollover`, `self.drain`
  - `_enqueue_write(self, description: str, callback: Callable[[], None]) -> None`（L170）；调用：`MemoryWriteTask`, `self._record_writer_error`, `self._write_queue.put_nowait`, `task.callback`
  - `_record_writer_error(self, description: str, exc: Exception) -> None`（L180）；调用：`print`, `self._writer_errors.append`
  - `start_session(self, model: str | None = None) -> str`（L184）；调用：`self._current_turn_summaries.clear`, `self._enqueue_write`, `self.store.ensure_session`, `uuid4`
  - `get_current_session_id(self) -> str | None`（L203）；调用：无
  - `clear_current_session_id(self) -> None`（L206）；调用：`self._current_turn_summaries.clear`
  - `get_active_context_epoch(self, session_id: str | None = None) -> ContextEpochState | None`（L211）；调用：`self.context_epoch_manager.get`
  - `ensure_context_epoch(self, *, session_id: str, messages: list[dict[str, Any]], current_turn_start: int | None = None) -> ContextEpochState`（L215）；调用：`self.context_epoch_manager.ensure`
  - `request_context_epoch_commit(self, *, reason: str, summary: str, retain_context_ids: list[str] | None = None, active_files: list[str] | None = None, next_context_hint: str = '', trigger: str = 'model', session_id: str | None = None) -> ContextEpochState`（L228）；调用：`ValueError`, `self.context_epoch_manager.request_commit`
  - `finalize_pending_context_epoch(self, *, session_id: str, messages: list[dict[str, Any]]) -> ContextEpochState | None`（L252）；调用：`format_context_epoch_commit_report`, `has_pending_tool_call`, `len`, `print`, `self._current_turn_summaries.clear`, `self.context_epoch_manager.finalize`, `self.force_context_virtualized`
  - `hot_context_budget_snapshot(self, *, session_id: str, messages: list[dict[str, Any]], current_turn_start: int | None = None) -> HotContextBudgetSnapshot`（L273）；调用：`self.context_epoch_manager.snapshot`
  - `context_mode(self, session_id: str | None = None) -> ContextMode`（L286）；调用：`self._context_modes.get`
  - `is_context_virtualized(self, session_id: str | None = None) -> bool`（L292）；调用：`self.context_mode`
  - `force_context_virtualized(self, session_id: str | None = None) -> None`（L295）；调用：无
  - `save_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None`（L300）；调用：`build_historical_turns`, `copy.deepcopy`, `self._enqueue_write`, `self._next_message_version`, `self._save_messages_if_current`
  - `save_messages_now(self, session_id: str, messages: list[dict[str, Any]]) -> None`（L309）；调用：`build_historical_turns`, `copy.deepcopy`, `self._next_message_version`, `self.store.ensure_session`, `self.store.save_historical_turns`, `self.store.save_messages`
  - `_next_message_version(self, session_id: str) -> int`（L324）；调用：`self._message_versions.get`
  - `_save_messages_if_current(self, session_id: str, messages: list[dict[str, Any]], historical_turns: list[HistoricalTurn], version: int) -> None`（L329）；调用：`self._message_versions.get`, `self.store.save_historical_turns`, `self.store.save_messages`
  - `load_session(self, session_id: str) -> SessionState | None`（L342）；调用：`has_pending_tool_call`, `self.context_epoch_manager.remember`, `self.ensure_context_epoch`, `self.finalize_pending_context_epoch`, `self.force_context_virtualized`, `self.store.has_committed_context_epoch`, `self.store.load_session`, `self.store.touch_session`
  - `record_token_usage(self, *, session_id: str, prompt_tokens: int, prompt_cache_hit_tokens: int, prompt_cache_miss_tokens: int, completion_tokens: int, total_tokens: int, model: str = '', prompt_hash: str = '', tools_hash: str = '', metadata: dict[str, Any] | None = None) -> TokenUsageSummary`（L359）；调用：`TokenUsageRecord`, `self.store.ensure_session`, `self.store.load_token_usage_summary`, `self.store.next_token_usage_request_index`, `self.store.save_token_usage`, `time`, `uuid4`
  - `load_token_usage_summary(self, session_id: str) -> TokenUsageSummary`（L399）；调用：`self.store.load_token_usage_summary`
  - `fork_session(self, source_session_id: str, *, model: str | None = None, messages: list[dict[str, Any]] | None = None) -> str | None`（L402）；调用：`copy.deepcopy`, `last_user_message_index`, `len`, `min`, `self.context_epoch_manager.create`, `self.save_messages_now`, `self.store.ensure_session`, `self.store.load_session`, `self.store.save_file_state_snapshot`, `self.store.save_lrfu_snapshot`, `uuid4`
  - `touch_session(self, session_id: str) -> bool`（L451）；调用：`self.store.touch_session`
  - `delete_session(self, session_id: str) -> bool`（L454）；调用：`self._context_modes.pop`, `self._last_raw_rendered_messages.pop`, `self.context_epoch_manager.delete`, `self.store.delete_session`
  - `delete_sessions(self, session_ids: list[str]) -> int`（L464）；调用：`self.delete_session`
  - `cleanup_expired_sessions(self) -> int`（L471）；调用：`max`, `self.store.delete_expired_sessions`
  - `list_sessions(self, *, limit: int = 20, include_all: bool = False) -> list[SessionListItem]`（L477）；调用：`self.store.list_sessions`
  - `list_migrated_workspace_sessions(self, *, limit: int = 20) -> list[SessionListItem]`（L482）；调用：`self.store.list_sessions`
  - `save_tool_output(self, *, session_id: str, tool_call_id: str, tool_name: str, arguments: str, output: str, metadata: dict[str, Any] | None = None) -> str`（L486）；调用：`ToolOutputRecord`, `ToolOutputRef`, `build_recoverable_context`, `estimate_tokens`, `is_reproducible_tool`, `len`, `self._enqueue_write`, `self.store.save_context`, `self.store.save_tool_output`, `time`
  - `get_tool_output(self, output_id: str) -> ToolOutputRecord | None`（L536）；调用：`self.store.get_tool_output`
  - `get_context_metadata(self, context_id: str) -> RecoverableContextObject | None`（L539）；调用：`self._context_metadata_refs.get`, `self.store.query_metadata`
  - `load_context(self, context_id: str) -> str | None`（L542）；调用：`self.store.load_context`
  - `load_partial_context(self, context_id: str, *, offset: int = 0, limit: int = 12000) -> tuple[str, int | None] | None`（L545）；调用：`self.store.load_partial_context`
  - `search_context_metadata(self, session_id: str, query: str = '', *, limit: int = 20) -> list[RecoverableContextObject]`（L548）；调用：`join`, `lower`, `query.split`, `self._context_metadata_refs.values`, `self.store.search_metadata`
  - `prompt_budget_snapshot(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, current_prompt: str = '', extra_tokens: int = 0) -> PromptBudgetSnapshot`（L573）；调用：`self.budget_manager.snapshot`
  - `tool_output_prompt_content(self, *, output_id: str, output: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, current_prompt: str = '') -> str`（L588）；调用：`estimate_tokens`, `self.context_reference_text`, `self.force_context_virtualized`, `self.get_context_metadata`, `self.is_context_virtualized`, `self.prompt_budget_snapshot`, `self.working_context.add`
  - `context_reference_text(self, context_id: str, *, preview: str = '', snapshot: PromptBudgetSnapshot | None = None) -> str`（L627）；调用：`join`, `lower`, `self._tool_output_refs.get`, `self.get_context_metadata`, `snapshot.to_prompt_text`, `str`
  - `prepare_messages_for_model(self, *, session_id: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], current_prompt: str, summary_text: str = '', persist_snapshot: bool = True, current_turn_start: int | None = None) -> list[dict[str, Any]]`（L669）；调用：`self.render_messages_for_model`
  - `render_messages_for_model(self, *, session_id: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], current_prompt: str, current_turn_start: int | None, summary_text: str = '', persist_snapshot: bool = True) -> list[dict[str, Any]]`（L690）；调用：`automatic_context_epoch_summary`, `build_historical_turns`, `collect_context_epoch_files`, `copy.deepcopy`, `format_hot_context_notice`, `format_virtualization_report`, `insert_budget_notice`, `message.get`, `print`, `render_virtualized_messages`, `sanitize_messages_for_model`, `self._enqueue_write`, `self._select_context_render`, `self.ensure_context_epoch`, `self.hot_context_budget_snapshot`, `self.prompt_budget_snapshot`, `self.request_context_epoch_commit`, `self.store.load_historical_turns`, `self.store.save_context_snapshot`, `split_historical_and_current`, `uuid4`
  - `_select_context_render(self, *, session_id: str, raw_messages: list[dict[str, Any]], virtualized_messages: list[dict[str, Any]], tools: list[dict[str, Any]], current_prompt: str) -> ContextRenderDecision`（L775）；调用：`ContextRenderDecision`, `estimate_raw_uncached_tokens`, `self._last_raw_rendered_messages.get`, `self._should_switch_to_virtualized`, `self.context_mode`, `self.prompt_budget_snapshot`
  - `_should_switch_to_virtualized(self, *, raw_snapshot: PromptBudgetSnapshot, raw_uncached_tokens: int, virtualized_tokens: int) -> bool`（L813）；调用：`int`
  - `summarize_current_turn_message(self, *, message_id: str, summary: str, reason: str, focus: str = '', context_id: str = '') -> ToolInvocationMetadata`（L826）；调用：`ToolInvocationMetadata`, `ValueError`, `estimate_tokens`, `extract_keywords_from_text`, `int`, `json.dumps`, `len`, `previous.get`, `reason.strip`, `self._current_turn_summaries.get`, `stable_hash`, `stable_id`, `str`, `truncate_one_line`
  - `save_lrfu_snapshot(self, session_id: str, skill_runtime: Any | None) -> None`（L885）；调用：`callable`, `copy.deepcopy`, `getattr`, `self._enqueue_write`, `self.store.save_lrfu_snapshot`, `to_dict`
  - `save_file_state_snapshot(self, session_id: str, file_state_cache: Any | None) -> None`（L897）；调用：`callable`, `copy.deepcopy`, `getattr`, `self._enqueue_write`, `self.store.save_file_state_snapshot`, `to_dict`
  - `async on_turn_completed(self, *, messages: list[dict[str, Any]], skill_runtime: Any | None = None, file_state_cache: Any | None = None, workspace_tracker: Any | None = None, system_prompt_source: dict[str, Any] | None = None, tools: list[dict[str, Any]] | None = None, current_prompt: str = '') -> RolloverResult`（L909）；调用：`RolloverResult`, `TurnState`, `asyncio.create_task`, `copy.deepcopy`, `has_pending_tool_call`, `len`, `self._checkpoint_runtime_state`, `self._pending_rollover_task.done`, `self._perform_rollover`, `self._record_writer_error`, `self.checkpoint_manager.should_checkpoint`, `self.drain`, `self.finalize_pending_context_epoch`, `self.get_current_session_id`, `self.prompt_budget_snapshot`, `self.render_messages_for_model`, `self.save_file_state_snapshot`, `self.save_lrfu_snapshot`, `self.save_messages_now`
  - `async _perform_rollover(self, *, session_id: str, messages: list[dict[str, Any]], runtime_state: dict[str, Any], trigger_reason: str, usage_ratio: float, system_prompt_source: dict[str, Any] | None) -> RolloverResult`（L979）；调用：`RolloverResult`, `asyncio.get_running_loop`, `loop.run_in_executor`, `self._record_writer_error`, `self.create_checkpoint`, `self.rollover_to_new_session`
  - `create_checkpoint(self, *, session_id: str, messages: list[dict[str, Any]], runtime_state: dict[str, Any], trigger_reason: str, usage_ratio: float) -> ConversationSnapshot`（L1014）；调用：`self.checkpoint_manager.checkpoint_session`
  - `rollover_to_new_session(self, *, session_id: str, snapshot: ConversationSnapshot, system_prompt_source: dict[str, Any] | None) -> RolloverResult`（L1031）；调用：`self.checkpoint_manager.rollover_session`
  - `restore_historical_session_snapshot(self, session_id: str) -> ConversationSnapshot | None`（L1044）；调用：`self.checkpoint_manager.restore_session_snapshot`
  - `async await_pending_rollover(self) -> RolloverResult`（L1047）；调用：`RolloverResult`, `isinstance`
  - `_checkpoint_runtime_state(self, *, skill_runtime: Any | None, file_state_cache: Any | None, workspace_tracker: Any | None) -> dict[str, Any]`（L1057）；调用：`getattr`, `list`, `self._context_metadata_refs.keys`, `snapshot_dict`
  - `load_lrfu_snapshot(self, session_id: str, skill_runtime: Any | None) -> None`（L1082）；调用：`callable`, `getattr`, `load_dict`, `self.store.load_session`
  - `load_file_state_snapshot(self, session_id: str, file_state_cache: Any | None, workspace_tracker: Any | None = None) -> dict`（L1093）；调用：`callable`, `file_state_paths`, `getattr`, `load_dict`, `mark_paths_for_recheck`, `self.store.load_session`
  - `save_short_term(self, content: str, metadata: dict[str, Any] | None = None) -> MemoryEntry`（L1112）；调用：`MemoryEntry`, `json.dumps`, `messages.append`, `self._enqueue_write`, `self.start_session`, `self.store.load_messages`, `self.store.save_messages`
  - `save_long_term(self, content: str, metadata: dict[str, Any] | None = None) -> MemoryEntry`（L1125）；调用：`MemoryEntry`
  - `recall_short_term(self, query: MemoryQuery | None = None) -> list[MemoryEntry]`（L1128）；调用：无
  - `recall_long_term(self, query: MemoryQuery | None = None) -> list[MemoryEntry]`（L1131）；调用：无
  - `compress_context(self, messages: list[dict[str, Any]]) -> CompressionResult`（L1134）；调用：`self.compressor.compress_messages`
  - `should_compress_context(self, messages: list[dict[str, Any]]) -> bool`（L1137）；调用：`self.compressor.should_compress`
- 函数 `format_compression_report(result: CompressionResult) -> str`（L1141）：执行模块级业务逻辑。；调用：`float`, `int`, `metadata.get`
- 函数 `format_virtualization_report(snapshot: PromptBudgetSnapshot, *, decision: ContextRenderDecision | None = None) -> str`（L1158）：执行模块级业务逻辑。；调用：`join`, `lines.extend`, `lower`, `str`
- 函数 `estimate_raw_uncached_tokens(previous_messages: list[dict[str, Any]] | None, current_messages: list[dict[str, Any]]) -> int`（L1190）：执行模块级业务逻辑。；调用：`enumerate`, `estimate_tokens`, `len`, `min`, `zip`
- 函数 `split_historical_and_current(messages: list[dict[str, Any]], current_turn_start: int | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]`（L1206）：执行模块级业务逻辑。；调用：`get`, `len`, `max`, `min`
- 函数 `insert_budget_notice(messages: list[dict[str, Any]], notice: str) -> list[dict[str, Any]]`（L1218）：执行模块级业务逻辑。；调用：`get`
- 函数 `format_budget_notice(snapshot: PromptBudgetSnapshot) -> str`（L1225）：执行模块级业务逻辑。；调用：`join`, `lines.append`, `lines.extend`
- 函数 `render_virtualized_messages(*, system_messages: list[dict[str, Any]], historical_messages: list[dict[str, Any]], session_id: str, historical_turns: list[HistoricalTurn], current_messages: list[dict[str, Any]], current_summaries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]`（L1245）：执行模块级业务逻辑。；调用：`apply_current_summaries`, `render_historical_topology`, `rendered.extend`
- 函数 `render_historical_topology(session_id: str, messages: list[dict[str, Any]], turns: list[HistoricalTurn]) -> list[dict[str, Any]]`（L1261）：执行模块级业务逻辑。；调用：`build_historical_turns`, `dict`, `get`, `message.get`, `metadata_by_call_id.get`, `render_historical_assistant_message`, `render_historical_tool_message`, `rendered.append`, `str`
- 函数 `render_historical_assistant_message(message: dict[str, Any]) -> dict[str, Any]`（L1289）：执行模块级业务逻辑。；调用：`copy.deepcopy`, `message.get`
- 函数 `render_historical_tool_message(message: dict[str, Any], metadata: ToolInvocationMetadata | None) -> dict[str, Any]`（L1298）：执行模块级业务逻辑。；调用：`historical_tool_content`, `message.get`, `str`
- 函数 `historical_tool_content(metadata: ToolInvocationMetadata | None, message: dict[str, Any]) -> str`（L1311）：执行模块级业务逻辑。；调用：`json.dumps`, `message.get`, `tool_metadata_prompt_dict`
- 函数 `tool_metadata_prompt_dict(metadata: ToolInvocationMetadata) -> dict[str, Any]`（L1338）：执行模块级业务逻辑。；调用：无
- 函数 `apply_current_summaries(messages: list[dict[str, Any]], summaries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]`（L1370）：执行模块级业务逻辑。；调用：`dict`, `isinstance`, `message.get`, `metadata.get`, `replacement.get`, `result.append`, `str`, `summaries.get`
- 函数 `sanitize_messages_for_model(messages: list[dict[str, Any]]) -> list[dict[str, Any]]`（L1404）：执行模块级业务逻辑。；调用：`message.items`
- 函数 `build_historical_turns(session_id: str, messages: list[dict[str, Any]]) -> list[HistoricalTurn]`（L1412）：执行模块级业务逻辑。；调用：`HistoricalTurn`, `build_tool_invocation_metadata`, `current.get`, `enumerate`, `get`, `isinstance`, `len`, `message.get`, `message_content_text`, `pending_calls.get`, `stable_id`, `str`, `tool_call.get`, `tool_metadata.append`, `turns.append`
- 函数 `build_tool_invocation_metadata(*, session_id: str, turn_id: str, turn_index: int, call_index: int, tool_call_id: str, tool_name: str, arguments: str, tool_message: dict[str, Any] | None) -> ToolInvocationMetadata`（L1494）：执行模块级业务逻辑。；调用：`ToolInvocationMetadata`, `bool`, `estimate_tokens`, `extract_keywords_from_text`, `extract_reference_paths`, `extract_related_files_from_text`, `extract_tool_intent`, `get`, `infer_prompt_content_type`, `is_error_text`, `is_reproducible_tool`, `is_skill_related_tool`, `isinstance`, `join`, `len`, `message_content_text`, `metadata_dict.get`, `metadata_dict.items`, `skill_invocation_kind`, `stable_hash`, `stable_id`, `str`, `tool_short_summary`, `truncate_one_line`
- 函数 `message_content_text(message: dict[str, Any]) -> str`（L1545）：执行模块级业务逻辑。；调用：`isinstance`, `json.dumps`, `message.get`
- 函数 `stable_hash(text: str) -> str`（L1552）：执行模块级业务逻辑。；调用：`hashlib.sha256`, `hexdigest`, `text.encode`
- 函数 `stable_id(*parts: str) -> str`（L1556）：执行模块级业务逻辑。；调用：`join`, `stable_hash`
- 函数 `truncate_one_line(text: str, max_chars: int) -> str`（L1560）：执行模块级业务逻辑。；调用：`join`, `len`, `max`, `split`, `str`
- 函数 `parse_arguments_object(arguments: str) -> dict[str, Any]`（L1567）：执行模块级业务逻辑。；调用：`isinstance`, `json.loads`
- 函数 `extract_tool_intent(tool_name: str, arguments: str, metadata: dict[str, Any]) -> str`（L1575）：执行模块级业务逻辑。；调用：`metadata.get`, `parse_arguments_object`, `parsed.get`, `str`, `truncate_one_line`
- 函数 `extract_keywords_from_text(text: str) -> list[str]`（L1589）：执行模块级业务逻辑。；调用：`dedupe_keep_order`, `re.findall`, `word.lower`
- 函数 `extract_related_files_from_text(text: str) -> list[str]`（L1595）：执行模块级业务逻辑。；调用：`dedupe_keep_order`, `re.findall`
- 函数 `extract_reference_paths(arguments: str, content: str) -> list[str]`（L1601）：执行模块级业务逻辑。；调用：`dedupe_keep_order`, `re.findall`
- 函数 `dedupe_keep_order(values: list[str]) -> list[str]`（L1606）：执行模块级业务逻辑。；调用：`result.append`, `seen.add`, `set`, `value.strip`
- 函数 `tool_short_summary(tool_name: str, arguments: str, content: str, context_id: str, *, intent: str = '') -> str`（L1618）：执行模块级业务逻辑。；调用：`is_error_text`, `join`, `len`, `parse_arguments_object`, `parsed.get`, `parts.append`, `str`, `truncate_one_line`
- 函数 `skill_invocation_kind(tool_name: str) -> str`（L1639）：执行模块级业务逻辑。；调用：`tool_name.startswith`
- 函数 `infer_prompt_content_type(content: str) -> str`（L1651）：执行模块级业务逻辑。；调用：`content.lstrip`, `is_error_text`, `json.loads`, `stripped.startswith`
- 函数 `is_error_text(text: str) -> bool`（L1664）：执行模块级业务逻辑。；调用：`text.startswith`
- 函数 `file_state_paths(snapshot: dict) -> list[str]`（L1668）：执行模块级业务逻辑。；调用：`isinstance`, `item.get`, `snapshot.get`
- 函数 `has_pending_tool_call(messages: list[dict[str, Any]]) -> bool`（L1677）：执行模块级业务逻辑。；调用：`bool`, `last_message.get`
- 函数 `snapshot_dict(value: Any | None) -> dict`（L1684）：执行模块级业务逻辑。；调用：`callable`, `getattr`, `isinstance`, `to_dict`

### `mycodingagent/memory/session_switch.py`

- 模块：`mycodingagent.memory.session_switch`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.memory`
- 函数 `has_conversation_content(messages: list[dict]) -> bool`（L8）：执行模块级业务逻辑。；调用：`any`, `bool`, `message.get`
- 函数 `save_current_session_if_needed(*, memory_runtime: MemoryRuntime, messages: list[dict], skill_runtime: Any | None, file_state_cache: Any | None = None) -> str`（L16）：执行模块级业务逻辑。；调用：`has_conversation_content`, `memory_runtime.get_current_session_id`, `memory_runtime.save_file_state_snapshot`, `memory_runtime.save_lrfu_snapshot`, `memory_runtime.save_messages`, `memory_runtime.start_session`

### `mycodingagent/memory/stores.py`

- 模块：`mycodingagent.memory.stores`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.memory.context_objects`, `mycodingagent.memory.models`
- 类 `class SQLiteMemoryStore`（L27）：封装该模块的状态与行为。
  - `__init__(self, db_path: Path | str) -> None`（L28）；调用：`Path`, `expanduser`, `self._init_db`, `self.db_path.parent.mkdir`
  - `_connect(self) -> sqlite3.Connection`（L33）；调用：`sqlite3.connect`
  - `_init_db(self) -> None`（L38）；调用：`conn.execute`, `self._connect`, `self._ensure_column`
  - `_ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None`（L281）；调用：`conn.execute`, `fetchall`
  - `ensure_session(self, *, session_id: str, model: str, status: str = 'active', workspace_root: str = '', workspace_label: str = '', workspace_fingerprint: str = '') -> None`（L286）；调用：`conn.execute`, `self._connect`, `time`
  - `save_messages(self, *, session_id: str, messages: list[dict]) -> None`（L330）；调用：`conn.execute`, `conn.executemany`, `enumerate`, `json.dumps`, `message.get`, `self._connect`, `self._session_status`, `str`, `time`
  - `_session_status(self, conn: sqlite3.Connection, session_id: str) -> str | None`（L357）；调用：`conn.execute`, `fetchone`, `str`
  - `load_messages(self, session_id: str) -> list[dict]`（L361）；调用：`conn.execute`, `fetchall`, `json.loads`, `self._connect`
  - `save_historical_turns(self, *, session_id: str, turns: list[HistoricalTurn]) -> None`（L373）；调用：`conn.execute`, `conn.executemany`, `int`, `json.dumps`, `self._connect`, `self._session_status`, `time`
  - `save_token_usage(self, record: TokenUsageRecord) -> None`（L443）；调用：`conn.execute`, `json.dumps`, `self._connect`, `self._session_status`, `time`
  - `next_token_usage_request_index(self, session_id: str) -> int`（L479）；调用：`conn.execute`, `fetchone`, `int`, `self._connect`
  - `load_token_usage_summary(self, session_id: str) -> TokenUsageSummary`（L487）；调用：`TokenUsageSummary`, `conn.execute`, `fetchone`, `int`, `self._connect`
  - `load_historical_turns(self, session_id: str, *, limit: int | None = None) -> list[HistoricalTurn]`（L514）；调用：`HistoricalTurn`, `append`, `conn.execute`, `fetchall`, `float`, `int`, `max`, `metadata_by_turn.get`, `metadata_by_turn.setdefault`, `params.append`, `self._connect`, `tool_metadata_from_row`, `tuple`
  - `search_historical_turns(self, session_id: str, query: str, *, limit: int = 10) -> list[HistoricalTurn]`（L551）；调用：`haystack_parts.extend`, `join`, `json.dumps`, `len`, `lower`, `matches.append`, `query.split`, `self.load_historical_turns`
  - `list_sessions(self, *, limit: int = 20, workspace_root: str | None = None, workspace_fingerprint: str | None = None) -> list[SessionListItem]`（L577）；调用：`SessionListItem`, `conn.execute`, `fetchall`, `float`, `items.append`, `join`, `len`, `params.append`, `self._connect`, `self.load_messages`, `session_preview`, `tuple`, `where.append`
  - `save_tool_output(self, record: ToolOutputRecord) -> None`（L623）；调用：`conn.execute`, `int`, `self._connect`
  - `save_context(self, context: RecoverableContextObject, content: str) -> str`（L646）；调用：`conn.execute`, `int`, `json.dumps`, `self._connect`
  - `load_context(self, context_id: str) -> str | None`（L684）；调用：`conn.execute`, `fetchone`, `self._connect`, `self._touch_context`
  - `load_partial_context(self, context_id: str, *, offset: int = 0, limit: int = 12000) -> tuple[str, int | None] | None`（L695）；调用：`conn.execute`, `fetchone`, `len`, `max`, `min`, `self._connect`, `self._touch_context`
  - `delete_context(self, context_id: str) -> bool`（L709）；调用：`conn.execute`, `self._connect`
  - `query_metadata(self, context_id: str) -> RecoverableContextObject | None`（L714）；调用：`conn.execute`, `context_from_row`, `fetchone`, `self._connect`
  - `search_metadata(self, session_id: str, query: str = '', *, limit: int = 20) -> list[RecoverableContextObject]`（L722）；调用：`conn.execute`, `context_from_row`, `fetchall`, `join`, `len`, `lower`, `matches.append`, `max`, `query.split`, `self._connect`
  - `_touch_context(self, conn: sqlite3.Connection, context_id: str) -> None`（L754）；调用：`conn.execute`, `time`
  - `get_tool_output(self, output_id: str) -> ToolOutputRecord | None`（L764）；调用：`ToolOutputRecord`, `bool`, `conn.execute`, `fetchone`, `self._connect`
  - `save_context_snapshot(self, *, snapshot_id: str, session_id: str, compressed_messages: list[dict], summary_text: str, pressure_ratio: float) -> None`（L784）；调用：`conn.execute`, `json.dumps`, `self._connect`, `time`
  - `save_context_epoch(self, state: ContextEpochState) -> None`（L815）；调用：`conn.execute`, `json.dumps`, `self._connect`
  - `load_active_context_epoch(self, session_id: str) -> ContextEpochState | None`（L843）；调用：`conn.execute`, `context_epoch_from_row`, `fetchone`, `self._connect`
  - `load_context_epochs(self, session_id: str) -> list[ContextEpochState]`（L860）；调用：`conn.execute`, `context_epoch_from_row`, `fetchall`, `self._connect`
  - `has_committed_context_epoch(self, session_id: str) -> bool`（L872）；调用：`conn.execute`, `fetchone`, `self._connect`
  - `save_lrfu_snapshot(self, *, session_id: str, lrfu: dict) -> None`（L884）；调用：`conn.execute`, `json.dumps`, `self._connect`, `time`
  - `save_file_state_snapshot(self, *, session_id: str, file_state: dict) -> None`（L896）；调用：`conn.execute`, `json.dumps`, `self._connect`, `time`
  - `touch_session(self, session_id: str) -> bool`（L908）；调用：`conn.execute`, `self._connect`, `self._session_status`, `time`
  - `delete_session(self, session_id: str) -> bool`（L931）；调用：`conn.execute`, `self._connect`
  - `delete_expired_sessions(self, *, max_age_seconds: float) -> int`（L948）；调用：`conn.execute`, `fetchall`, `len`, `self._connect`, `time`
  - `load_session(self, session_id: str) -> SessionState | None`（L972）；调用：`SessionState`, `conn.execute`, `fetchone`, `float`, `json.loads`, `self._connect`, `self.load_active_context_epoch`, `self.load_historical_turns`, `self.load_messages`, `self.load_token_usage_summary`
  - `save_conversation_snapshot(self, snapshot: ConversationSnapshot) -> None`（L1006）；调用：`asdict`, `conn.execute`, `json.dumps`, `self._connect`
  - `get_conversation_snapshot(self, snapshot_id: str) -> ConversationSnapshot | None`（L1026）；调用：`conn.execute`, `conversation_snapshot_from_dict`, `fetchone`, `json.loads`, `self._connect`
  - `get_latest_snapshot_for_session(self, session_id: str) -> ConversationSnapshot | None`（L1036）；调用：`conn.execute`, `conversation_snapshot_from_dict`, `fetchone`, `json.loads`, `self._connect`
  - `save_snapshot_delta(self, delta: SnapshotDelta) -> None`（L1051）；调用：`asdict`, `conn.execute`, `json.dumps`, `self._connect`
  - `save_checkpoint_record(self, record: CheckpointRecord) -> None`（L1072）；调用：`conn.execute`, `self._connect`
  - `mark_session_historical(self, session_id: str, snapshot_id: str, summary: str, context_refs: list[str]) -> None`（L1093）；调用：`conn.execute`, `fetchone`, `float`, `json.dumps`, `self._connect`, `time`
  - `get_historical_session(self, session_id: str) -> HistoricalSessionRef | None`（L1134）；调用：`conn.execute`, `fetchone`, `historical_session_from_row`, `self._connect`
  - `list_historical_sessions(self, limit: int = 20) -> list[HistoricalSessionRef]`（L1142）；调用：`conn.execute`, `fetchall`, `historical_session_from_row`, `self._connect`
  - `touch_historical_session(self, session_id: str) -> bool`（L1154）；调用：`conn.execute`, `self._connect`, `time`
- 函数 `session_preview(messages: list[dict], *, max_chars: int = 120) -> str`（L1172）：执行模块级业务逻辑。；调用：`content.strip`, `lower`, `message.get`, `message_content_to_text`, `reversed`, `truncate_one_line`
- 函数 `message_content_to_text(content: object) -> str`（L1187）：执行模块级业务逻辑。；调用：`isinstance`, `json.dumps`
- 函数 `truncate_one_line(text: str, *, max_chars: int) -> str`（L1193）：执行模块级业务逻辑。；调用：`join`, `len`, `split`, `text.strip`
- 函数 `context_from_row(row: sqlite3.Row) -> RecoverableContextObject`（L1200）：执行模块级业务逻辑。；调用：`ContextContentType`, `ContextLifecycleState`, `RecoverableContextObject`, `bool`, `float`, `int`, `json.loads`
- 函数 `tool_metadata_from_row(row: sqlite3.Row) -> ToolInvocationMetadata`（L1224）：执行模块级业务逻辑。；调用：`ToolInvocationMetadata`, `bool`, `float`, `int`, `json.loads`
- 函数 `context_epoch_from_row(row: sqlite3.Row) -> ContextEpochState`（L1253）：执行模块级业务逻辑。；调用：`ContextEpochState`, `ContextEpochStatus`, `float`, `int`, `json.loads`
- 函数 `conversation_snapshot_from_dict(data: dict) -> ConversationSnapshot`（L1271）：执行模块级业务逻辑。；调用：`ConversationSnapshot`, `data.get`, `dict`, `float`, `list`, `str`, `time`
- 函数 `historical_session_from_row(row: sqlite3.Row) -> HistoricalSessionRef`（L1290）：执行模块级业务逻辑。；调用：`HistoricalSessionRef`, `float`, `json.loads`

### `mycodingagent/memory/working_context.py`

- 模块：`mycodingagent.memory.working_context`
- 职责：会话持久化、跨多轮热工作上下文、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.memory.context_objects`
- 类 `class WorkingContext`（L9）：封装该模块的状态与行为。
  - `add(self, context: RecoverableContextObject) -> None`（L12）；调用：无
  - `evict(self, context_id: str) -> RecoverableContextObject | None`（L16）；调用：`self.contexts.pop`
  - `archive(self, context_id: str) -> RecoverableContextObject | None`（L22）；调用：`self.contexts.pop`
  - `metadata(self) -> list[dict]`（L28）；调用：`context.to_dict`, `self.contexts.values`
  - `clear(self) -> None`（L31）；调用：`self.contexts.clear`, `self.contexts.values`

### `mycodingagent/multi_agent/__init__.py`

- 模块：`mycodingagent.multi_agent`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.infrastructure.direct_responder`, `mycodingagent.multi_agent.infrastructure.events`, `mycodingagent.multi_agent.infrastructure.runner`, `mycodingagent.multi_agent.orchestration.controller`, `mycodingagent.multi_agent.orchestration.orchestrator`
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/__init__.py`

- 模块：`mycodingagent.multi_agent.agents`
- 职责：Role-specific multi-agent implementations.
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/auditor/__init__.py`

- 模块：`mycodingagent.multi_agent.agents.auditor`
- 职责：Parallel project inspection and audit result merging.
- 内部依赖：`mycodingagent.multi_agent.agents.auditor.prompts`
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/auditor/prompts.py`

- 模块：`mycodingagent.multi_agent.agents.auditor.prompts`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/executor/__init__.py`

- 模块：`mycodingagent.multi_agent.agents.executor`
- 职责：Scoped source-code execution agents.
- 内部依赖：`mycodingagent.multi_agent.agents.executor.prompts`
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/executor/prompts.py`

- 模块：`mycodingagent.multi_agent.agents.executor.prompts`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/optimizer/__init__.py`

- 模块：`mycodingagent.multi_agent.agents.optimizer`
- 职责：Read-only architecture optimization proposals.
- 内部依赖：`mycodingagent.multi_agent.agents.optimizer.prompts`
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/optimizer/prompts.py`

- 模块：`mycodingagent.multi_agent.agents.optimizer.prompts`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/planner/__init__.py`

- 模块：`mycodingagent.multi_agent.agents.planner`
- 职责：Audit scope, implementation, and repair planning.
- 内部依赖：`mycodingagent.multi_agent.agents.planner.prompts`
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/planner/prompts.py`

- 模块：`mycodingagent.multi_agent.agents.planner.prompts`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/router/__init__.py`

- 模块：`mycodingagent.multi_agent.agents.router`
- 职责：Main request routing and final workflow synthesis.
- 内部依赖：`mycodingagent.multi_agent.agents.router.prompts`
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/router/prompts.py`

- 模块：`mycodingagent.multi_agent.agents.router.prompts`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/validator/__init__.py`

- 模块：`mycodingagent.multi_agent.agents.validator`
- 职责：Read-only implementation verification agents.
- 内部依赖：`mycodingagent.multi_agent.agents.validator.prompts`
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/agents/validator/prompts.py`

- 模块：`mycodingagent.multi_agent.agents.validator.prompts`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/domain/__init__.py`

- 模块：`mycodingagent.multi_agent.domain`
- 职责：Pure multi-agent workflow contracts and data models.
- 内部依赖：`mycodingagent.multi_agent.domain.contracts`, `mycodingagent.multi_agent.domain.models`
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/domain/contracts.py`

- 模块：`mycodingagent.multi_agent.domain.contracts`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.domain.models`
- 类 `class AgentRuntime(Protocol)`（L9）：封装该模块的状态与行为。
  - `async run(self, request: AgentRequest) -> AgentResult`（L10）；调用：无
- 类 `class DirectResponder(Protocol)`（L13）：封装该模块的状态与行为。
  - `async respond(self, prompt: str, messages: list[dict[str, Any]] | None) -> tuple[str, list[dict[str, Any]]]`（L14）；调用：无
- 类 `class RuntimeEventSink(Protocol)`（L21）：封装该模块的状态与行为。
  - `async emit(self, event: RuntimeEvent) -> None`（L22）；调用：无
- 类 `class MultiAgentSettings(Protocol)`（L25）：封装该模块的状态与行为。
- 类 `class ConversationRecorder(Protocol)`（L38）：封装该模块的状态与行为。
  - `start_session(self, model: str) -> str`（L39）；调用：无
  - `save_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None`（L41）；调用：无
- 类 `class RunJournal(Protocol)`（L44）：封装该模块的状态与行为。
  - `save(self, record: dict[str, Any]) -> str`（L45）；调用：无
  - `latest(self) -> dict[str, Any] | None`（L47）；调用：无
  - `get(self, run_id: str) -> dict[str, Any] | None`（L49）；调用：无
- 类 `class ArchitectureApprovalDecision`（L53）：封装该模块的状态与行为。
- 类 `class ArchitectureApprovalPort(Protocol)`（L58）：封装该模块的状态与行为。
  - `async approve(self, proposal: ArchitectureProposal) -> ArchitectureApprovalDecision`（L59）；调用：无

### `mycodingagent/multi_agent/domain/models.py`

- 模块：`mycodingagent.multi_agent.domain.models`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：无
- 类 `class AgentRole(str, Enum)`（L8）：封装该模块的状态与行为。
- 类 `class WorkflowStatus(str, Enum)`（L17）：封装该模块的状态与行为。
- 类 `class WorkflowMode(str, Enum)`（L23）：封装该模块的状态与行为。
- 函数 `_strings(value: Any) -> tuple[str, ...]`（L29）：执行模块级业务逻辑。；调用：`isinstance`, `str`, `strip`, `tuple`
- 类 `class QueryDecision`（L36）：封装该模块的状态与行为。
  - `needs_planning(self) -> bool`（L42）；调用：无
  - `from_mapping(cls, value: dict[str, Any], fallback_query: str) -> QueryDecision`（L46）；调用：`WorkflowMode`, `bool`, `cls`, `lower`, `str`, `strip`, `value.get`
- 类 `class AuditScope`（L62）：封装该模块的状态与行为。
  - `from_mapping(cls, value: dict[str, Any], index: int = 0) -> AuditScope`（L68）；调用：`_strings`, `cls`, `str`, `strip`, `value.get`
- 类 `class FunctionNode`（L77）：封装该模块的状态与行为。
  - `from_mapping(cls, value: dict[str, Any]) -> FunctionNode`（L87）；调用：`_strings`, `cls`, `str`, `strip`, `value.get`
- 类 `class CallEdge`（L100）：封装该模块的状态与行为。
  - `from_mapping(cls, value: dict[str, Any]) -> CallEdge`（L108）；调用：`cls`, `float`, `max`, `min`, `str`, `strip`, `value.get`
- 类 `class ProjectAuditReport`（L123）：封装该模块的状态与行为。
  - `from_mapping(cls, value: dict[str, Any]) -> ProjectAuditReport`（L133）；调用：`CallEdge.from_mapping`, `FunctionNode.from_mapping`, `_strings`, `cls`, `isinstance`, `str`, `strip`, `tuple`, `value.get`
  - `to_dict(self) -> dict[str, Any]`（L153）；调用：`asdict`
- 类 `class ArchitectureProposal`（L158）：封装该模块的状态与行为。
  - `from_mapping(cls, value: dict[str, Any]) -> ArchitectureProposal`（L168）；调用：`_strings`, `bool`, `cls`, `str`, `strip`, `value.get`
  - `to_dict(self) -> dict[str, Any]`（L179）；调用：`asdict`
- 类 `class WorkItem`（L184）：封装该模块的状态与行为。
  - `from_mapping(cls, value: dict[str, Any], index: int = 0) -> WorkItem`（L193）；调用：`_strings`, `cls`, `str`, `strip`, `value.get`
  - `to_dict(self) -> dict[str, Any]`（L203）；调用：`asdict`
- 类 `class VerificationReport`（L208）：封装该模块的状态与行为。
  - `from_mapping(cls, value: dict[str, Any]) -> VerificationReport`（L216）；调用：`_strings`, `bool`, `cls`, `isinstance`, `str`, `strip`, `tuple`, `value.get`
  - `to_dict(self) -> dict[str, Any]`（L226）；调用：`asdict`
- 类 `class AgentRequest`（L231）：封装该模块的状态与行为。
- 类 `class AgentResult`（L243）：封装该模块的状态与行为。
- 类 `class RuntimeEvent`（L251）：封装该模块的状态与行为。
- 类 `class WorkflowResult`（L258）：封装该模块的状态与行为。

### `mycodingagent/multi_agent/infrastructure/__init__.py`

- 模块：`mycodingagent.multi_agent.infrastructure`
- 职责：Model, tool, workspace, persistence, and user-interface adapters.
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/infrastructure/direct_responder.py`

- 模块：`mycodingagent.multi_agent.infrastructure.direct_responder`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.llm_runtime`, `mycodingagent.tool_runtime`
- 类 `class LLMDirectResponder`（L11）：封装该模块的状态与行为。
  - `__init__(self, *, api_client: AsyncOpenAI, registry: ToolRegistry, tools: list[dict[str, Any]], core_tool_schemas: list[dict[str, Any]], skill_runtime: Any = None, workspace_tracker: Any = None, memory_runtime: Any = None, capability_router: Any = None) -> None`（L12）；调用：无
  - `async respond(self, prompt: str, messages: list[dict[str, Any]] | None) -> tuple[str, list[dict[str, Any]]]`（L33）；调用：`agent_client.ask_deepseek`

### `mycodingagent/multi_agent/infrastructure/events.py`

- 模块：`mycodingagent.multi_agent.infrastructure.events`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.domain.contracts`, `mycodingagent.multi_agent.domain.models`
- 类 `class RuntimeEventHook`（L9）：封装该模块的状态与行为。
  - `async emit(self, event: RuntimeEvent) -> None`（L10）；调用：无
- 类 `class CLIRuntimeEventHook(RuntimeEventHook)`（L14）：封装该模块的状态与行为。
  - `async emit(self, event: RuntimeEvent) -> None`（L15）；调用：`event.metadata.items`, `join`, `print`
- 类 `class ArchitectureApprovalHook`（L23）：封装该模块的状态与行为。
  - `async approve(self, proposal: ArchitectureProposal) -> ArchitectureApprovalDecision`（L24）；调用：`ArchitectureApprovalDecision`
- 类 `class CLIArchitectureApprovalHook(ArchitectureApprovalHook)`（L28）：封装该模块的状态与行为。
  - `async approve(self, proposal: ArchitectureProposal) -> ArchitectureApprovalDecision`（L29）；调用：`ArchitectureApprovalDecision`, `input`, `lower`, `print`, `strip`
- 类 `class StaticArchitectureApprovalHook(ArchitectureApprovalHook)`（L51）：封装该模块的状态与行为。
  - `__init__(self, allowed: bool) -> None`（L52）；调用：无
  - `async approve(self, proposal: ArchitectureProposal) -> ArchitectureApprovalDecision`（L55）；调用：`ArchitectureApprovalDecision`
- 类 `class CollectingRuntimeEventHook(RuntimeEventHook)`（L60）：封装该模块的状态与行为。
  - `__init__(self) -> None`（L61）；调用：无
  - `async emit(self, event: RuntimeEvent) -> None`（L64）；调用：`self.events.append`

### `mycodingagent/multi_agent/infrastructure/history_tool.py`

- 模块：`mycodingagent.multi_agent.infrastructure.history_tool`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.domain.contracts`, `mycodingagent.tool_runtime.base`
- 类 `class GetMultiAgentRunParams(BaseModel)`（L11）：封装该模块的状态与行为。
- 类 `class GetMultiAgentRun(Tool)`（L18）：封装该模块的状态与行为。
  - `__init__(self, journal: RunJournal) -> None`（L29）；调用：无
  - `async execute(self, params: GetMultiAgentRunParams) -> ToolResult`（L32）；调用：`ToolResult`, `json.dumps`, `self._journal.get`, `self._journal.latest`

### `mycodingagent/multi_agent/infrastructure/path_locks.py`

- 模块：`mycodingagent.multi_agent.infrastructure.path_locks`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.infrastructure.permissions`
- 类 `class PathLockManager`（L11）：封装该模块的状态与行为。
  - `__init__(self, workspace_root: Path) -> None`（L12）；调用：`asyncio.Lock`, `workspace_root.resolve`
  - `async acquire(self, paths: tuple[str, ...]) -> AsyncIterator[None]`（L18）；调用：`lock.acquire`, `lock.release`, `normalize_workspace_path`, `reversed`, `self._get_locks`, `sorted`, `str`
  - `async _get_locks(self, keys: list[str]) -> list[asyncio.Lock]`（L29）；调用：`asyncio.Lock`, `self._locks.setdefault`

### `mycodingagent/multi_agent/infrastructure/permissions.py`

- 模块：`mycodingagent.multi_agent.infrastructure.permissions`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.tool_runtime`
- 类 `class ToolPermissionError(RuntimeError)`（L11）：封装该模块的状态与行为。
- 类 `class ToolAccessPolicy`（L22）：封装该模块的状态与行为。
  - `schemas(self, registry: ToolRegistry) -> list[dict[str, Any]]`（L28）；调用：`registry.list_tools`, `schemas.append`, `tool.get_schema`
  - `authorize(self, tool_name: str, arguments: dict[str, Any]) -> None`（L43）；调用：`ToolPermissionError`, `arguments.get`, `is_validation_command`, `self._authorize_write_path`, `str`, `strip`
  - `_authorize_write_path(self, raw_path: str) -> None`（L55）；调用：`ToolPermissionError`, `any`, `join`, `normalize_workspace_path`, `str`
- 函数 `normalize_workspace_path(raw_path: str, workspace_root: Path) -> Path`（L67）：执行模块级业务逻辑。；调用：`Path`, `len`, `path.is_absolute`, `path.resolve`, `raw_path.strip`, `text.startswith`, `workspace_root.resolve`
- 函数 `is_validation_command(command: str) -> bool`（L80）：执行模块级业务逻辑。；调用：`Path`, `_allowed_validation_subcommand`, `any`, `len`, `shlex.split`
- 函数 `_allowed_validation_subcommand(executable: str, args: list[str]) -> bool`（L105）：执行模块级业务逻辑。；调用：`any`, `bool`

### `mycodingagent/multi_agent/infrastructure/run_journal.py`

- 模块：`mycodingagent.multi_agent.infrastructure.run_journal`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：无
- 类 `class JsonRunJournal`（L10）：封装该模块的状态与行为。
  - `__init__(self, root: Path) -> None`（L11）；调用：`Lock`
  - `save(self, record: dict[str, Any]) -> str`（L15）；调用：`json.dumps`, `record.get`, `self.root.mkdir`, `str`, `target.write_text`, `uuid4`, `write_text`
  - `latest(self) -> dict[str, Any] | None`（L25）；调用：`marker.exists`, `marker.read_text`, `self.get`, `strip`
  - `get(self, run_id: str) -> dict[str, Any] | None`（L31）；调用：`isinstance`, `json.loads`, `target.exists`, `target.read_text`

### `mycodingagent/multi_agent/infrastructure/runner.py`

- 模块：`mycodingagent.multi_agent.infrastructure.runner`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.llm_runtime`, `mycodingagent.multi_agent.domain.contracts`, `mycodingagent.multi_agent.domain.models`, `mycodingagent.multi_agent.infrastructure.permissions`, `mycodingagent.tool_runtime`
- 类 `class AgentOutputError(ValueError)`（L16）：封装该模块的状态与行为。
- 类 `class AgentRunner`（L20）：封装该模块的状态与行为。
  - `__init__(self, *, api_client: AsyncOpenAI, registry: ToolRegistry, workspace_root: Any, event_sink: RuntimeEventSink | None = None) -> None`（L21）；调用：无
  - `async run(self, request: AgentRequest) -> AgentResult`（L34）；调用：`AgentResult`, `ToolAccessPolicy`, `_parse_arguments`, `agent_client.execute_local_tool`, `agent_client.format_openai_tools`, `agent_client.stream_one_round`, `enumerate`, `messages.append`, `policy.authorize`, `policy.schemas`, `range`, `self._emit`, `tuple`
  - `async _emit(self, phase: str, message: str, **metadata: Any) -> None`（L126）；调用：`RuntimeEvent`, `self.event_sink.emit`
- 函数 `parse_json_object(text: str) -> dict[str, Any]`（L131）：执行模块级业务逻辑。；调用：`AgentOutputError`, `isinstance`, `join`, `json.loads`, `startswith`, `strip`, `text.strip`, `value.find`, `value.rfind`, `value.splitlines`, `value.startswith`
- 函数 `_parse_arguments(raw: str) -> dict[str, Any]`（L156）：执行模块级业务逻辑。；调用：`isinstance`, `json.loads`

### `mycodingagent/multi_agent/infrastructure/workspace_state.py`

- 模块：`mycodingagent.multi_agent.infrastructure.workspace_state`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.infrastructure.permissions`
- 函数 `capture_workspace_state(root: Path) -> dict[str, str]`（L24）：执行模块级业务逻辑。；调用：`any`, `as_posix`, `hashlib.sha256`, `hexdigest`, `path.is_file`, `path.read_bytes`, `path.relative_to`, `resolved_root.rglob`, `root.resolve`
- 函数 `changed_paths(before: dict[str, str], after: dict[str, str]) -> set[str]`（L38）：执行模块级业务逻辑。；调用：`after.get`, `after.keys`, `before.get`, `before.keys`
- 函数 `outside_scopes(paths: set[str], scopes: tuple[str, ...], root: Path) -> set[str]`（L46）：执行模块级业务逻辑。；调用：`any`, `normalize_workspace_path`, `outside.add`, `set`

### `mycodingagent/multi_agent/orchestration/__init__.py`

- 模块：`mycodingagent.multi_agent.orchestration`
- 职责：Multi-agent workflow state machine and scheduling.
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/multi_agent/orchestration/controller.py`

- 模块：`mycodingagent.multi_agent.orchestration.controller`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.domain.contracts`, `mycodingagent.multi_agent.domain.models`
- 类 `class MultiCodingController`（L9）：封装该模块的状态与行为。
  - `__init__(self, orchestrator: Any, config: MultiAgentSettings) -> None`（L10）；调用：无
  - `enable(self) -> None`（L17）；调用：无
  - `disable(self) -> None`（L20）；调用：`RuntimeError`
  - `status_text(self) -> str`（L25）；调用：无
  - `async run(self, prompt: str, messages: list[dict[str, Any]] | None) -> tuple[str, list[dict[str, Any]]]`（L34）；调用：`RuntimeError`, `self.orchestrator.run`

### `mycodingagent/multi_agent/orchestration/orchestrator.py`

- 模块：`mycodingagent.multi_agent.orchestration.orchestrator`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.agents.auditor`, `mycodingagent.multi_agent.agents.executor`, `mycodingagent.multi_agent.agents.optimizer`, `mycodingagent.multi_agent.agents.planner`, `mycodingagent.multi_agent.agents.router`, `mycodingagent.multi_agent.agents.validator`, `mycodingagent.multi_agent.domain.contracts`, `mycodingagent.multi_agent.domain.models`, `mycodingagent.multi_agent.infrastructure.path_locks`, `mycodingagent.multi_agent.infrastructure.permissions`, `mycodingagent.multi_agent.infrastructure.runner`, `mycodingagent.multi_agent.infrastructure.workspace_state`
- 类 `class WorkflowError(RuntimeError)`（L57）：封装该模块的状态与行为。
- 类 `class MultiCodingOrchestrator`（L61）：封装该模块的状态与行为。
  - `__init__(self, *, workspace_root: Path, config: MultiAgentSettings, event_hook: RuntimeEventSink, approval_hook: ArchitectureApprovalPort, runner: AgentRuntime, direct_responder: DirectResponder | None = None, conversation_recorder: ConversationRecorder | None = None, run_journal: RunJournal | None = None, default_model: str = '') -> None`（L62）；调用：`PathLockManager`, `workspace_root.resolve`
  - `async run(self, prompt: str, messages: list[dict[str, Any]] | None) -> tuple[WorkflowResult, list[dict[str, Any]]]`（L86）；调用：`VerificationReport`, `WorkflowError`, `WorkflowResult`, `all_execution_reports.extend`, `all_work_items.extend`, `capture_workspace_state`, `changed.update`, `changed_paths`, `len`, `list`, `print`, `self._architecture_phase`, `self._audit`, `self._decide_query`, `self._emit`, `self._execute_work_items`, `self._plan_work_items`, `self._record_turn`, `self._save_run`, `self._synthesize`, `self._validate`, `self.direct_responder.respond`, `set`, `sorted`, `str`, `time`, `tuple`, `uuid4`
  - `async _decide_query(self, prompt: str) -> QueryDecision`（L304）；调用：`QueryDecision`, `QueryDecision.from_mapping`, `frozenset`, `heuristic_workflow_mode`, `join`, `prompt.split`, `self._agent_json`
  - `async _audit(self, query: str) -> ProjectAuditReport`（L320）；调用：`AuditScope`, `AuditScope.from_mapping`, `ProjectAuditReport.from_mapping`, `_compact_json`, `_json`, `asyncio.Semaphore`, `asyncio.gather`, `enumerate`, `frozenset`, `isinstance`, `len`, `list`, `merge_audit_reports`, `reports.append`, `run_subtask`, `scope_payload.get`, `self._agent_json`, `self._emit`, `split_payload.get`, `str`, `zip`
  - `async _architecture_phase(self, query: str, audit_report: ProjectAuditReport, *, request_approval: bool = True) -> tuple[ArchitectureProposal | None, str]`（L419）；调用：`ArchitectureProposal.from_mapping`, `_compact_json`, `architecture_approval_required`, `audit_report.to_dict`, `bool`, `decision.get`, `self._agent_json`, `self._emit`, `self.approval_hook.approve`, `user_forbids_architecture_change`
  - `async _plan_work_items(self, query: str, audit_report: ProjectAuditReport, proposal: ArchitectureProposal | None, *, architecture_constraint: str, planner_prompt: str, verification: VerificationReport | None = None) -> tuple[WorkItem, ...]`（L464）；调用：`WorkflowError`, `_compact_json`, `audit_report.to_dict`, `ensure_framework_work_item`, `len`, `parse_work_items`, `proposal.to_dict`, `range`, `self._agent_json`, `self._emit`, `str`, `validate_work_items`, `verification.to_dict`
  - `async _execute_work_items(self, *, query: str, audit_report: ProjectAuditReport, proposal: ArchitectureProposal | None, work_items: tuple[WorkItem, ...]) -> tuple[list[dict[str, Any]], set[str]]`（L502）；调用：`WorkflowError`, `asyncio.gather`, `capture_workspace_state`, `changed.update`, `changed_paths`, `completed.add`, `failures.append`, `isinstance`, `join`, `outside_scopes`, `pending.pop`, `pending.values`, `reports.append`, `select_runnable_batch`, `self._emit`, `self._execute_item`, `set`, `sorted`, `tuple`, `zip`
  - `async _execute_item(self, *, query: str, audit_report: ProjectAuditReport, proposal: ArchitectureProposal | None, item: WorkItem) -> dict[str, Any]`（L564）；调用：`AgentRequest`, `WorkflowError`, `_compact_json`, `item.to_dict`, `parse_json_object`, `proposal.to_dict`, `result.text.strip`, `self._model_for`, `self.path_locks.acquire`, `self.runner.run`
  - `async _validate(self, *, query: str, audit_report: ProjectAuditReport, proposal: ArchitectureProposal | None, work_items: tuple[WorkItem, ...], execution_reports: list[dict[str, Any]], changed_files: set[str]) -> VerificationReport`（L597）；调用：`VerificationReport`, `VerificationReport.from_mapping`, `_compact_json`, `item.to_dict`, `len`, `proposal.to_dict`, `self._agent_json`, `self._emit`, `sorted`
  - `async _synthesize(self, *, query: str, status: WorkflowStatus, audit_report: ProjectAuditReport, proposal: ArchitectureProposal | None, work_items: tuple[WorkItem, ...], verification: VerificationReport, repair_rounds: int, changed_files: set[str], execution_reports: list[dict[str, Any]]) -> str`（L641）；调用：`AgentRequest`, `_compact_json`, `frozenset`, `item.to_dict`, `join`, `proposal.to_dict`, `result.text.strip`, `self._model_for`, `self.runner.run`, `sorted`, `verification.to_dict`
  - `async _agent_json(self, *, role: AgentRole, system_prompt: str, user_prompt: str, allowed_tools: frozenset[str], allow_validation_bash: bool = False) -> dict[str, Any]`（L680）；调用：`AgentRequest`, `WorkflowError`, `errors.append`, `join`, `parse_json_object`, `range`, `self._model_for`, `self.runner.run`, `str`
  - `async _emit(self, phase: str, message: str, **metadata: Any) -> None`（L717）；调用：`RuntimeEvent`, `self.event_hook.emit`
  - `_model_for(self, role: AgentRole) -> str`（L720）；调用：无
  - `_record_turn(self, messages: list[dict[str, Any]] | None, prompt: str, response: str) -> list[dict[str, Any]]`（L731）；调用：`list`, `self.conversation_recorder.save_messages`, `self.conversation_recorder.start_session`, `updated.append`
  - `_save_run(self, *, run_id: str, started_at: float, prompt: str, decision: QueryDecision | None, status: WorkflowStatus, response: str, audit_report: ProjectAuditReport | None = None, proposal: ArchitectureProposal | None = None, work_items: tuple[WorkItem, ...] = (), execution_reports: list[dict[str, Any]] | None = None, verification: VerificationReport | None = None, changed_files: set[str] | None = None, errors: tuple[str, ...] = ()) -> None`（L747）；调用：`audit_report.to_dict`, `item.to_dict`, `list`, `proposal.to_dict`, `self.run_journal.save`, `set`, `sorted`, `time`, `verification.to_dict`
- 函数 `parse_work_items(payload: dict[str, Any]) -> tuple[WorkItem, ...]`（L787）：执行模块级业务逻辑。；调用：`WorkItem.from_mapping`, `WorkflowError`, `enumerate`, `isinstance`, `payload.get`, `tuple`
- 函数 `ensure_framework_work_item(items: tuple[WorkItem, ...]) -> tuple[WorkItem, ...]`（L798）：执行模块级业务逻辑。；调用：`WorkItem`, `any`, `path.rstrip`, `tuple`
- 函数 `validate_work_items(items: tuple[WorkItem, ...]) -> None`（L818）：执行模块级业务逻辑。；调用：`WorkflowError`, `any`, `join`, `len`, `set`, `sorted`
- 函数 `select_runnable_batch(items: tuple[WorkItem, ...], completed: set[str], limit: int, workspace_root: Path) -> tuple[WorkItem, ...]`（L839）：执行模块级业务逻辑。；调用：`any`, `issubset`, `len`, `max`, `path_scopes_overlap`, `selected.append`, `set`, `sorted`, `tuple`
- 函数 `path_scopes_overlap(left: tuple[str, ...], right: tuple[str, ...], root: Path) -> bool`（L861）：执行模块级业务逻辑。；调用：`any`, `normalize_workspace_path`
- 函数 `merge_audit_reports(reports: list[dict[str, Any]]) -> dict[str, Any]`（L871）：执行模块级业务逻辑。；调用：`append`, `isinstance`, `join`, `json.dumps`, `report.get`, `seen.add`, `set`, `str`, `strip`
- 函数 `architecture_approval_required(proposal: ArchitectureProposal) -> bool`（L898）：执行模块级业务逻辑。；调用：`bool`
- 函数 `user_forbids_architecture_change(query: str) -> bool`（L907）：执行模块级业务逻辑。；调用：`any`, `join`, `query.lower`, `split`
- 函数 `heuristic_workflow_mode(prompt: str) -> WorkflowMode`（L922）：执行模块级业务逻辑。；调用：`any`, `prompt.lower`
- 函数 `_json(value: Any) -> str`（L969）：执行模块级业务逻辑。；调用：`json.dumps`
- 函数 `_compact_json(value: Any, limit: int = 60000) -> str`（L973）：执行模块级业务逻辑。；调用：`_json`, `len`

### `mycodingagent/relevance/__init__.py`

- 模块：`mycodingagent.relevance`
- 职责：Reusable relevance and usage-ranking primitives.
- 内部依赖：`mycodingagent.relevance.lrfu`
- 定义：无公开类或函数。

### `mycodingagent/relevance/lrfu.py`

- 模块：`mycodingagent.relevance.lrfu`
- 职责：跨模块复用的相关性和使用频率排序算法。
- 内部依赖：无
- 类 `class LRFUEntry`（L7）：封装该模块的状态与行为。
- 类 `class LRFUCandidate`（L14）：封装该模块的状态与行为。
- 类 `class LRFUCache`（L19）：In-memory time-decayed LRFU cache with lazy score updates.
  - `__init__(self, *, decay: float = 0.95, max_entries: int = 200) -> None`（L22）；调用：`max`
  - `touch(self, skill_name: str, *, current_round: int, reward: float = 1.0) -> float`（L27）；调用：`LRFUEntry`, `max`, `self._entries.get`, `self._prune_if_needed`, `self.decayed_score`
  - `get_score(self, skill_name: str, *, current_round: int) -> float`（L42）；调用：`max`, `self._entries.get`, `self.decayed_score`
  - `top_candidates(self, *, limit: int, current_round: int) -> list[LRFUCandidate]`（L55）；调用：`LRFUCandidate`, `candidates.sort`, `list`, `self.get_score`
  - `to_dict(self) -> dict`（L65）；调用：`self._entries.values`
  - `load_dict(self, data: dict) -> None`（L79）；调用：`LRFUEntry`, `data.get`, `float`, `int`, `isinstance`, `item.get`, `max`, `str`, `strip`
  - `decayed_score(score: float, *, last_update_round: int, current_round: int, decay: float) -> float`（L97）；调用：`max`
  - `_prune_if_needed(self, *, current_round: int) -> None`（L109）；调用：`len`, `self._entries.items`, `self.top_candidates`

### `mycodingagent/skill_runtime/__init__.py`

- 模块：`mycodingagent.skill_runtime`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.skill_runtime.runtime`
- 函数 `__getattr__(name: str)`（L6）：执行模块级业务逻辑。；调用：`AttributeError`

### `mycodingagent/skill_runtime/contracts.py`

- 模块：`mycodingagent.skill_runtime.contracts`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：无
- 类 `class SkillService(Protocol)`（L6）：封装该模块的状态与行为。
  - `async search_skill_schemas(self, *, query: str, max_results: int, tool_names: list[str]) -> dict[str, Any]`（L7）；调用：无
  - `async list_skill_tools(self) -> dict[str, Any]`（L15）；调用：无
  - `async get_tool_schema_by_name(self, tool_name: str) -> dict[str, Any]`（L17）；调用：无
  - `async search_skill_references(self, *, query: str, skill_name: str, max_results: int) -> dict[str, Any]`（L19）；调用：无
  - `async get_skill_reference(self, *, skill_name: str, reference_path: str) -> dict[str, Any]`（L27）；调用：无
  - `get_record(self, tool_name: str) -> Any | None`（L34）；调用：无
  - `record_skill_invocation(self, tool_name: str) -> None`（L36）；调用：无
  - `list_references_for_skill(self, tool_name: str) -> list[dict[str, Any]]`（L38）；调用：无
- 类 `class ToolRegistrar(Protocol)`（L41）：封装该模块的状态与行为。
  - `register(self, tool: Any) -> None`（L42）；调用：无

### `mycodingagent/skill_runtime/discovery.py`

- 模块：`mycodingagent.skill_runtime.discovery`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.skill_runtime.models`
- 函数 `discover_skill_records(skills_root: Path | tuple[Path, ...] | list[Path]) -> list[SkillRecord]`（L33）：执行模块级业务逻辑。；调用：`_discover_single_root`, `isinstance`, `list`, `records_by_tool_name.values`
- 函数 `discover_reference_records(records: dict[str, SkillRecord] | list[SkillRecord]) -> list[SkillReferenceRecord]`（L44）：执行模块级业务逻辑。；调用：`_discover_record_references`, `isinstance`, `records.values`, `reference_records.append`, `seen.add`, `set`
- 函数 `_discover_single_root(skills_root: Path) -> list[SkillRecord]`（L57）：执行模块级业务逻辑。；调用：`_iter_skill_files`, `_load_skill_file`, `records.append`, `skills_root.exists`, `sorted`
- 函数 `_discover_record_references(record: SkillRecord) -> list[SkillReferenceRecord]`（L69）：执行模块级业务逻辑。；调用：`SkillReferenceRecord`, `_is_reference_text_file`, `_should_skip`, `as_posix`, `content.encode`, `hashlib.sha256`, `hexdigest`, `path.is_file`, `path.read_text`, `path.relative_to`, `path.resolve`, `references_root.exists`, `references_root.is_dir`, `references_root.rglob`, `result.append`, `sorted`, `time.time`
- 函数 `_iter_skill_files(skills_root: Path) -> list[Path]`（L104）：执行模块级业务逻辑。；调用：`_should_skip`, `path.is_file`, `path.name.endswith`, `skill_files.append`, `skills_root.rglob`
- 函数 `_should_skip(path: Path) -> bool`（L116）：执行模块级业务逻辑。；调用：`any`
- 函数 `_is_reference_text_file(path: Path) -> bool`（L120）：执行模块级业务逻辑。；调用：`path.name.startswith`, `path.suffix.lower`
- 函数 `_load_skill_file(path: Path) -> SkillRecord | None`（L126）：执行模块级业务逻辑。；调用：`_load_json_skill`, `_load_markdown_skill`, `path.name.endswith`, `path.read_text`
- 函数 `_load_json_skill(path: Path, content: str) -> SkillRecord | None`（L137）：执行模块级业务逻辑。；调用：`_first_nonempty_line`, `_make_record`, `data.get`, `isinstance`, `json.loads`, `path.stem.removesuffix`, `str`, `strip`
- 函数 `_load_markdown_skill(path: Path, content: str) -> SkillRecord`（L151）：执行模块级业务逻辑。；调用：`_first_markdown_heading`, `_first_paragraph`, `_frontmatter`, `_make_record`, `frontmatter.get`, `str`, `strip`
- 函数 `_make_record(path: Path, name: str, description: str, content: str, metadata: dict[str, Any]) -> SkillRecord`（L158）：执行模块级业务逻辑。；调用：`SkillRecord`, `content.encode`, `hashlib.sha256`, `hexdigest`, `normalize_tool_name`, `path.resolve`, `time.time`
- 函数 `normalize_tool_name(name: str) -> str`（L172）：执行模块级业务逻辑。；调用：`isalpha`, `lower`, `name.strip`, `normalized.startswith`, `re.sub`, `strip`
- 函数 `_first_markdown_heading(content: str) -> str | None`（L185）：执行模块级业务逻辑。；调用：`content.splitlines`, `line.strip`, `strip`, `stripped.lstrip`, `stripped.startswith`
- 函数 `_frontmatter(content: str) -> dict[str, str]`（L193）：执行模块级业务逻辑。；调用：`content.splitlines`, `key.strip`, `line.strip`, `strip`, `stripped.split`, `stripped.startswith`, `value.strip`
- 函数 `_first_paragraph(content: str) -> str | None`（L210）：执行模块级业务逻辑。；调用：`content.splitlines`, `join`, `line.strip`, `lines.append`, `stripped.startswith`
- 函数 `_first_nonempty_line(content: str) -> str`（L230）：执行模块级业务逻辑。；调用：`content.splitlines`, `line.strip`

### `mycodingagent/skill_runtime/embeddings.py`

- 模块：`mycodingagent.skill_runtime.embeddings`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.configuration`
- 类 `class EmbeddingService(Protocol)`（L19）：封装该模块的状态与行为。
  - `dim(self) -> int`（L21）；调用：无
  - `embed(self, text: str) -> list[float]`（L24）；调用：无
  - `embed_many(self, texts: list[str]) -> list[list[float]]`（L27）；调用：无
  - `embed_query(self, text: str) -> list[float]`（L30）；调用：无
  - `embed_documents(self, texts: list[str]) -> list[list[float]]`（L33）；调用：无
  - `signature(self) -> str`（L36）；调用：无
- 类 `class HashEmbeddingService`（L40）：Deterministic fallback used when local BGE dependencies are unavailable.
  - `__init__(self, dim: int | None = None) -> None`（L43）；调用：无
  - `dim(self) -> int`（L47）；调用：无
  - `embed(self, text: str) -> list[float]`（L50）；调用：`self.embed_many`
  - `embed_many(self, texts: list[str]) -> list[list[float]]`（L53）；调用：`_hash_vector`
  - `embed_query(self, text: str) -> list[float]`（L56）；调用：`self.embed`
  - `embed_documents(self, texts: list[str]) -> list[list[float]]`（L59）；调用：`self.embed_many`
  - `signature(self) -> str`（L62）；调用：无
- 类 `class BgeEmbeddingService`（L66）：封装该模块的状态与行为。
  - `__init__(self, *, model_name: str | None = None, device: str | None = None, batch_size: int | None = None, fallback_to_hash: bool | None = None) -> None`（L67）；调用：`HashEmbeddingService`, `threading.Lock`
  - `dim(self) -> int`（L87）；调用：无
  - `embed(self, text: str) -> list[float]`（L90）；调用：`self.embed_many`
  - `embed_many(self, texts: list[str]) -> list[list[float]]`（L93）；调用：`self._encode_with_model`, `self._fallback.embed_many`, `self._load_model`
  - `embed_query(self, text: str) -> list[float]`（L101）；调用：`self._encode_with_model`, `self._fallback.embed_query`, `self._load_model`
  - `embed_documents(self, texts: list[str]) -> list[list[float]]`（L108）；调用：`self.embed_many`
  - `signature(self) -> str`（L111）；调用：`join`, `str`
  - `_load_model(self)`（L119）；调用：`RuntimeError`, `SentenceTransformer`, `int`, `self._model.get_sentence_embedding_dimension`
  - `_encode_with_model(self, model, texts: list[str]) -> list[list[float]]`（L146）；调用：`_to_float_list`, `model.encode`
- 类 `class BgeHttpEmbeddingService`（L157）：封装该模块的状态与行为。
  - `__init__(self, *, endpoint: str | None = None, model_name: str | None = None, api_key: str | None = None, timeout: float | None = None, dim: int | None = None) -> None`（L158）；调用：无
  - `dim(self) -> int`（L176）；调用：无
  - `embed(self, text: str) -> list[float]`（L179）；调用：`self.embed_many`
  - `embed_many(self, texts: list[str]) -> list[list[float]]`（L182）；调用：`self._request_embeddings`
  - `embed_query(self, text: str) -> list[float]`（L185）；调用：`self._request_embeddings`
  - `embed_documents(self, texts: list[str]) -> list[list[float]]`（L189）；调用：`self.embed_many`
  - `signature(self) -> str`（L192）；调用：`join`, `str`
  - `_request_embeddings(self, texts: list[str]) -> list[list[float]]`（L201）；调用：`RuntimeError`, `_extract_embeddings`, `decode`, `encode`, `json.dumps`, `json.loads`, `len`, `response.read`, `self._headers`, `self._openai_payload`, `self._request_ollama`, `urllib.request.Request`, `urllib.request.urlopen`
  - `_request_ollama(self, texts: list[str]) -> list[list[float]]`（L248）；调用：`RuntimeError`, `_extract_embeddings`, `decode`, `encode`, `json.dumps`, `json.loads`, `len`, `response.read`, `self._headers`, `urllib.request.Request`, `urllib.request.urlopen`
  - `_openai_payload(self, texts: list[str]) -> dict`（L283）；调用：无
  - `_headers(self) -> dict[str, str]`（L289）；调用：无
- 函数 `create_embedding_service() -> EmbeddingService`（L299）：执行模块级业务逻辑。；调用：`BgeEmbeddingService`, `BgeHttpEmbeddingService`, `HashEmbeddingService`, `ValueError`
- 类 `class EmbeddingCache`（L312）：封装该模块的状态与行为。
  - `__init__(self, db_path: Path) -> None`（L313）；调用：`self._init_db`, `self.db_path.parent.mkdir`
  - `_connect(self) -> sqlite3.Connection`（L318）；调用：`sqlite3.connect`
  - `_init_db(self) -> None`（L321）；调用：`conn.execute`, `self._connect`
  - `get(self, *, tool_name: str, text_hash: str, embedding_signature: str) -> list[float] | None`（L335）；调用：`_to_float_list`, `conn.execute`, `fetchone`, `json.loads`, `self._connect`
  - `put(self, *, tool_name: str, text_hash: str, embedding_signature: str, vector: list[float], updated_at: float) -> None`（L352）；调用：`conn.execute`, `json.dumps`, `self._connect`
  - `delete_missing(self, existing_tool_names: set[str]) -> None`（L375）；调用：`conn.execute`, `join`, `self._connect`, `tuple`
  - `delete(self, tool_names: set[str]) -> None`（L386）；调用：`conn.execute`, `join`, `self._connect`, `tuple`
- 函数 `embedding_text_hash(text: str) -> str`（L397）：执行模块级业务逻辑。；调用：`hashlib.sha256`, `hexdigest`, `text.encode`
- 函数 `_extract_embeddings(body) -> list[list[float]]`（L401）：执行模块级业务逻辑。；调用：`RuntimeError`, `_to_float_list`, `body.get`, `isinstance`, `item.get`, `sorted`, `str`
- 函数 `_hash_vector(text: str, dim: int) -> list[float]`（L417）：执行模块级业务逻辑。；调用：`_normalize`, `_tokens`, `digest`, `hashlib.sha256`, `int.from_bytes`, `token.encode`
- 函数 `_tokens(text: str) -> list[str]`（L427）：执行模块级业务逻辑。；调用：`TOKEN_RE.findall`, `token.lower`
- 函数 `_normalize(vector: list[float]) -> list[float]`（L431）：执行模块级业务逻辑。；调用：`math.sqrt`, `sum`
- 函数 `_to_float_list(vector) -> list[float]`（L438）：执行模块级业务逻辑。；调用：`float`, `hasattr`, `vector.tolist`

### `mycodingagent/skill_runtime/index.py`

- 模块：`mycodingagent.skill_runtime.index`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.skill_runtime.models`
- 类 `class SkillSqlStore`（L9）：封装该模块的状态与行为。
  - `__init__(self, db_path: Path) -> None`（L10）；调用：`self._init_db`, `self.db_path.parent.mkdir`
  - `_connect(self) -> sqlite3.Connection`（L15）；调用：`sqlite3.connect`
  - `_init_db(self) -> None`（L18）；调用：`conn.execute`, `self._connect`
  - `load_all(self) -> dict[str, SkillRecord]`（L62）；调用：`Path`, `SkillRecord`, `conn.execute`, `fetchall`, `self._connect`
  - `upsert(self, record: SkillRecord) -> None`（L80）；调用：`conn.execute`, `self._connect`, `str`
  - `delete_missing_sources(self, existing_sources: set[str]) -> int`（L106）；调用：`conn.execute`, `fetchall`, `self._connect`
  - `delete_missing_tool_names(self, existing_tool_names: set[str]) -> int`（L116）；调用：`conn.execute`, `fetchall`, `self._connect`
  - `reject(self, source_path: Path, reason: str, updated_at: float) -> None`（L126）；调用：`conn.execute`, `self._connect`, `str`
  - `load_references(self) -> dict[str, SkillReferenceRecord]`（L139）；调用：`Path`, `SkillReferenceRecord`, `conn.execute`, `fetchall`, `self._connect`
  - `upsert_reference(self, record: SkillReferenceRecord) -> None`（L174）；调用：`conn.execute`, `self._connect`, `str`
  - `delete_missing_references(self, existing_ref_ids: set[str]) -> int`（L206）；调用：`conn.execute`, `fetchall`, `self._connect`
  - `delete_references_for_missing_skills(self, existing_tool_names: set[str]) -> int`（L216）；调用：`conn.execute`, `fetchall`, `self._connect`
  - `get_reference(self, *, skill_tool_name: str, reference_path: str) -> SkillReferenceRecord | None`（L226）；调用：`get`, `self.load_references`
  - `list_references_for_skill(self, skill_tool_name: str) -> list[SkillReferenceRecord]`（L230）；调用：`self.load_references`, `sorted`, `values`

### `mycodingagent/skill_runtime/models.py`

- 模块：`mycodingagent.skill_runtime.models`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：无
- 类 `class ReviewResult`（L9）：封装该模块的状态与行为。
- 类 `class SkillRecord`（L15）：封装该模块的状态与行为。
- 类 `class SkillReferenceRecord`（L27）：封装该模块的状态与行为。
- 类 `class SearchResult`（L40）：封装该模块的状态与行为。
- 类 `class SkillSyncReport`（L49）：封装该模块的状态与行为。
  - `summary(self) -> str`（L61）；调用：`join`, `len`, `parts.append`

### `mycodingagent/skill_runtime/reviewers.py`

- 模块：`mycodingagent.skill_runtime.reviewers`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.skill_runtime.models`
- 函数 `async review_skill_code(source_path: Path, content: str) -> ReviewResult`（L8）：Entry point for future malicious-code review. The real implementation should inspect files, scripts, and executable snippets referenced by a skill. For now it approves by default so the runtime wiring can be developed an；调用：`ReviewResult`
- 函数 `async review_skill_prompt(source_path: Path, content: str) -> ReviewResult`（L18）：Entry point for future prompt-injection and instruction-risk review.；调用：`ReviewResult`

### `mycodingagent/skill_runtime/router.py`

- 模块：`mycodingagent.skill_runtime.router`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.relevance.lrfu`, `mycodingagent.skill_runtime.models`
- 类 `class SkillRouterConfig`（L11）：封装该模块的状态与行为。
- 类 `class _RouterCandidate`（L21）：封装该模块的状态与行为。
  - `from_retrieval(self) -> bool`（L31）；调用：无
- 类 `class SkillRouter`（L35）：Fuse retrieval, session, and user Skill candidates into a bounded TopN.
  - `__init__(self, config: SkillRouterConfig) -> None`（L38）；调用：无
  - `select(self, *, records: dict[str, SkillRecord], retrieval_results: list[SearchResult], user_candidates: list[LRFUCandidate], session_candidates: list[LRFUCandidate], pinned_names: set[str]) -> list[SkillRecord]`（L41）；调用：`_RouterCandidate`, `candidates.setdefault`, `candidates.values`, `list`, `records.get`, `selected.sort`, `self._enforce_retrieval_floor`, `self._merge_lrfu`, `self._merge_retrieval`, `self._score_candidates`, `sorted`
  - `_merge_retrieval(self, candidates: dict[str, _RouterCandidate], *, records: dict[str, SkillRecord], retrieval_results: list[SearchResult]) -> None`（L73）；调用：`_RouterCandidate`, `candidates.setdefault`, `records.get`, `seen.add`, `set`
  - `_merge_lrfu(self, candidates: dict[str, _RouterCandidate], *, records: dict[str, SkillRecord], source: list[LRFUCandidate], source_name: str) -> None`（L95）；调用：`_RouterCandidate`, `candidates.setdefault`, `max`, `records.get`
  - `_score_candidates(self, candidates: list[_RouterCandidate]) -> None`（L115）；调用：无
  - `_enforce_retrieval_floor(self, selected: list[_RouterCandidate], candidates: dict[str, _RouterCandidate]) -> list[_RouterCandidate]`（L125）；调用：`candidates.values`, `ceil`, `len`, `max`, `min`, `selected.append`, `selected.remove`, `selected_by_name.pop`, `sorted`, `sum`
  - `_sort_key(self, candidate: _RouterCandidate) -> tuple[float, int, float, float, str]`（L168）；调用：`int`

### `mycodingagent/skill_runtime/runtime.py`

- 模块：`mycodingagent.skill_runtime.runtime`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.skill_runtime.contracts`, `mycodingagent.skill_runtime.discovery`, `mycodingagent.skill_runtime.embeddings`, `mycodingagent.skill_runtime.index`, `mycodingagent.skill_runtime.models`, `mycodingagent.skill_runtime.reviewers`, `mycodingagent.skill_runtime.router`, `mycodingagent.skill_runtime.session_skill_cache`, `mycodingagent.skill_runtime.user_skill_cache`, `mycodingagent.skill_runtime.vector_store`, `mycodingagent.skill_runtime.watcher`, `mycodingagent.tool_runtime.skill_tools`
- 类 `class SkillRuntime`（L86）：封装该模块的状态与行为。
  - `__init__(self, *, skills_root: Path | None = None, skill_roots: tuple[Path, ...] | list[Path] | None = None, registry: ToolRegistrar) -> None`（L87）；调用：`EmbeddingCache`, `GetAllTool`, `GetSkillReferenceTool`, `GetToolByNameTool`, `MultiSkillDirectoryWatcher`, `SearchSkillReferencesTool`, `SearchSkillTool`, `SessionSkillCache`, `SkillRouter`, `SkillRouterConfig`, `SkillSqlStore`, `UserSkillCache`, `create_embedding_service`, `create_vector_store`, `int`, `normalize_tool_name`, `self.store.load_all`, `self.store.load_references`, `self.user_skill_cache.start_session`, `set`, `time.time`, `tuple`, `uuid4`
  - `async initialize(self) -> SkillSyncReport`（L148）；调用：`self._ensure_vector_index_complete`, `self._watcher.start`, `self.ensure_synced`, `self.registry.register`
  - `search_records_for_capability(self, query: str, *, top_k: int) -> list[SearchResult]`（L159）；调用：`self._search_records`
  - `close(self) -> None`（L162）；调用：`self._watcher.stop`, `self.user_skill_cache.commit_session`
  - `async ensure_synced(self) -> SkillSyncReport`（L168）；调用：`SkillSyncReport`, `self._watcher.consume_dirty`, `self.sync`
  - `_ensure_vector_index_complete(self, report: SkillSyncReport | None = None) -> None`（L173）；调用：`_progress_bar`, `getattr`, `len`, `max`, `print`, `range`, `self._upsert_vector_batch_with_retry`, `self.vector_store.stale_records`
  - `_upsert_vector_batch_with_retry(self, batch: list[SkillRecord], *, batch_label: str) -> tuple[bool, Exception | None]`（L226）；调用：`max`, `min`, `print`, `range`, `self.vector_store.upsert`, `time.sleep`
  - `async sync(self) -> SkillSyncReport`（L246）；调用：`SkillSyncReport`, `any`, `changed_records.append`, `current_records.values`, `discover_skill_records`, `getattr`, `list`, `report.rejected.append`, `self._activate_default_skill_tools`, `self._register_available_skill_tools`, `self._review`, `self._sync_references`, `self.embedding_cache.delete_missing`, `self.store.delete_missing_sources`, `self.store.delete_missing_tool_names`, `self.store.load_all`, `self.store.load_references`, `self.store.reject`, `self.store.upsert`, `self.vector_store.delete_missing`, `self.vector_store.upsert`, `stored.get`, `str`, `time.time`
  - `get_record(self, tool_name: str) -> SkillRecord | None`（L314）；调用：`self.records.get`
  - `list_references_for_skill(self, tool_name: str) -> list[dict[str, Any]]`（L317）；调用：`self.references.values`, `sorted`, `str`
  - `build_tools_for_prompt(self, prompt: str, core_tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]`（L333）；调用：`_dedupe_schemas`, `_format_recall_names`, `print`, `self._search_records`, `self._skill_management_schemas`, `self.router.select`, `self.session_skill_cache.top_candidates`, `self.user_skill_cache.top_candidates`, `set`, `skill_schema_from_record`
  - `async build_tools_for_prompt_async(self, prompt: str, core_tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]`（L367）；调用：`self.build_tools_for_prompt`, `self.ensure_synced`
  - `async search_skill_schemas(self, *, query: str, max_results: int, tool_names: list[str] | None = None) -> dict[str, Any]`（L375）；调用：`len`, `max`, `min`, `result.metadata.get`, `round`, `self._pin_skill`, `self._search_records`, `self.ensure_synced`, `skill_schema_from_record`, `str`, `zip`
  - `async list_skill_tools(self) -> dict[str, Any]`（L402）；调用：`len`, `self._source_kind`, `self.ensure_synced`, `self.records.values`, `sorted`, `str`
  - `async get_tool_schema_by_name(self, tool_name: str) -> dict[str, Any]`（L419）；调用：`len`, `record.name.lower`, `record.tool_name.lower`, `self._pin_skill`, `self._source_kind`, `self.ensure_synced`, `self.records.get`, `self.records.values`, `self.session_skill_cache.touch`, `skill_schema_from_record`, `str`, `tool_name.lower`
  - `async search_skill_references(self, *, query: str = '', skill_name: str = '', max_results: int = 5) -> dict[str, Any]`（L449）；调用：`_rank_references`, `_reference_snippet`, `len`, `max`, `min`, `query.strip`, `round`, `self._resolve_skill_tool_name`, `self.ensure_synced`, `self.references.values`, `sorted`, `str`
  - `async get_skill_reference(self, *, skill_name: str, reference_path: str) -> dict[str, Any]`（L502）；调用：`_normalize_reference_path`, `self._resolve_skill_tool_name`, `self.ensure_synced`, `self.references.get`, `str`
  - `system_hint(self) -> str`（L532）；调用：无
  - `default_skill_hint(self) -> str`（L535）；调用：`join`, `parts.append`, `self._source_kind`
  - `_skill_management_schemas(self) -> list[dict[str, Any]]`（L556）；调用：`self.get_all_tool_instance.get_schema`, `self.get_reference_tool_instance.get_schema`, `self.get_tool_by_name_instance.get_schema`, `self.search_references_tool_instance.get_schema`, `self.search_tool_instance.get_schema`
  - `_register_available_skill_tools(self) -> None`（L565）；调用：`SkillTool`, `self._registered_skill_tools.add`, `self.registry.register`
  - `_activate_default_skill_tools(self) -> None`（L572）；调用：`self._pin_skill`
  - `begin_turn(self) -> None`（L576）；调用：`self._turn_pinned_tool_names.clear`
  - `end_turn(self) -> None`（L579）；调用：`self._turn_pinned_tool_names.clear`
  - `_pin_skill(self, tool_name: str, *, scope: str = 'turn') -> None`（L582）；调用：`iter`, `len`, `max`, `next`, `pinned.pop`
  - `record_skill_invocation(self, tool_name: str) -> None`（L592）；调用：`self._pin_skill`, `self.session_skill_cache.touch`, `self.user_skill_cache.record_skill_call`
  - `_search_records(self, query: str, *, top_k: int, preferred_names: list[str] | None = None) -> list[SearchResult]`（L609）；调用：`_local_keyword_search`, `_merge_search_results`, `self.vector_store.search`
  - `_source_kind(self, source_path: Path) -> str`（L633）；调用：`_is_relative_to`, `root.resolve`, `self._builtin_root.resolve`, `self.skills_root.resolve`, `source_path.resolve`
  - `_sync_references(self, current_records: dict[str, SkillRecord]) -> tuple[int, int, int]`（L646）；调用：`discover_reference_records`, `previous.get`, `self.store.delete_missing_references`, `self.store.delete_references_for_missing_skills`, `self.store.load_references`, `self.store.upsert_reference`, `set`, `str`
  - `_resolve_skill_tool_name(self, name: str) -> str`（L669）；调用：`candidate.lower`, `len`, `name.strip`, `normalize_tool_name`, `record.name.lower`, `record.tool_name.lower`, `self.records.values`
  - `async _review(self, record: SkillRecord) -> str`（L689）；调用：`review_skill_code`, `review_skill_prompt`
- 函数 `_dedupe_schemas(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]`（L699）：执行模块级业务逻辑。；调用：`result.append`, `schema.get`, `seen.add`, `set`
- 函数 `_format_recall_names(names: Any) -> str`（L711）：执行模块级业务逻辑。；调用：`join`, `str`
- 函数 `_progress_bar(done: int, total: int, *, width: int = 24) -> str`（L716）：执行模块级业务逻辑。；调用：`int`, `max`, `min`, `round`
- 函数 `_merge_search_results(*, primary: list[SearchResult], fallback: list[SearchResult], top_k: int) -> list[SearchResult]`（L724）：执行模块级业务逻辑。；调用：`max`, `merged.get`, `merged.values`, `sorted`
- 函数 `_local_keyword_search(query: str, *, records: dict[str, SkillRecord], top_k: int, preferred_names: list[str] | None = None) -> list[SearchResult]`（L744）：执行模块级业务逻辑。；调用：`SearchResult`, `_local_keyword_score`, `_tokenize_for_local_search`, `any`, `name.lower`, `record.name.lower`, `record.tool_name.lower`, `records.values`, `results.append`, `sorted`
- 函数 `_local_keyword_score(query_tokens: list[str], record: SkillRecord) -> float`（L778）：执行模块级业务逻辑。；调用：`join`, `lower`, `record.content.lower`, `record.description.lower`, `record.name.lower`, `record.tool_name.lower`
- 函数 `_tokenize_for_local_search(query: str) -> list[str]`（L796）：执行模块级业务逻辑。；调用：`TOKEN_RE.findall`, `dict.fromkeys`, `list`, `query.lower`, `strip`, `token.strip`, `tokens.append`
- 函数 `_is_relative_to(path: Path, root: Path) -> bool`（L804）：执行模块级业务逻辑。；调用：`path.relative_to`
- 函数 `_normalize_reference_path(reference_path: str) -> str | None`（L812）：执行模块级业务逻辑。；调用：`any`, `join`, `lstrip`, `normalized.split`, `parts.insert`, `reference_path.strip`, `replace`
- 函数 `_rank_references(*, query: str, references: list[SkillReferenceRecord], skill_tool_name: str, limit: int) -> list[tuple[SkillReferenceRecord, float]]`（L826）：执行模块级业务逻辑。；调用：`_overlap`, `_tokens`, `join`, `scored.append`, `scored.sort`
- 函数 `_tokens(text: str) -> set[str]`（L859）：执行模块级业务逻辑。；调用：`TOKEN_RE.findall`, `token.lower`
- 函数 `_overlap(left: set[str], right: set[str]) -> float`（L863）：执行模块级业务逻辑。；调用：`len`
- 函数 `_reference_snippet(content: str, query: str, limit: int = 240) -> str`（L869）：执行模块级业务逻辑。；调用：`_tokens`, `compact.lower`, `content.split`, `join`, `len`, `lower.find`, `max`, `sorted`, `token.lower`

### `mycodingagent/skill_runtime/session_skill_cache.py`

- 模块：`mycodingagent.skill_runtime.session_skill_cache`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.relevance.lrfu`
- 类 `class SessionSkillCache`（L6）：Session-scoped LRFU cache used for immediate in-conversation routing.
  - `__init__(self, *, decay: float = 0.95, max_entries: int = 200) -> None`（L9）；调用：`LRFUCache`
  - `touch(self, skill_name: str, *, current_round: int, reward: float = 1.0) -> float`（L12）；调用：`self._cache.touch`
  - `top_candidates(self, *, limit: int, current_round: int) -> list[LRFUCandidate]`（L15）；调用：`self._cache.top_candidates`
  - `to_dict(self) -> dict`（L18）；调用：`self._cache.to_dict`
  - `load_dict(self, data: dict) -> None`（L21）；调用：`self._cache.load_dict`

### `mycodingagent/skill_runtime/user_skill_cache.py`

- 模块：`mycodingagent.skill_runtime.user_skill_cache`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.relevance.lrfu`
- 类 `class UserSkillCache`（L10）：Persistent user LRFU cache with deferred session commits. The main user table is updated only at graceful session end or during startup recovery. Individual skill invocations are persisted to pending session rows so an i
  - `__init__(self, db_path: Path, *, decay: float = 0.95, reward: float = 1.0, max_entries: int = 1000) -> None`（L18）；调用：`max`, `self._init_db`, `self.db_path.parent.mkdir`
  - `start_session(self, *, user_id: str, session_id: str) -> None`（L33）；调用：`conn.execute`, `self._connect`, `self.get_user_skill_call_round`, `self.recover_uncommitted`, `time.time`
  - `get_user_skill_call_round(self, *, user_id: str) -> int`（L49）；调用：`self._connect`, `self._get_user_skill_call_round`
  - `record_skill_call(self, *, user_id: str, session_id: str, skill_name: str, session_skill_call_round: int) -> None`（L53）；调用：`LRFUCache.decayed_score`, `conn.execute`, `fetchone`, `float`, `int`, `self._connect`, `self._get_user_skill_call_round`, `time.time`
  - `commit_session(self, *, user_id: str, session_id: str) -> None`（L144）；调用：`self._commit_session`, `self._connect`
  - `recover_uncommitted(self, *, user_id: str) -> None`（L148）；调用：`conn.execute`, `fetchall`, `self._commit_session`, `self._connect`, `str`
  - `top_candidates(self, *, user_id: str, limit: int) -> list[LRFUCandidate]`（L162）；调用：`LRFUCache.decayed_score`, `LRFUCandidate`, `candidates.append`, `candidates.sort`, `conn.execute`, `fetchall`, `float`, `int`, `max`, `rows_by_name.values`, `self._connect`, `self.get_user_skill_call_round`, `str`
  - `_commit_session(self, conn: sqlite3.Connection, *, user_id: str, session_id: str) -> None`（L214）；调用：`LRFUCache.decayed_score`, `conn.execute`, `fetchall`, `fetchone`, `float`, `int`, `max`, `self._get_user_skill_call_round`, `self._mark_session_committed`, `self._prune`, `time.time`
  - `_mark_session_committed(self, conn: sqlite3.Connection, *, user_id: str, session_id: str, updated_at: float) -> None`（L291）；调用：`conn.execute`
  - `_prune(self, conn: sqlite3.Connection, *, user_id: str) -> None`（L316）；调用：`conn.execute`, `conn.executemany`, `fetchall`, `str`
  - `_connect(self) -> sqlite3.Connection`（L334）；调用：`sqlite3.connect`
  - `_get_user_skill_call_round(self, conn: sqlite3.Connection, *, user_id: str) -> int`（L337）；调用：`conn.execute`, `fetchone`, `int`
  - `_init_db(self) -> None`（L350）；调用：`conn.execute`, `self._connect`

### `mycodingagent/skill_runtime/vector_store.py`

- 模块：`mycodingagent.skill_runtime.vector_store`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.skill_runtime.embeddings`, `mycodingagent.skill_runtime.models`
- 类 `class SkillVectorStore`（L22）：封装该模块的状态与行为。
  - `upsert(self, records: list[SkillRecord]) -> None`（L26）；调用：无
  - `delete_missing(self, existing_tool_names: set[str]) -> None`（L29）；调用：无
  - `stale_records(self, records: dict[str, SkillRecord]) -> list[SkillRecord]`（L32）；调用：无
  - `search(self, query: str, *, records: dict[str, SkillRecord], top_k: int, preferred_names: list[str] | None = None) -> list[SearchResult] | None`（L35）；调用：无
- 类 `class MilvusVectorStore(SkillVectorStore)`（L46）：Milvus-backed hybrid retrieval for SKILL search. Dense semantic search uses HNSW. Keyword search uses Milvus BM25 over the indexed text field. Indexes are created with the collection; subsequent upserts let Milvus mainta
  - `__init__(self, embedding_service: EmbeddingService, embedding_cache: EmbeddingCache | None = None) -> None`（L58）；调用：`embedding_service.signature`, `self._connect`, `self._detect_dim`
  - `upsert(self, records: list[SkillRecord]) -> None`（L69）；调用：`_search_text`, `_truncate_text`, `float`, `self._client.upsert`, `self._ensure_ready`, `self._flush`, `self._vectors_for_records`, `str`, `zip`
  - `delete_missing(self, existing_tool_names: set[str]) -> None`（L92）；调用：`_quoted_list`, `self._client.delete`, `self._ensure_ready`, `self._flush`
  - `stale_records(self, records: dict[str, SkillRecord]) -> list[SkillRecord]`（L101）；调用：`indexed_hashes.get`, `len`, `list`, `max`, `records.items`, `records.values`, `row.get`, `self._client.query`, `self._ensure_ready`, `str`
  - `search(self, query: str, *, records: dict[str, SkillRecord], top_k: int, preferred_names: list[str] | None = None) -> list[SearchResult] | None`（L127）；调用：`_boost_preferred`, `query.strip`, `self._ensure_ready`, `self._hybrid_search`
  - `_connect(self) -> None`（L143）；调用：`MilvusClient`, `RuntimeError`, `self._client.drop_collection`, `self._client.has_collection`, `self._client.load_collection`, `self._create_collection`, `self._schema_is_compatible`
  - `_create_collection(self, DataType, Function, FunctionType) -> None`（L178）；调用：`Function`, `index_params.add_index`, `schema.add_field`, `schema.add_function`, `self._client.create_collection`, `self._client.create_schema`, `self._client.prepare_index_params`
  - `_schema_is_compatible(self) -> bool`（L237）；调用：`dense_field.get`, `dense_params.get`, `description.get`, `field.get`, `int`, `next`, `self._client.describe_collection`
  - `_hybrid_search(self, query: str, *, records: dict[str, SkillRecord], top_k: int) -> list[SearchResult]`（L266）；调用：`AnnSearchRequest`, `SearchResult`, `_hit_entity`, `_hit_id`, `_hit_score`, `_record_from_entity`, `_rrf_ranker`, `entity.get`, `float`, `max`, `records.get`, `results.append`, `self._client.hybrid_search`, `self._ensure_ready`, `self.embedding_service.embed_query`, `str`
  - `_detect_dim(self) -> int`（L330）；调用：`embedding_text_hash`, `len`, `self.embedding_cache.get`, `self.embedding_cache.put`, `self.embedding_service.embed_documents`
  - `_vectors_for_records(self, records: list[SkillRecord]) -> list[list[float]]`（L357）；调用：`_semantic_document`, `embedding_text_hash`, `len`, `missed_hashes.append`, `missed_records.append`, `missed_texts.append`, `self.embedding_cache.get`, `self.embedding_cache.put`, `self.embedding_service.embed_documents`, `zip`
  - `_ensure_ready(self) -> None`（L401）；调用：`RuntimeError`
  - `_flush(self) -> None`（L408）；调用：`self._client.flush`
- 函数 `create_vector_store(embedding_service: EmbeddingService, embedding_cache: EmbeddingCache | None = None) -> SkillVectorStore`（L419）：执行模块级业务逻辑。；调用：`MilvusVectorStore`, `RuntimeError`
- 函数 `_record_from_entity(entity: dict[str, Any], tool_name: str) -> SkillRecord | None`（L428）：执行模块级业务逻辑。；调用：`Path`, `SkillRecord`, `entity.get`, `float`, `str`
- 函数 `_hit_entity(hit: Any) -> dict[str, Any]`（L442）：执行模块级业务逻辑。；调用：`entity.get`, `entity.to_dict`, `getattr`, `hasattr`, `hit.get`, `isinstance`
- 函数 `_hit_id(hit: Any) -> Any`（L474）：执行模块级业务逻辑。；调用：`getattr`, `hit.get`, `isinstance`
- 函数 `_hit_score(hit: Any) -> float`（L480）：执行模块级业务逻辑。；调用：`getattr`, `hit.get`, `isinstance`
- 函数 `_rrf_ranker() -> Any`（L486）：执行模块级业务逻辑。；调用：`RRFRanker`
- 函数 `_boost_preferred(results: list[SearchResult], preferred_names: list[str]) -> list[SearchResult]`（L495）：执行模块级业务逻辑。；调用：`any`, `name.lower`, `result.record.name.lower`, `result.record.tool_name.lower`, `results.sort`
- 函数 `_quoted_list(values: set[str]) -> str`（L507）：执行模块级业务逻辑。；调用：`join`, `sorted`
- 函数 `_semantic_document(record: SkillRecord) -> str`（L511）：执行模块级业务逻辑。；调用：`join`
- 函数 `_search_text(record: SkillRecord) -> str`（L515）：执行模块级业务逻辑。；调用：`join`
- 函数 `_truncate_text(text: str, max_bytes: int) -> str`（L519）：执行模块级业务逻辑。；调用：`decode`, `len`, `text.encode`

### `mycodingagent/skill_runtime/watcher.py`

- 模块：`mycodingagent.skill_runtime.watcher`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.configuration`
- 类 `class SkillDirectoryWatcher`（L44）：封装该模块的状态与行为。
  - `__init__(self, root: Path) -> None`（L45）；调用：`Event`, `Lock`
  - `start(self) -> None`（L53）；调用：`Thread`, `_create_backend`, `self._thread.start`, `self.root.mkdir`
  - `stop(self) -> None`（L61）；调用：`self._backend.close`, `self._stop_event.set`, `self._thread.join`
  - `mark_dirty(self) -> None`（L68）；调用：无
  - `consume_dirty(self) -> bool`（L72）；调用：无
  - `async wait_for_change(self, timeout: float | None = None) -> bool`（L78）；调用：`asyncio.get_running_loop`, `asyncio.sleep`, `min`, `self.consume_dirty`, `time`
  - `_run(self) -> None`（L91）；调用：`self._backend.poll`, `self._stop_event.is_set`, `self.mark_dirty`
- 类 `class MultiSkillDirectoryWatcher`（L100）：封装该模块的状态与行为。
  - `__init__(self, roots: tuple[Path, ...] | list[Path]) -> None`（L101）；调用：`SkillDirectoryWatcher`
  - `start(self) -> None`（L104）；调用：`watcher.start`
  - `stop(self) -> None`（L108）；调用：`watcher.stop`
  - `consume_dirty(self) -> bool`（L112）；调用：`any`, `watcher.consume_dirty`
  - `async wait_for_change(self, timeout: float | None = None) -> bool`（L115）；调用：`asyncio.get_running_loop`, `asyncio.sleep`, `min`, `self.consume_dirty`, `time`
- 类 `class _WatcherBackend`（L129）：封装该模块的状态与行为。
  - `poll(self, stop_event: Event) -> bool`（L130）；调用：无
  - `close(self) -> None`（L133）；调用：无
- 类 `class _InotifyBackend(_WatcherBackend)`（L137）：封装该模块的状态与行为。
  - `__init__(self, root: Path) -> None`（L138）；调用：`OSError`, `ctypes.CDLL`, `ctypes.get_errno`, `os.strerror`, `self._add_tree`, `self._libc.inotify_init1`
  - `poll(self, stop_event: Event) -> bool`（L147）；调用：`os.read`, `select.select`, `self._consume_events`, `stop_event.is_set`
  - `close(self) -> None`（L163）；调用：`os.close`
  - `_consume_events(self, data: bytes) -> bool`（L169）；调用：`EVENT_STRUCT.unpack_from`, `len`, `raw_name.decode`, `rstrip`, `self._add_tree`, `self._watch_descriptors.get`, `self._watch_descriptors.pop`
  - `_add_tree(self, root: Path) -> None`（L190）；调用：`_iter_directories`, `self._add_watch`
  - `_add_watch(self, directory: Path) -> None`（L194）；调用：`os.fsencode`, `self._libc.inotify_add_watch`, `str`
- 类 `class _PollingBackend(_WatcherBackend)`（L202）：封装该模块的状态与行为。
  - `__init__(self, root: Path) -> None`（L203）；调用：`_snapshot`
  - `poll(self, stop_event: Event) -> bool`（L207）；调用：`_snapshot`, `stop_event.wait`
- 函数 `_create_backend(root: Path) -> _WatcherBackend`（L216）：执行模块级业务逻辑。；调用：`_InotifyBackend`, `_PollingBackend`
- 函数 `_iter_directories(root: Path) -> list[Path]`（L223）：执行模块级业务逻辑。；调用：`_should_skip`, `directories.append`, `path.is_dir`, `root.exists`, `root.rglob`
- 函数 `_snapshot(root: Path) -> dict[str, tuple[int, int]]`（L233）：执行模块级业务逻辑。；调用：`_should_skip`, `path.stat`, `root.exists`, `root.rglob`, `str`
- 函数 `_should_skip(path: Path) -> bool`（L248）：执行模块级业务逻辑。；调用：`any`

### `mycodingagent/terminal_ui/__init__.py`

- 模块：`mycodingagent.terminal_ui`
- 职责：Terminal input, rendering, history, selection, and confirmation.
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/terminal_ui/confirm.py`

- 模块：`mycodingagent.terminal_ui.confirm`
- 职责：终端输入、历史展示、会话选择与确认交互。
- 内部依赖：`mycodingagent.memory`, `mycodingagent.terminal_ui.session_selector`
- 函数 `confirm_cross_workspace_restore(source_workspace: str, current_workspace: str) -> bool`（L7）：执行模块级业务逻辑。；调用：`confirm_cross_workspace_action`
- 函数 `confirm_delete_sessions(sessions: list[SessionListItem], *, include_all: bool) -> bool`（L11）：执行模块级业务逻辑。；调用：`input`, `len`, `lower`, `print`, `print_session_options`, `strip`
- 函数 `confirm_cross_workspace_action(action: str, source_workspace: str, current_workspace: str) -> bool`（L21）：执行模块级业务逻辑。；调用：`input`, `lower`, `print`, `strip`

### `mycodingagent/terminal_ui/history.py`

- 模块：`mycodingagent.terminal_ui.history`
- 职责：终端输入、历史展示、会话选择与确认交互。
- 内部依赖：无
- 函数 `render_conversation_history(messages: list[dict], *, max_chars_per_message: int = 2000) -> None`（L6）：执行模块级业务逻辑。；调用：`format_history_message`, `join`, `print`
- 函数 `format_history_message(message: dict, *, max_chars_per_message: int = 2000) -> str`（L20）：执行模块级业务逻辑。；调用：`call.get`, `get`, `join`, `message.get`, `message_content_to_text`, `truncate_history_text`
- 函数 `message_content_to_text(content: object) -> str`（L44）：执行模块级业务逻辑。；调用：`isinstance`, `json.dumps`
- 函数 `truncate_history_text(text: str, max_chars: int) -> str`（L50）：执行模块级业务逻辑。；调用：`len`

### `mycodingagent/terminal_ui/input.py`

- 模块：`mycodingagent.terminal_ui.input`
- 职责：终端输入、历史展示、会话选择与确认交互。
- 内部依赖：`mycodingagent.commands`
- 函数 `read_user_prompt(prompt: str, command_registry: CommandRegistry | None = None) -> str`（L27）：执行模块级业务逻辑。；调用：`InteractivePrompt`, `input`, `reader.read`, `sys.stdin.isatty`
- 类 `class InteractivePrompt`（L34）：封装该模块的状态与行为。
  - `__init__(self, *, prompt: str, command_registry: CommandRegistry | None) -> None`（L35）；调用：`codecs.getincrementaldecoder`, `strip_readline_markers`, `visible_width`
  - `read(self) -> str`（L47）；调用：`char.isprintable`, `self._decoder.reset`, `self._finish`, `self._handle_escape_sequence`, `self._read_char`, `self._render`, `self.accept_selected_suggestion`, `sys.stdin.fileno`, `termios.tcgetattr`, `termios.tcsetattr`, `tty.setraw`
  - `_finish(self) -> str`（L82）；调用：`self._clear_render`, `sys.stdout.flush`, `sys.stdout.write`
  - `_suggestions(self) -> list[CommandSpec]`（L89）；调用：`self.command_registry.suggestions`
  - `_render(self) -> None`（L94）；调用：`clamp_selection`, `join`, `len`, `render_screen`, `safe_render_columns`, `self._clear_render`, `self._hint_lines`, `self._move_cursor_to_input_end`, `self._suggestions`, `sys.stdout.flush`, `sys.stdout.write`
  - `_hint_lines(self, suggestions: list[CommandSpec]) -> list[str]`（L109）；调用：`enumerate`, `format_command_argument_usage_panel`, `format_command_suggestion`, `format_command_usage_panel`, `self.command_registry.exact_command`
  - `_clear_render(self) -> None`（L122）；调用：`len`, `range`, `sys.stdout.flush`, `sys.stdout.write`
  - `_move_cursor_to_input_end(self) -> None`（L141）；调用：`len`, `sys.stdout.flush`, `sys.stdout.write`
  - `_handle_escape_sequence(self) -> None`（L152）；调用：`self._drain_escape_sequence`, `self._read_escape_sequence`, `self.move_selection`
  - `_read_escape_sequence(self) -> str`（L164）；调用：`self._read_pending_char`
  - `_read_pending_char(self, *, timeout: float = 0.0) -> str`（L173）；调用：`select.select`, `self._read_char`
  - `_read_char(self) -> str`（L180）；调用：`read_char_from_fd`, `sys.stdin.read`
  - `_drain_escape_sequence(self) -> None`（L185）；调用：`range`, `select.select`, `self._read_char`
  - `move_selection(self, delta: int) -> None`（L193）；调用：`len`, `self._render`, `self._suggestions`
  - `accept_selected_suggestion(self) -> bool`（L200）；调用：`self._render`, `self._suggestions`, `self.command_registry.exact_command`
- 函数 `format_command_suggestion(spec: CommandSpec, *, selected: bool = False) -> str`（L216）：执行模块级业务逻辑。；调用：无
- 函数 `format_command_usage_panel(spec: CommandSpec) -> list[str]`（L222）：执行模块级业务逻辑。；调用：`join`, `lines.append`, `lines.extend`
- 函数 `format_command_argument_usage_panel(spec: CommandSpec, buffer: str) -> list[str]`（L236）：执行模块级业务逻辑。；调用：`command_argument_prefix`, `command_usage_matches_prefix`, `lines.extend`
- 函数 `command_argument_prefix(spec: CommandSpec, buffer: str) -> str`（L252）：执行模块级业务逻辑。；调用：`buffer.startswith`, `len`, `strip`
- 函数 `command_usage_matches_prefix(usage: str, prefix: str) -> bool`（L260）：执行模块级业务逻辑。；调用：`bool`, `usage.strip`, `usage_text.startswith`
- 函数 `clamp_selection(index: int, suggestion_count: int) -> int`（L267）：执行模块级业务逻辑。；调用：无
- 函数 `strip_readline_markers(text: str) -> str`（L277）：执行模块级业务逻辑。；调用：`READLINE_MARKER_RE.sub`
- 函数 `visible_width(text: str) -> int`（L281）：执行模块级业务逻辑。；调用：`ANSI_ESCAPE_RE.sub`, `character_width`, `strip_readline_markers`, `sum`, `wcswidth`
- 函数 `terminal_width() -> int`（L292）：执行模块级业务逻辑。；调用：`max`, `shutil.get_terminal_size`
- 函数 `read_char_from_fd(input_fd: int, decoder: codecs.IncrementalDecoder) -> str`（L296）：执行模块级业务逻辑。；调用：`decoder.decode`, `os.read`
- 函数 `read_escape_sequence_from_fd(input_fd: int, decoder: codecs.IncrementalDecoder, *, timeout: float = ESC_SEQUENCE_TIMEOUT_SECONDS) -> str`（L306）：执行模块级业务逻辑。；调用：`read_char_from_fd`, `select.select`
- 函数 `safe_render_columns() -> int`（L324）：执行模块级业务逻辑。；调用：`max`, `terminal_width`
- 类 `class RenderedScreen`（L328）：封装该模块的状态与行为。
  - `__init__(self, *, lines: list[str], cursor_row: int, cursor_column: int) -> None`（L329）；调用：无
- 函数 `render_screen(lines: list[str], columns: int) -> RenderedScreen`（L335）：执行模块级业务逻辑。；调用：`RenderedScreen`, `enumerate`, `hard_wrap_ansi`, `len`, `max`, `screen_lines.extend`, `visible_width`
- 函数 `hard_wrap_ansi(text: str, columns: int) -> list[str]`（L348）：执行模块级业务逻辑。；调用：`ANSI_ESCAPE_RE.match`, `join`, `len`, `line_parts.append`, `match.end`, `match.group`, `max`, `parts.append`, `visible_width`
- 函数 `character_width(char: str) -> int`（L376）：执行模块级业务逻辑。；调用：`ord`, `unicodedata.category`, `unicodedata.combining`, `unicodedata.east_asian_width`

### `mycodingagent/terminal_ui/session_selector.py`

- 模块：`mycodingagent.terminal_ui.session_selector`
- 职责：终端输入、历史展示、会话选择与确认交互。
- 内部依赖：`mycodingagent.memory`, `mycodingagent.terminal_ui.input`
- 函数 `select_session_interactively(memory_runtime: MemoryRuntime, *, limit: int = 20, include_all: bool = False, action: str = '恢复') -> str`（L17）：执行模块级业务逻辑。；调用：`clear_session_selector`, `codecs.getincrementaldecoder`, `command_for_session_action`, `decoder.reset`, `len`, `locals`, `memory_runtime.list_migrated_workspace_sessions`, `memory_runtime.list_sessions`, `print`, `print_session_options`, `read_char_from_fd`, `read_escape_sequence_from_fd`, `render_session_selector`, `sys.stdin.fileno`, `sys.stdin.isatty`, `sys.stdout.flush`, `sys.stdout.write`, `termios.tcgetattr`, `termios.tcsetattr`, `tty.setcbreak`
- 函数 `render_session_selector(sessions: list[SessionListItem], selected: int, *, previous_row_count: int = 0, include_workspace: bool = False, action: str = '恢复') -> int`（L98）：执行模块级业务逻辑。；调用：`clear_session_selector`, `enumerate`, `format_session_option`, `join`, `len`, `logical_lines.extend`, `render_screen`, `safe_render_columns`, `sys.stdout.flush`, `sys.stdout.write`
- 函数 `clear_session_selector(rendered_row_count: int) -> None`（L123）：执行模块级业务逻辑。；调用：`range`, `sys.stdout.flush`, `sys.stdout.write`
- 函数 `print_session_options(sessions: list[SessionListItem], *, include_workspace: bool = False) -> None`（L137）：执行模块级业务逻辑。；调用：`format_session_option`, `print`
- 函数 `command_for_session_action(action: str) -> str`（L142）：执行模块级业务逻辑。；调用：`get`
- 函数 `format_session_option(session: SessionListItem, *, selected: bool, include_workspace: bool = False) -> str`（L151）：执行模块级业务逻辑。；调用：无

### `mycodingagent/tool_runtime/__init__.py`

- 模块：`mycodingagent.tool_runtime`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.memory`, `mycodingagent.tool_runtime.ask_user`, `mycodingagent.tool_runtime.base`, `mycodingagent.tool_runtime.bash`, `mycodingagent.tool_runtime.edit_file`, `mycodingagent.tool_runtime.file_state_cache`, `mycodingagent.tool_runtime.glob`, `mycodingagent.tool_runtime.grep`, `mycodingagent.tool_runtime.memory_lookup`, `mycodingagent.tool_runtime.read_file`, `mycodingagent.tool_runtime.write_file`, `mycodingagent.workspace.file_cache`
- 类 `class ToolRegistry`（L12）：封装该模块的状态与行为。
  - `__init__(self) -> None`（L13）；调用：`set`
  - `register(self, tool: Tool) -> None`（L17）；调用：无
  - `get(self, name: str) -> Tool | None`（L20）；调用：`self._tools.get`
  - `is_enabled(self, name: str) -> bool`（L24）；调用：无
  - `enable(self, name: str) -> None`（L27）；调用：`self._disabled.discard`
  - `disable(self, name: str) -> None`（L31）；调用：`self._disabled.add`
  - `enable_all(self) -> None`（L35）；调用：`self._disabled.clear`
  - `list_tools(self) -> list[Tool]`（L39）；调用：`list`, `self._tools.values`
  - `get_all_schemas(self, protocol: str = 'anthropic') -> list[dict[str, Any]]`（L43）；调用：`schemas.append`, `self._tools.items`, `tool.get_schema`
- 函数 `create_default_registry(file_cache: FileCache | None = None, file_history: Any = None, file_state_cache: Any = None, workspace_tracker: Any = None, memory_runtime: MemoryRuntime | None = None) -> ToolRegistry`（L61）：执行模块级业务逻辑。；调用：`AskUser`, `Bash`, `CommitWorkingContext`, `EditFile`, `FileStateCache`, `GetRecentConversationTurns`, `GetStoredToolOutput`, `Glob`, `Grep`, `ReadFile`, `RecoverContext`, `RestoreSession`, `SearchRecoverableContext`, `SearchSessionHistory`, `SummarizeCurrentTurnMessage`, `ToolRegistry`, `WriteFile`, `get_sandbox_root`, `registry.register`

### `mycodingagent/tool_runtime/ask_user.py`

- 模块：`mycodingagent.tool_runtime.ask_user`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.tool_runtime.base`
- 类 `class AskUserParams(BaseModel)`（L8）：封装该模块的状态与行为。
- 类 `class AskUser(Tool)`（L14）：封装该模块的状态与行为。
  - `async execute(self, params: AskUserParams) -> ToolResult`（L25）；调用：`ToolResult`, `input`, `join`, `line.rstrip`, `params.intent.split`, `params.query.split`, `print`, `splitlines`, `str`, `strip`

### `mycodingagent/tool_runtime/base.py`

- 模块：`mycodingagent.tool_runtime.base`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.configuration`
- 函数 `get_sandbox_root() -> Path`（L21）：执行模块级业务逻辑。；调用：`CONFIG.sandbox.root.expanduser`, `resolve`
- 函数 `is_path_in_sandbox(path: Path, sandbox_root: Path) -> bool`（L25）：执行模块级业务逻辑。；调用：`path.relative_to`
- 函数 `resolve_sandbox_path(raw_path: str, sandbox_root: Path | None = None) -> tuple[Path | None, str]`（L33）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `get_sandbox_root`, `is_path_in_sandbox`, `path.is_absolute`, `path.relative_to`, `path.resolve`, `raw_path.strip`, `resolve`
- 类 `class ToolResult`（L57）：封装该模块的状态与行为。
- 类 `class Tool(ABC)`（L62）：封装该模块的状态与行为。
  - `is_read_only(self) -> bool`（L71）；调用：无
  - `get_schema(self) -> dict[str, Any]`（L75）；调用：`isinstance`, `required.append`, `schema.pop`, `schema.setdefault`, `self.params_model.model_json_schema`
  - `async execute(self, params: BaseModel) -> ToolResult`（L95）；调用：无

### `mycodingagent/tool_runtime/bash.py`

- 模块：`mycodingagent.tool_runtime.bash`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.tool_runtime.base`
- 函数 `get_docker_image() -> str`（L29）：执行模块级业务逻辑。；调用：无
- 函数 `get_docker_pull_timeout() -> int`（L33）：执行模块级业务逻辑。；调用：无
- 函数 `docker_subprocess_env() -> dict[str, str]`（L37）：执行模块级业务逻辑。；调用：`Path`, `docker_config.mkdir`, `env.get`, `get_sandbox_root`, `os.environ.copy`, `str`
- 类 `class Params(BaseModel)`（L45）：封装该模块的状态与行为。
- 类 `class Bash(Tool)`（L53）：封装该模块的状态与行为。
  - `__init__(self, sandbox_root: Path | None = None) -> None`（L62）；调用：`get_sandbox_root`
  - `async execute(self, params: Params) -> ToolResult`（L66）；调用：`ToolResult`, `asyncio.create_subprocess_exec`, `asyncio.wait_for`, `docker_subprocess_env`, `get_docker_image`, `join`, `min`, `os.getgid`, `os.getuid`, `parts.append`, `proc.communicate`, `proc.kill`, `proc.wait`, `self._check_docker_daemon`, `self._check_image_available`, `self._force_remove_container`, `shutil.which`, `stderr.decode`, `stdout.decode`, `str`, `uuid.uuid4`
  - `async ensure_image(self, image: str | None = None) -> ToolResult`（L143）；调用：`ToolResult`, `get_docker_image`, `self._build_image_from_dockerfile`, `self._check_docker_daemon`, `self._check_image_available`, `self._check_image_supports_bash`, `self._find_sandbox_dockerfile`, `self._is_local_sandbox_image`, `self._pull_image`, `shutil.which`
  - `_is_local_sandbox_image(self, image: str) -> bool`（L185）；调用：`image.startswith`
  - `_find_sandbox_dockerfile(self) -> Path | None`（L188）；调用：`Path`, `candidate.is_file`, `resolve`
  - `async _build_image_from_dockerfile(self, image: str, dockerfile: Path) -> str`（L198）；调用：`asyncio.create_subprocess_exec`, `asyncio.wait_for`, `docker_subprocess_env`, `get_docker_pull_timeout`, `proc.communicate`, `proc.kill`, `proc.wait`, `self._decode_output`, `str`
  - `async _check_docker_daemon(self) -> str`（L239）；调用：`asyncio.create_subprocess_exec`, `asyncio.wait_for`, `detail.lower`, `docker_subprocess_env`, `proc.communicate`, `proc.kill`, `proc.wait`, `self._decode_output`
  - `async _check_image_available(self, image: str) -> str`（L271）；调用：`asyncio.create_subprocess_exec`, `asyncio.wait_for`, `docker_subprocess_env`, `proc.communicate`, `proc.kill`, `proc.wait`, `stderr.decode`, `strip`
  - `async _check_image_supports_bash(self, image: str) -> str`（L300）；调用：`asyncio.create_subprocess_exec`, `asyncio.wait_for`, `docker_subprocess_env`, `proc.communicate`, `proc.kill`, `proc.wait`, `stderr.decode`, `strip`
  - `async _pull_image(self, image: str) -> str`（L334）；调用：`asyncio.create_subprocess_exec`, `asyncio.wait_for`, `docker_subprocess_env`, `get_docker_pull_timeout`, `proc.communicate`, `proc.kill`, `proc.wait`, `self._decode_output`
  - `_decode_output(self, stdout: bytes, stderr: bytes) -> str`（L358）；调用：`join`, `parts.append`, `stderr.decode`, `stdout.decode`, `strip`
  - `async _force_remove_container(self, container_name: str) -> None`（L366）；调用：`asyncio.create_subprocess_exec`, `asyncio.wait_for`, `docker_subprocess_env`, `proc.wait`
- 函数 `async ensure_docker_image(image: str | None = None) -> ToolResult`（L382）：执行模块级业务逻辑。；调用：`Bash`, `ensure_image`

### `mycodingagent/tool_runtime/edit_file.py`

- 模块：`mycodingagent.tool_runtime.edit_file`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.tool_runtime.base`, `mycodingagent.tool_runtime.file_state_cache`, `mycodingagent.workspace.file_cache`
- 类 `class Params(BaseModel)`（L15）：封装该模块的状态与行为。
- 类 `class EditFile(Tool)`（L21）：封装该模块的状态与行为。
  - `__init__(self, file_cache: FileCache | None = None, file_history: Any = None, file_state_cache: FileStateCache | None = None, workspace_tracker: Any = None, sandbox_root: Path | None = None) -> None`（L32）；调用：无
  - `async execute(self, params: Params) -> ToolResult`（L47）；调用：`ToolResult`, `content.count`, `content.replace`, `path.exists`, `path.read_text`, `path.write_text`, `resolve_sandbox_path`, `self._cache.invalidate`, `self._state_cache.check`, `self._state_cache.update`, `self._workspace_tracker.mark_agent_write`, `self.file_history.track_edit`, `str`

### `mycodingagent/tool_runtime/file_state_cache.py`

- 模块：`mycodingagent.tool_runtime.file_state_cache`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：无
- 类 `class FileStateCache`（L7）：封装该模块的状态与行为。
  - `__init__(self) -> None`（L12）；调用：`Lock`
  - `record(self, path: str, content: str, mtime_ns: int) -> None`（L16）；调用：无
  - `has_read(self, path: str) -> bool`（L21）；调用：无
  - `get_state(self, path: str) -> tuple[str, int] | None`（L25）；调用：`self._cache.get`
  - `to_dict(self) -> dict`（L29）；调用：`self._cache.items`
  - `load_dict(self, data: dict) -> None`（L37）；调用：`data.get`, `isinstance`, `item.get`
  - `is_stale(self, path: str) -> bool`（L52）；调用：`Path`, `self._cache.get`, `stat`
  - `check(self, path: str) -> tuple[bool, str]`（L64）；调用：`Path`, `self._cache.get`, `stat`
  - `update(self, path: str) -> None`（L84）；调用：`Path`, `p.read_text`, `p.stat`, `self._cache.pop`
- 函数 `file_state_paths(snapshot: dict) -> list[str]`（L98）：执行模块级业务逻辑。；调用：`isinstance`, `item.get`, `snapshot.get`

### `mycodingagent/tool_runtime/glob.py`

- 模块：`mycodingagent.tool_runtime.glob`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.tool_runtime.base`
- 类 `class Params(BaseModel)`（L14）：封装该模块的状态与行为。
- 类 `class Glob(Tool)`（L19）：封装该模块的状态与行为。
  - `__init__(self, sandbox_root: Path | None = None) -> None`（L29）；调用：无
  - `async execute(self, params: Params) -> ToolResult`（L33）；调用：`ToolResult`, `_iter_matching_files`, `base.exists`, `file_path.relative_to`, `join`, `len`, `matches.append`, `matches.sort`, `resolve_sandbox_path`, `str`
- 函数 `_iter_matching_files(base: Path, pattern: str, sandbox_root: Path)`（L58）：执行模块级业务逻辑。；调用：`Path`, `_matches`, `base.glob`, `os.walk`
- 函数 `_matches(file_path: Path, base: Path, pattern: str, sandbox_root: Path) -> bool`（L75）：执行模块级业务逻辑。；调用：`any`, `file_path.is_file`, `file_path.relative_to`, `file_path.resolve`, `fnmatch.fnmatch`, `is_path_in_sandbox`, `pattern.startswith`, `str`

### `mycodingagent/tool_runtime/grep.py`

- 模块：`mycodingagent.tool_runtime.grep`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.tool_runtime.base`
- 类 `class Params(BaseModel)`（L15）：封装该模块的状态与行为。
- 类 `class Grep(Tool)`（L21）：封装该模块的状态与行为。
  - `__init__(self, sandbox_root: Path | None = None) -> None`（L31）；调用：无
  - `async execute(self, params: Params) -> ToolResult`（L35）；调用：`ToolResult`, `_iter_search_files`, `base.exists`, `enumerate`, `file_path.read_text`, `join`, `len`, `re.compile`, `regex.search`, `resolve_sandbox_path`, `results.append`, `text.splitlines`
- 函数 `_iter_search_files(base: Path, include_pattern: str, sandbox_root: Path)`（L68）：执行模块级业务逻辑。；调用：`Path`, `_include_matches`, `any`, `file_path.relative_to`, `file_path.resolve`, `is_path_in_sandbox`, `os.walk`, `sorted`, `str`
- 函数 `_include_matches(relative_path: str, include_pattern: str) -> bool`（L90）：执行模块级业务逻辑。；调用：`Path`, `fnmatch.fnmatch`, `include_pattern.startswith`

### `mycodingagent/tool_runtime/mcp_discovery.py`

- 模块：`mycodingagent.tool_runtime.mcp_discovery`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.capability_discovery`, `mycodingagent.mcp_integration`, `mycodingagent.tool_runtime.base`
- 类 `class PaginationParams(BaseModel)`（L16）：封装该模块的状态与行为。
- 类 `class ServerSearchParams(PaginationParams)`（L21）：封装该模块的状态与行为。
- 类 `class ServerNameParams(PaginationParams)`（L25）：封装该模块的状态与行为。
- 类 `class ServerItemSearchParams(ServerNameParams)`（L29）：封装该模块的状态与行为。
- 类 `class _ServerItemsTool(Tool)`（L33）：封装该模块的状态与行为。
  - `__init__(self, manager: MCPClientManager, router: CapabilityRouter | None = None) -> None`（L41）；调用：无
  - `async execute(self, params: ServerNameParams) -> ToolResult`（L45）；调用：`_json_result`, `_paginate`, `getattr`, `method`, `result.get`, `self._router.record_mcp_server_use`
- 类 `class _ServerItemSearchTool(_ServerItemsTool)`（L59）：封装该模块的状态与行为。
  - `async execute(self, params: ServerItemSearchParams) -> ToolResult`（L62）；调用：`_json_result`, `_paginate`, `_search_items`, `getattr`, `method`, `result.get`, `self._router.record_mcp_server_use`
- 类 `class ListServersTool(Tool)`（L77）：封装该模块的状态与行为。
  - `__init__(self, manager: MCPClientManager) -> None`（L90）；调用：无
  - `async execute(self, params: PaginationParams) -> ToolResult`（L93）；调用：`_json_result`, `_paginate`, `self._manager.list_servers`, `server.to_payload`
- 类 `class SearchServersTool(Tool)`（L98）：封装该模块的状态与行为。
  - `__init__(self, router: CapabilityRouter) -> None`（L109）；调用：无
  - `async execute(self, params: ServerSearchParams) -> ToolResult`（L112）；调用：`_json_result`, `_paginate`, `item.to_payload`, `self._router.route`
- 类 `class ListToolsTool(_ServerItemsTool)`（L128）：封装该模块的状态与行为。
- 类 `class SearchToolsTool(_ServerItemSearchTool)`（L135）：封装该模块的状态与行为。
- 类 `class ListResourcesTool(_ServerItemsTool)`（L142）：封装该模块的状态与行为。
- 类 `class SearchResourcesTool(_ServerItemSearchTool)`（L149）：封装该模块的状态与行为。
- 类 `class ListPromptsTool(_ServerItemsTool)`（L156）：封装该模块的状态与行为。
- 类 `class SearchPromptsTool(_ServerItemSearchTool)`（L163）：封装该模块的状态与行为。
- 函数 `register_mcp_discovery_tools(registry, *, manager: MCPClientManager, router: CapabilityRouter) -> None`（L170）：执行模块级业务逻辑。；调用：`ListPromptsTool`, `ListResourcesTool`, `ListServersTool`, `ListToolsTool`, `SearchPromptsTool`, `SearchResourcesTool`, `SearchServersTool`, `SearchToolsTool`, `registry.register`
- 函数 `_search_items(query: str, items: list[dict]) -> list[dict]`（L186）：执行模块级业务逻辑。；调用：`get`, `item.get`, `list`, `lower`, `query.replace`, `scored.append`, `scored.sort`, `split`, `str`, `sum`, `term.lower`, `term.strip`
- 函数 `_paginate(items: list[dict], *, offset: int, limit: int, item_key: str) -> dict`（L200）：执行模块级业务逻辑。；调用：`len`, `max`, `min`
- 函数 `_json_result(payload: dict, *, is_error: bool = False) -> ToolResult`（L218）：执行模块级业务逻辑。；调用：`ToolResult`, `json.dumps`

### `mycodingagent/tool_runtime/mcp_execution.py`

- 模块：`mycodingagent.tool_runtime.mcp_execution`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.mcp_integration.hooks`, `mycodingagent.mcp_integration.manager`, `mycodingagent.mcp_integration.policy`, `mycodingagent.tool_runtime.base`
- 类 `class CallToolParams(BaseModel)`（L16）：封装该模块的状态与行为。
- 类 `class ReadResourceParams(BaseModel)`（L23）：封装该模块的状态与行为。
- 类 `class GetPromptParams(BaseModel)`（L29）：封装该模块的状态与行为。
- 类 `class CallMCPToolTool(Tool)`（L36）：封装该模块的状态与行为。
  - `__init__(self, manager: MCPClientManager, policy: MCPToolPermissionPolicy, approval_hook: MCPToolApprovalHook) -> None`（L47）；调用：无
  - `async execute(self, params: CallToolParams) -> ToolResult`（L57）；调用：`MCPApprovalRequest`, `ToolResult`, `_compact_intent`, `_json_result`, `result.to_payload`, `self._approval_hook.approve`, `self._manager.call_tool`, `self._manager.server_configs.get`, `self._policy.classify`, `self._policy.requires_approval`
- 类 `class ReadMCPResourceTool(Tool)`（L87）：封装该模块的状态与行为。
  - `__init__(self, manager: MCPClientManager) -> None`（L95）；调用：无
  - `async execute(self, params: ReadResourceParams) -> ToolResult`（L98）；调用：`ToolResult`, `_compact_intent`, `_json_result`, `result.to_payload`, `self._manager.read_resource`
- 类 `class GetMCPPromptTool(Tool)`（L112）：封装该模块的状态与行为。
  - `__init__(self, manager: MCPClientManager) -> None`（L120）；调用：无
  - `async execute(self, params: GetPromptParams) -> ToolResult`（L123）；调用：`ToolResult`, `_compact_intent`, `_json_result`, `result.to_payload`, `self._manager.get_prompt`
- 函数 `register_mcp_execution_tools(registry, *, manager: MCPClientManager, policy: MCPToolPermissionPolicy, approval_hook: MCPToolApprovalHook) -> None`（L137）：执行模块级业务逻辑。；调用：`CallMCPToolTool`, `GetMCPPromptTool`, `ReadMCPResourceTool`, `registry.register`
- 函数 `_compact_intent(value: str) -> str`（L149）：执行模块级业务逻辑。；调用：`join`, `len`, `split`, `str`
- 函数 `_json_result(payload: dict[str, Any], *, is_error: bool = False) -> ToolResult`（L156）：执行模块级业务逻辑。；调用：`ToolResult`, `json.dumps`

### `mycodingagent/tool_runtime/memory_lookup.py`

- 模块：`mycodingagent.tool_runtime.memory_lookup`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.memory`, `mycodingagent.memory.contracts`, `mycodingagent.tool_runtime.base`
- 类 `class GetStoredToolOutputParams(BaseModel)`（L16）：封装该模块的状态与行为。
- 类 `class GetStoredToolOutput(Tool)`（L22）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime: MemoryRuntime) -> None`（L35）；调用：无
  - `async execute(self, params: GetStoredToolOutputParams) -> ToolResult`（L38）；调用：`recover_context_output`, `self._memory_runtime.drain`
- 类 `class RecoverContextParams(BaseModel)`（L48）：封装该模块的状态与行为。
- 类 `class RecoverContext(Tool)`（L54）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime: MemoryRuntime) -> None`（L67）；调用：无
  - `async execute(self, params: RecoverContextParams) -> ToolResult`（L70）；调用：`recover_context_output`, `self._memory_runtime.drain`
- 类 `class SearchRecoverableContextParams(BaseModel)`（L80）：封装该模块的状态与行为。
- 类 `class SearchRecoverableContext(Tool)`（L85）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime: MemoryRuntime) -> None`（L98）；调用：无
  - `async execute(self, params: SearchRecoverableContextParams) -> ToolResult`（L101）；调用：`ToolResult`, `context.to_dict`, `json.dumps`, `len`, `self._memory_runtime.drain`, `self._memory_runtime.get_current_session_id`, `self._memory_runtime.search_context_metadata`
- 类 `class SearchSessionHistoryParams(BaseModel)`（L116）：封装该模块的状态与行为。
- 类 `class SearchSessionHistory(Tool)`（L122）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime: MemoryRuntime, *, preview_chars: int = 1200) -> None`（L134）；调用：无
  - `async execute(self, params: SearchSessionHistoryParams) -> ToolResult`（L138）；调用：`ToolResult`, `asdict`, `enumerate`, `join`, `json.dumps`, `len`, `message.get`, `message_to_search_text`, `params.query.split`, `query.lower`, `results.append`, `searchable.lower`, `self._memory_runtime.drain`, `self._memory_runtime.get_current_session_id`, `self._memory_runtime.load_session`, `str`, `text.lower`, `truncate_one_line`
- 类 `class GetRecentConversationTurnsParams(BaseModel)`（L202）：封装该模块的状态与行为。
- 类 `class GetRecentConversationTurns(Tool)`（L206）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime: MemoryRuntime) -> None`（L218）；调用：无
  - `async execute(self, params: GetRecentConversationTurnsParams) -> ToolResult`（L221）；调用：`ToolResult`, `asdict`, `json.dumps`, `len`, `self._memory_runtime.drain`, `self._memory_runtime.get_current_session_id`, `self._memory_runtime.store.load_historical_turns`
- 类 `class SummarizeCurrentTurnMessageParams(BaseModel)`（L244）：封装该模块的状态与行为。
- 类 `class SummarizeCurrentTurnMessage(Tool)`（L252）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime: MemoryRuntime) -> None`（L263）；调用：无
  - `async execute(self, params: SummarizeCurrentTurnMessageParams) -> ToolResult`（L266）；调用：`ToolResult`, `asdict`, `json.dumps`, `self._memory_runtime.summarize_current_turn_message`
- 类 `class CommitWorkingContextParams(BaseModel)`（L285）：封装该模块的状态与行为。
- 类 `class CommitWorkingContext(Tool)`（L302）：封装该模块的状态与行为。
  - `__init__(self, context_control: ContextEpochControl) -> None`（L315）；调用：无
  - `async execute(self, params: CommitWorkingContextParams) -> ToolResult`（L318）；调用：`ToolResult`, `json.dumps`, `self._context_control.request_context_epoch_commit`
- 类 `class RestoreSessionParams(BaseModel)`（L342）：封装该模块的状态与行为。
- 类 `class RestoreSession(Tool)`（L346）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime: MemoryRuntime) -> None`（L356）；调用：无
  - `async execute(self, params: RestoreSessionParams) -> ToolResult`（L359）；调用：`ToolResult`, `asdict`, `json.dumps`, `self._memory_runtime.drain`, `self._memory_runtime.restore_historical_session_snapshot`
- 函数 `message_to_search_text(message: dict[str, Any]) -> str`（L375）：执行模块级业务逻辑。；调用：`isinstance`, `json.dumps`, `message.get`
- 函数 `recover_context_output(memory_runtime: MemoryRuntime, *, context_id: str, offset: int, limit: int) -> ToolResult`（L387）：执行模块级业务逻辑。；调用：`ToolResult`, `json.dumps`, `len`, `memory_runtime.get_context_metadata`, `memory_runtime.get_tool_output`, `memory_runtime.load_partial_context`, `min`
- 函数 `truncate_one_line(text: str, *, max_chars: int) -> str`（L444）：执行模块级业务逻辑。；调用：`join`, `len`, `split`, `text.strip`

### `mycodingagent/tool_runtime/read_file.py`

- 模块：`mycodingagent.tool_runtime.read_file`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.tool_runtime.base`, `mycodingagent.tool_runtime.file_state_cache`, `mycodingagent.workspace.file_cache`
- 类 `class Params(BaseModel)`（L15）：封装该模块的状态与行为。
- 类 `class ReadFile(Tool)`（L21）：封装该模块的状态与行为。
  - `__init__(self, file_cache: FileCache | None = None, file_state_cache: FileStateCache | None = None, sandbox_root: Path | None = None) -> None`（L29）；调用：无
  - `async execute(self, params: Params) -> ToolResult`（L40）；调用：`ToolResult`, `enumerate`, `join`, `path.exists`, `path.is_file`, `path.read_text`, `path.stat`, `resolve_sandbox_path`, `self._cache.get`, `self._cache.put`, `self._state_cache.record`, `str`, `text.splitlines`

### `mycodingagent/tool_runtime/skill_tools.py`

- 模块：`mycodingagent.tool_runtime.skill_tools`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.skill_runtime.contracts`, `mycodingagent.tool_runtime.base`
- 类 `class SearchSkillParams(BaseModel)`（L11）：封装该模块的状态与行为。
- 类 `class SearchSkillTool(Tool)`（L22）：封装该模块的状态与行为。
  - `__init__(self, runtime: SkillService) -> None`（L37）；调用：无
  - `async execute(self, params: SearchSkillParams) -> ToolResult`（L40）；调用：`ToolResult`, `json.dumps`, `self._runtime.search_skill_schemas`
- 类 `class GetAllToolParams(BaseModel)`（L49）：封装该模块的状态与行为。
- 类 `class GetAllTool(Tool)`（L53）：封装该模块的状态与行为。
  - `__init__(self, runtime: SkillService) -> None`（L68）；调用：无
  - `async execute(self, params: GetAllToolParams) -> ToolResult`（L71）；调用：`ToolResult`, `json.dumps`, `self._runtime.list_skill_tools`
- 类 `class GetToolByNameParams(BaseModel)`（L76）：封装该模块的状态与行为。
- 类 `class GetToolByNameTool(Tool)`（L80）：封装该模块的状态与行为。
  - `__init__(self, runtime: SkillService) -> None`（L92）；调用：无
  - `async execute(self, params: GetToolByNameParams) -> ToolResult`（L95）；调用：`ToolResult`, `bool`, `json.dumps`, `result.get`, `self._runtime.get_tool_schema_by_name`
- 类 `class SearchSkillReferencesParams(BaseModel)`（L100）：封装该模块的状态与行为。
- 类 `class SearchSkillReferencesTool(Tool)`（L106）：封装该模块的状态与行为。
  - `__init__(self, runtime: SkillService) -> None`（L118）；调用：无
  - `async execute(self, params: SearchSkillReferencesParams) -> ToolResult`（L121）；调用：`ToolResult`, `json.dumps`, `self._runtime.search_skill_references`
- 类 `class GetSkillReferenceParams(BaseModel)`（L130）：封装该模块的状态与行为。
- 类 `class GetSkillReferenceTool(Tool)`（L135）：封装该模块的状态与行为。
  - `__init__(self, runtime: SkillService) -> None`（L146）；调用：无
  - `async execute(self, params: GetSkillReferenceParams) -> ToolResult`（L149）；调用：`ToolResult`, `bool`, `json.dumps`, `result.get`, `self._runtime.get_skill_reference`
- 类 `class SkillInvocationParams(BaseModel)`（L157）：封装该模块的状态与行为。
- 类 `class SkillTool(Tool)`（L162）：封装该模块的状态与行为。
  - `__init__(self, runtime: SkillService, tool_name: str) -> None`（L166）；调用：`self._runtime.get_record`
  - `async execute(self, params: SkillInvocationParams) -> ToolResult`（L180）；调用：`ToolResult`, `join`, `json.dumps`, `self._runtime.get_record`, `self._runtime.list_references_for_skill`, `self._runtime.record_skill_invocation`
- 函数 `skill_schema_from_record(record) -> dict`（L214）：执行模块级业务逻辑。；调用：`SkillInvocationParams.model_json_schema`

### `mycodingagent/tool_runtime/workspace_change_tracker.py`

- 模块：`mycodingagent.tool_runtime.workspace_change_tracker`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.tool_runtime.file_state_cache`
- 类 `class WorkspaceChangeTracker`（L41）：封装该模块的状态与行为。
  - `__init__(self, root: Path, file_state_cache: FileStateCache, *, max_changes: int = 20) -> None`（L42）；调用：`Event`, `Lock`, `root.resolve`, `set`
  - `start(self) -> None`（L53）；调用：`Thread`, `_InotifyWorkspaceBackend`, `_PollingWorkspaceBackend`, `self._thread.start`, `self.root.mkdir`
  - `close(self) -> None`（L64）；调用：`self._backend.close`, `self._stop_event.set`, `self._thread.join`
  - `mark_agent_write(self, path: str) -> None`（L71）；调用：`Path`, `_fingerprint`, `self._changed_paths.discard`, `self._normalize_path`
  - `mark_paths_for_recheck(self, paths: list[str]) -> None`（L80）；调用：`self._agent_writes.pop`, `self._changed_paths.add`, `self._normalize_path`
  - `consume_external_changes(self) -> tuple[list[str], int]`（L87）；调用：`_display_path`, `len`, `max`, `self._changed_paths.clear`, `self._is_agent_write`, `self.file_state_cache.has_read`, `self.file_state_cache.is_stale`, `sorted`, `stale_paths.append`
  - `_run(self) -> None`（L105）；调用：`self._backend.poll`, `self._stop_event.is_set`
  - `_record_change(self, path: Path, is_delete: bool) -> None`（L111）；调用：`path.is_dir`, `self._changed_paths.add`, `self._is_agent_write`, `self._normalize_path`, `self.file_state_cache.has_read`, `str`
  - `_is_agent_write(self, path: str) -> bool`（L122）；调用：`Path`, `_fingerprint`, `self._agent_writes.get`, `self._agent_writes.pop`
  - `_normalize_path(self, path: str) -> str`（L134）；调用：`Path`, `resolve`, `str`
- 类 `class _WorkspaceBackend`（L138）：封装该模块的状态与行为。
  - `poll(self, stop_event: Event) -> None`（L139）；调用：无
  - `close(self) -> None`（L142）；调用：无
- 类 `class _InotifyWorkspaceBackend(_WorkspaceBackend)`（L146）：封装该模块的状态与行为。
  - `__init__(self, root: Path, on_change) -> None`（L147）；调用：`OSError`, `ctypes.CDLL`, `ctypes.get_errno`, `os.strerror`, `self._add_tree`, `self._libc.inotify_init1`
  - `poll(self, stop_event: Event) -> None`（L157）；调用：`os.read`, `select.select`, `self._consume_events`, `stop_event.is_set`
  - `close(self) -> None`（L171）；调用：`os.close`
  - `_consume_events(self, data: bytes) -> None`（L177）；调用：`EVENT_STRUCT.unpack_from`, `_should_skip`, `bool`, `len`, `raw_name.decode`, `rstrip`, `self._add_tree`, `self._on_change`, `self._watch_descriptors.get`, `self._watch_descriptors.pop`
  - `_add_tree(self, root: Path) -> None`（L200）；调用：`_iter_directories`, `self._add_watch`
  - `_add_watch(self, directory: Path) -> None`（L204）；调用：`os.fsencode`, `self._libc.inotify_add_watch`, `str`
- 类 `class _PollingWorkspaceBackend(_WorkspaceBackend)`（L212）：封装该模块的状态与行为。
  - `__init__(self, root: Path, on_change) -> None`（L213）；调用：`_snapshot`
  - `poll(self, stop_event: Event) -> None`（L218）；调用：`Path`, `_snapshot`, `changed_paths.add`, `self._on_change`, `set`, `stop_event.wait`
- 函数 `_iter_directories(root: Path) -> list[Path]`（L230）：执行模块级业务逻辑。；调用：`_should_skip`, `directories.append`, `path.is_dir`, `root.exists`, `root.rglob`
- 函数 `_should_skip(path: Path) -> bool`（L240）：执行模块级业务逻辑。；调用：`any`
- 函数 `_snapshot(root: Path) -> dict[str, tuple[int, int]]`（L244）：执行模块级业务逻辑。；调用：`_fingerprint`, `_should_skip`, `path.is_dir`, `path.resolve`, `root.exists`, `root.rglob`, `str`
- 函数 `_fingerprint(path: Path) -> tuple[int, int] | None`（L257）：执行模块级业务逻辑。；调用：`path.stat`
- 函数 `_display_path(root: Path, path: str) -> str`（L265）：执行模块级业务逻辑。；调用：`Path`, `relative_to`, `str`

### `mycodingagent/tool_runtime/write_file.py`

- 模块：`mycodingagent.tool_runtime.write_file`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.tool_runtime.base`, `mycodingagent.tool_runtime.file_state_cache`, `mycodingagent.workspace.file_cache`
- 类 `class Params(BaseModel)`（L15）：封装该模块的状态与行为。
- 类 `class WriteFile(Tool)`（L20）：封装该模块的状态与行为。
  - `__init__(self, file_cache: FileCache | None = None, file_history: Any = None, file_state_cache: FileStateCache | None = None, workspace_tracker: Any = None, sandbox_root: Path | None = None) -> None`（L31）；调用：无
  - `async execute(self, params: Params) -> ToolResult`（L46）；调用：`ToolResult`, `path.exists`, `path.parent.mkdir`, `path.write_text`, `resolve_sandbox_path`, `self._cache.invalidate`, `self._state_cache.check`, `self._state_cache.update`, `self._workspace_tracker.mark_agent_write`, `self.file_history.track_edit`, `str`

### `mycodingagent/workspace/__init__.py`

- 模块：`mycodingagent.workspace`
- 职责：Workspace identity, file state, cache, and change tracking.
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/workspace/file_cache.py`

- 模块：`mycodingagent.workspace.file_cache`
- 职责：工作区身份、文件缓存和工作区状态。
- 内部依赖：无
- 类 `class FileCache`（L8）：封装该模块的状态与行为。
  - `__init__(self) -> None`（L9）；调用：`threading.Lock`
  - `get(self, path: str) -> str | None`（L13）；调用：`self._store.get`
  - `put(self, path: str, content: str) -> None`（L18）；调用：无
  - `invalidate(self, path: str) -> None`（L23）；调用：`self._store.pop`
  - `clear(self) -> None`（L28）；调用：`self._store.clear`
  - `__len__(self) -> int`（L33）；调用：`len`

### `mycodingagent/workspace/identity.py`

- 模块：`mycodingagent.workspace.identity`
- 职责：工作区身份、文件缓存和工作区状态。
- 内部依赖：无
- 函数 `workspace_root_text(root: Path | str) -> str`（L8）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `resolve`, `str`
- 函数 `workspace_label(root: Path | str) -> str`（L12）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `resolve`, `str`
- 函数 `workspace_fingerprint(root: Path | str) -> str`（L17）：执行模块级业务逻辑。；调用：`Path`, `_git_fingerprint`, `expanduser`, `hashlib.sha256`, `hexdigest`, `join`, `marker.exists`, `marker.is_file`, `marker.read_bytes`, `markers.append`, `raw.encode`, `resolve`, `str`
- 函数 `_git_fingerprint(path: Path) -> str`（L34）：执行模块级业务逻辑。；调用：`hashlib.sha256`, `hexdigest`, `raw.encode`, `str`, `strip`, `subprocess.check_output`

## 6. 架构验证规则

- `tests/test_architecture_boundaries.py` 检查核心模块无 import cycle。
- 多智能体角色必须位于独立目录，编排层不得直接依赖 LLM/Tool 实现。
- 上下文阶段管理器依赖存储 Protocol；提交工具依赖控制 Protocol。
- 新增、删除、移动模块、类或函数后必须重新生成本文档。
- 完成修改前必须运行全量测试、编译检查和 `git diff --check`。
