# myCodingAgent 函数级项目框架图

> 本文档由当前源码结构生成。每次代码修改后必须同步更新，确保项目、模块、类、函数和依赖关系可审计。

## 1. 项目总览

- 项目：`myCodingAgent`
- 运行时代码：`mycodingagent/`
- 插件资产：`skills/`，仅保存独立 Skill 定义、脚本和资源。
- 启动入口：根目录 `__main__.py` -> `mycodingagent.app.main.main()`。
- 架构原则：应用层负责组装；业务模块依赖 Protocol；基础设施适配器依赖具体 SDK、数据库和工具框架。
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
├── memory/  # 会话持久化、上下文预算、虚拟化、检查点和恢复。
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

- 当前核心运行时依赖图无循环。
- `app` 是唯一组合根，可引用各模块具体实现。
- `multi_agent/orchestration` 不直接导入 LLM 或 Tool 具体实现。
- `capability_discovery` 不直接导入 MCP Client 具体实现。
- `skill_runtime` 通过 `ToolRegistrar` 注册工具，Skill 工具适配器位于 `tool_runtime/skill_tools.py`。

## 4. 多智能体框架

```text
multi_agent/
├── domain/          # AgentRequest、WorkflowResult、Protocol 等纯契约
├── orchestration/   # 工作流状态机、调度、路径所有权和修复循环
├── infrastructure/  # 模型、工具、事件、运行日志和工作区适配器
└── agents/
    ├── router/      # 请求分类和最终总结
    ├── planner/     # 审计范围、执行计划和修复计划
    ├── auditor/     # 审计拆分、并发子审计和结果合并
    ├── optimizer/   # 只读架构优化提案
    ├── executor/    # 按 allowed_paths 修改代码
    └── validator/   # 只读测试、构建和静态验证
```

核心流程：

```text
用户输入 -> Router
  ├── direct -> DirectResponder -> 主 Agent 回答
  ├── audit_only -> Planner -> Auditor workers -> Auditor merge -> Optimizer proposal -> 主 Agent 总结
  └── implementation -> Audit -> Optimize/Approve -> Plan -> Executor batches -> Validator -> Repair -> 主 Agent 总结
所有路径 -> JsonRunJournal -> get_multicoding_run 工具可查询
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
- 函数 `async main(无) -> None` （L56）：执行模块级业务逻辑。；调用：`AgentRunner`, `AsyncOpenAI`, `CLIApprovalHook`, `CLIArchitectureApprovalHook`, `CLIRuntimeEventHook`, `CapabilityRouter`, `CommandContext`, `FileStateCache`, `GetMultiAgentRun`, `JsonRunJournal`, `LLMDirectResponder`, `MCPClientManager`, `MCPConfigLoader`, `MCPToolPermissionPolicy`, `MemoryRuntime`, `MultiCodingController`

### `mycodingagent/capability_discovery/__init__.py`

- 模块：`mycodingagent.capability_discovery`
- 职责：Skill 与 MCP 能力推荐，依赖抽象能力源。
- 内部依赖：`mycodingagent.capability_discovery.router`
- 定义：无公开类或函数。

### `mycodingagent/capability_discovery/contracts.py`

- 模块：`mycodingagent.capability_discovery.contracts`
- 职责：Skill 与 MCP 能力推荐，依赖抽象能力源。
- 内部依赖：无
- 类 `class MCPServerView`（L6）：封装该模块的状态与行为。
- 类 `class SkillCapabilitySource`（L20）：封装该模块的状态与行为。
  - `async build_tools_for_prompt_async(self, prompt, core_tool_schemas) -> list[dict[str, Any]]` （L24）；调用：无
  - `search_records_for_capability(self, query, top_k) -> list[Any]` （L30）；调用：无
- 类 `class MCPServerSource`（L33）：封装该模块的状态与行为。
  - `server_count(self) -> int` （L34）；调用：无
  - `available_count(self) -> int` （L36）；调用：无
  - `list_servers(self) -> list[MCPServerView]` （L38）；调用：无

### `mycodingagent/capability_discovery/models.py`

- 模块：`mycodingagent.capability_discovery.models`
- 职责：Skill 与 MCP 能力推荐，依赖抽象能力源。
- 内部依赖：无
- 类 `class CapabilityRecommendation`（L11）：封装该模块的状态与行为。
  - `to_payload(self) -> dict[str, Any]` （L19）；调用：`asdict`, `round`
- 类 `class CapabilityResult`（L26）：封装该模块的状态与行为。
  - `to_runtime_payload(self) -> dict[str, Any]` （L36）；调用：`item.to_payload`

### `mycodingagent/capability_discovery/retrieval.py`

- 模块：`mycodingagent.capability_discovery.retrieval`
- 职责：Skill 与 MCP 能力推荐，依赖抽象能力源。
- 内部依赖：`mycodingagent.capability_discovery.contracts`
- 类 `class ServerRetrievalScore`（L12）：封装该模块的状态与行为。
- 类 `class LexicalServerSignal`（L18）：封装该模块的状态与行为。
  - `score(self, query, servers) -> list[ServerRetrievalScore]` （L19）；调用：`ServerRetrievalScore`, `_tokens`, `_weighted_terms`, `join`, `len`, `max`, `min`, `query.lower`, `query_tokens.intersection`, `reasons.append`, `results.append`, `results.sort`
- 函数 `_tokens(text) -> set[str]` （L45）：执行模块级业务逻辑。；调用：`TOKEN_RE.findall`, `item.lower`
- 函数 `_weighted_terms(server) -> list[tuple[str, float]]` （L49）：执行模块级业务逻辑。；调用：`terms.extend`

### `mycodingagent/capability_discovery/router.py`

- 模块：`mycodingagent.capability_discovery.router`
- 职责：Skill 与 MCP 能力推荐，依赖抽象能力源。
- 内部依赖：`mycodingagent.capability_discovery.contracts`, `mycodingagent.capability_discovery.models`, `mycodingagent.capability_discovery.retrieval`, `mycodingagent.relevance.lrfu`
- 类 `class CapabilityRouterConfig`（L13）：封装该模块的状态与行为。
- 类 `class CapabilityRouter`（L21）：封装该模块的状态与行为。
  - `__init__(self, skill_runtime, mcp_manager, config) -> None` （L22）；调用：`CapabilityRouterConfig`, `LRFUCache`, `LexicalServerSignal`
  - `async route(self, prompt) -> CapabilityResult` （L36）；调用：`CapabilityResult`, `recommendations.extend`, `recommendations.sort`, `self._mcp_recommendations`, `self._skill_recommendations`, `self.mcp_manager.available_count`, `self.mcp_manager.server_count`, `tuple`
  - `record_mcp_server_use(self, server, reward) -> None` （L55）；调用：`self._server_lrfu.touch`
  - `async build_tools_for_prompt(self, prompt, core_tool_schemas) -> list[dict[str, Any]]` （L59）；调用：`self.skill_runtime.build_tools_for_prompt_async`
  - `async _skill_recommendations(self, prompt) -> list[CapabilityRecommendation]` （L68）；调用：`CapabilityRecommendation`, `float`, `min`, `recommendations.append`, `runtime.search_records_for_capability`, `str`
  - `_mcp_recommendations(self, prompt) -> list[CapabilityRecommendation]` （L94）；调用：`CapabilityRecommendation`, `by_name.get`, `by_name.values`, `max`, `self._lexical_signal.score`, `self._server_lrfu.top_candidates`, `self.mcp_manager.list_servers`, `server_by_name.get`, `sorted`

### `mycodingagent/commands/__init__.py`

- 模块：`mycodingagent.commands`
- 职责：CLI 命令注册、解析和命令处理。
- 内部依赖：`mycodingagent.commands.registry`
- 定义：无公开类或函数。

### `mycodingagent/commands/handlers.py`

- 模块：`mycodingagent.commands.handlers`
- 职责：CLI 命令注册、解析和命令处理。
- 内部依赖：`mycodingagent.commands.registry`, `mycodingagent.configuration`, `mycodingagent.llm_runtime`, `mycodingagent.memory.session_switch`, `mycodingagent.terminal_ui.confirm`, `mycodingagent.terminal_ui.history`, `mycodingagent.terminal_ui.session_selector`
- 函数 `build_command_registry(无) -> CommandRegistry` （L16）：执行模块级业务逻辑。；调用：`CommandRegistry`, `CommandSpec`, `registry.register`
- 函数 `async handle_multicoding_command(context, arguments) -> CommandResult` （L129）：执行模块级业务逻辑。；调用：`CommandResult`, `arguments.strip`, `build_command_registry`, `controller.disable`, `controller.enable`, `controller.status_text`, `lower`, `match`, `print`, `spec.help_text`
- 函数 `async handle_resume_command(context, arguments) -> CommandResult` （L158）：执行模块级业务逻辑。；调用：`CommandResult`, `arguments.strip`, `build_command_registry`, `confirm_cross_workspace_restore`, `has_conversation_content`, `len`, `match`, `memory_runtime.cleanup_expired_sessions`, `memory_runtime.drain`, `memory_runtime.load_file_state_snapshot`, `memory_runtime.load_lrfu_snapshot`, `memory_runtime.load_session`, `memory_runtime.touch_session`, `print`, `render_conversation_history`, `resume_spec.help_text`
- 函数 `async handle_fork_command(context, arguments) -> CommandResult` （L207）：执行模块级业务逻辑。；调用：`CommandResult`, `arguments.strip`, `build_command_registry`, `confirm_cross_workspace_action`, `fork_spec.help_text`, `has_conversation_content`, `len`, `match`, `memory_runtime.cleanup_expired_sessions`, `memory_runtime.drain`, `memory_runtime.fork_session`, `memory_runtime.load_file_state_snapshot`, `memory_runtime.load_lrfu_snapshot`, `memory_runtime.store.load_session`, `print`, `render_conversation_history`
- 函数 `async handle_clear_command(context, arguments) -> CommandResult` （L273）：执行模块级业务逻辑。；调用：`CommandResult`, `arguments.strip`, `build_command_registry`, `clear_spec.help_text`, `match`, `memory_runtime.clear_current_session_id`, `memory_runtime.drain`, `memory_runtime.start_session`, `print`, `save_current_session_if_needed`
- 函数 `async handle_delete_command(context, arguments) -> CommandResult` （L308）：执行模块级业务逻辑。；调用：`CommandResult`, `arguments.strip`, `build_command_registry`, `confirm_cross_workspace_action`, `confirm_delete_sessions`, `delete_spec.help_text`, `match`, `memory_runtime.cleanup_expired_sessions`, `memory_runtime.delete_session`, `memory_runtime.delete_sessions`, `memory_runtime.drain`, `memory_runtime.list_sessions`, `memory_runtime.store.load_session`, `print`, `save_current_session_if_needed`, `select_session_interactively`

### `mycodingagent/commands/registry.py`

- 模块：`mycodingagent.commands.registry`
- 职责：CLI 命令注册、解析和命令处理。
- 内部依赖：无
- 类 `class CommandContext`（L8）：封装该模块的状态与行为。
- 类 `class CommandResult`（L18）：封装该模块的状态与行为。
- 类 `class CommandSpec`（L28）：封装该模块的状态与行为。
  - `names(self) -> tuple[str, ...]` （L37）；调用：无
  - `help_text(self) -> str` （L40）；调用：`join`, `lines.append`, `lines.extend`
- 类 `class CommandRegistry`（L55）：封装该模块的状态与行为。
  - `__init__(self) -> None` （L56）；调用：无
  - `register(self, spec) -> None` （L59）；调用：无
  - `suggestions(self, buffer) -> list[CommandSpec]` （L62）；调用：`any`, `char.isspace`, `list`, `self._commands.values`, `spec.name.startswith`, `text.startswith`
  - `exact_command(self, buffer) -> CommandSpec | None` （L70）；调用：`buffer.strip`, `self._commands.get`, `text.split`, `text.startswith`
  - `match(self, text) -> tuple[CommandSpec, str] | None` （L77）；调用：`len`, `self._commands.values`, `spec.names`, `strip`, `stripped.startswith`, `text.strip`
  - `async execute(self, text, context) -> CommandResult` （L87）；调用：`CommandResult`, `self.match`, `spec.handler`

### `mycodingagent/configuration/__init__.py`

- 模块：`mycodingagent.configuration`
- 职责：Environment-backed application settings.
- 内部依赖：`mycodingagent.configuration.settings`
- 定义：无公开类或函数。

### `mycodingagent/configuration/settings.py`

- 模块：`mycodingagent.configuration.settings`
- 职责：环境变量解析与不可变应用配置。
- 内部依赖：无
- 函数 `_env_int(name, default) -> int` （L9）：执行模块级业务逻辑。；调用：`int`, `os.getenv`
- 函数 `_env_float(name, default) -> float` （L19）：执行模块级业务逻辑。；调用：`float`, `os.getenv`
- 函数 `_env_bool(name, default) -> bool` （L29）：执行模块级业务逻辑。；调用：`lower`, `os.getenv`, `raw_value.strip`
- 函数 `_env_path(name, default) -> Path | None` （L36）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `os.getenv`
- 函数 `_env_paths(name) -> tuple[Path, ...]` （L43）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `item.strip`, `os.getenv`, `raw_value.split`, `tuple`
- 函数 `_env_list(name, default) -> tuple[str, ...]` （L50）：执行模块级业务逻辑。；调用：`item.strip`, `os.getenv`, `raw_value.split`, `tuple`
- 函数 `_default_user_id(无) -> str` （L57）：执行模块级业务逻辑。；调用：`os.getenv`
- 函数 `_env_json_dict(name, default) -> dict` （L66）：执行模块级业务逻辑。；调用：`isinstance`, `json.loads`, `os.getenv`
- 函数 `_default_builtin_skills_root(无) -> Path` （L77）：执行模块级业务逻辑。；调用：`Path`, `resolve`
- 函数 `_default_workspace_skills_root(无) -> Path` （L81）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `os.getcwd`, `os.getenv`
- 函数 `_default_memory_db_path(无) -> Path` （L91）：执行模块级业务逻辑。；调用：`Path`, `Path.home`, `expanduser`, `os.getenv`
- 函数 `_default_mcp_user_config_path(无) -> Path` （L101）：执行模块级业务逻辑。；调用：`Path.home`
- 函数 `_default_mcp_project_config_path(无) -> Path` （L105）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `os.getcwd`, `os.getenv`
- 函数 `_dedupe_paths(paths) -> tuple[Path, ...]` （L109）：执行模块级业务逻辑。；调用：`path.expanduser`, `resolve`, `result.append`, `seen.add`, `set`, `str`, `tuple`
- 类 `class ApiConfig`（L122）：封装该模块的状态与行为。
- 类 `class ClientConfig`（L131）：封装该模块的状态与行为。
- 类 `class MultiCodingConfig`（L145）：封装该模块的状态与行为。
- 类 `class MemoryConfig`（L167）：封装该模块的状态与行为。
  - `context_window_for(self, model) -> int` （L215）；调用：`isinstance`, `self.model_context_windows.get`
- 类 `class SandboxConfig`（L223）：封装该模块的状态与行为。
- 类 `class DockerConfig`（L245）：封装该模块的状态与行为。
- 类 `class SkillConfig`（L266）：封装该模块的状态与行为。
  - `root(self) -> Path` （L330）；调用：无
  - `roots(self) -> tuple[Path, ...]` （L334）；调用：`_dedupe_paths`
- 类 `class EmbeddingConfig`（L339）：封装该模块的状态与行为。
- 类 `class MilvusConfig`（L357）：封装该模块的状态与行为。
  - `uri(self) -> str` （L387）；调用：`os.getenv`
- 类 `class MCPConfig`（L392）：封装该模块的状态与行为。
- 类 `class AppConfig`（L415）：封装该模块的状态与行为。

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
- 函数 `stable_json_hash(value) -> str` （L77）：执行模块级业务逻辑。；调用：`hashlib.sha256`, `hexdigest`, `json.dumps`, `payload.encode`
- 函数 `estimated_json_tokens(value) -> int` （L82）：执行模块级业务逻辑。；调用：`estimate_tokens`, `json.dumps`
- 函数 `api_usage_to_dict(usage) -> dict[str, int]` （L86）：执行模块级业务逻辑。；调用：`getattr`, `int`
- 函数 `add_usage_to_summary(summary, values) -> None` （L103）：执行模块级业务逻辑。；调用：`TokenUsageRecord`, `summary.add`
- 函数 `format_token_summary(label, summary) -> str` （L118）：执行模块级业务逻辑。；调用：无
- 函数 `split_prompt_debug_sections(model_messages, temporary_system_messages, tools, current_turn_start) -> dict[str, Any]` （L126）：执行模块级业务逻辑。；调用：`get`, `len`, `max`, `min`, `range`
- 函数 `build_prompt_debug_snapshot(model_messages, temporary_system_messages, tools, current_turn_start, rendered_prompt) -> PromptDebugSnapshot` （L153）：执行模块级业务逻辑。；调用：`PromptDebugSnapshot`, `estimated_json_tokens`, `len`, `split_prompt_debug_sections`, `stable_json_hash`
- 函数 `first_changed_prompt_debug_section(previous, current) -> str` （L203）：执行模块级业务逻辑。；调用：无
- 函数 `print_prompt_debug(snapshot, first_changed_section) -> None` （L223）：执行模块级业务逻辑。；调用：`print_token_block`
- 函数 `print_prompt_debug_with_previous(snapshot) -> None` （L246）：执行模块级业务逻辑。；调用：`first_changed_prompt_debug_section`, `print_prompt_debug`
- 函数 `print_token_block(*lines) -> None` （L253）：执行模块级业务逻辑。；调用：`print`
- 函数 `context_budget_state_from_snapshot(snapshot) -> ContextBudgetState` （L260）：执行模块级业务逻辑。；调用：`ContextBudgetState`, `float`, `getattr`, `str`
- 函数 `format_openai_tools(raw_tools) -> list[dict[str, Any]]` （L269）：执行模块级业务逻辑。；调用：`tool.get`, `tools.append`
- 函数 `pretty_arguments(raw_args) -> str` （L291）：执行模块级业务逻辑。；调用：`format_argument_mapping`, `isinstance`, `json.dumps`, `json.loads`, `raw_args.strip`
- 函数 `format_argument_mapping(arguments) -> str` （L304）：执行模块级业务逻辑。；调用：`arguments.items`, `indent_multiline_text`, `join`, `json.dumps`, `lines.append`, `should_render_multiline`, `truncate_display_string`
- 函数 `should_render_multiline(key, value) -> bool` （L320）：执行模块级业务逻辑。；调用：`isinstance`, `len`
- 函数 `truncate_display_string(value) -> str` （L331）：执行模块级业务逻辑。；调用：`len`
- 函数 `indent_multiline_text(value, prefix) -> str` （L338）：执行模块级业务逻辑。；调用：`join`, `lines.append`, `value.endswith`, `value.splitlines`
- 函数 `skill_tool_notice(tool_name, args, skill_runtime) -> str` （L347）：执行模块级业务逻辑。；调用：`args.get`, `compact_notice_value`, `get_skill_record_for_notice`, `join`, `lines.append`, `tool_name.startswith`
- 函数 `get_skill_record_for_notice(skill_runtime, tool_name) -> Any | None` （L384）：执行模块级业务逻辑。；调用：`callable`, `get_record`, `getattr`
- 函数 `compact_notice_value(value, limit) -> str` （L396）：执行模块级业务逻辑。；调用：`isinstance`, `join`, `json.dumps`, `len`, `value.split`
- 函数 `parse_tool_arguments(raw_args) -> dict[str, Any]` （L408）：执行模块级业务逻辑。；调用：`isinstance`, `json.loads`
- 函数 `compact_tool_metadata_value(value, limit) -> str` （L416）：执行模块级业务逻辑。；调用：`isinstance`, `join`, `json.dumps`, `len`, `split`, `str`
- 函数 `tool_call_metadata(tool_name, raw_args, output) -> dict[str, Any]` （L423）：执行模块级业务逻辑。；调用：`args.get`, `compact_tool_metadata_value`, `isinstance`, `json.loads`, `metadata.setdefault`, `output.lstrip`, `parse_tool_arguments`, `payload.get`, `startswith`
- 函数 `async execute_local_tool(registry, tool_name, raw_args, skill_runtime) -> str` （L458）：执行模块级业务逻辑。；调用：`isinstance`, `json.loads`, `print`, `registry.get`, `skill_tool_notice`, `tool.execute`, `tool.params_model.model_validate`
- 函数 `async stream_one_round(client, model, messages, tools, display, output_label) -> tuple[str, list[PendingToolCall], Any]` （L487）：执行模块级业务逻辑。；调用：`PendingToolCall`, `client.chat.completions.create`, `content_parts.append`, `getattr`, `hasattr`, `join`, `pending_tool_calls.setdefault`, `pretty_arguments`, `print`, `sorted`
- 函数 `async ask_deepseek(client, prompt, registry, tools, messages, skill_runtime, core_tool_schemas, workspace_tracker, memory_runtime, capability_router) -> tuple[str, list[dict[str, Any]]]` （L569）：执行模块级业务逻辑。；调用：`PromptRenderer.render_current_user_message`, `RuntimeContextBuilder`, `TokenUsageSummary`, `add_usage_to_summary`, `api_usage_to_dict`, `assistant_text.startswith`, `begin_turn`, `build`, `build_prompt_debug_snapshot`, `build_round_tools`, `callable`, `capability_router.route`, `context_budget_state_from_snapshot`, `end_skill_turn`, `end_turn`, `enumerate`
- 函数 `should_generate_summary(memory_runtime, messages, tools, prompt) -> bool` （L959）：执行模块级业务逻辑。；调用：`memory_runtime.prompt_budget_snapshot`
- 函数 `async summarize_engineering_state(client, model, messages) -> str` （L975）：执行模块级业务逻辑。；调用：`client.chat.completions.create`, `json.dumps`, `prompt_path.read_text`
- 函数 `truncate_tool_output(output) -> str` （L1011）：执行模块级业务逻辑。；调用：`len`
- 函数 `build_turn_temporary_system_messages(workspace_tracker) -> list[dict[str, Any]]` （L1018）：执行模块级业务逻辑。；调用：无
- 函数 `with_workspace_change_notice(messages, workspace_tracker) -> list[dict[str, Any]]` （L1022）：执行模块级业务逻辑。；调用：`list`
- 函数 `with_turn_temporary_system_messages(messages, temporary_system_messages) -> list[dict[str, Any]]` （L1026）：执行模块级业务逻辑。；调用：`get`, `list`
- 函数 `workspace_change_notice_content(workspace_tracker) -> str` （L1036）：执行模块级业务逻辑。；调用：无
- 函数 `async build_round_tools(prompt, default_tools, skill_runtime, core_tool_schemas, capability_router) -> list[dict[str, Any]]` （L1040）：执行模块级业务逻辑。；调用：`capability_router.build_tools_for_prompt`, `format_openai_tools`, `skill_runtime.build_tools_for_prompt_async`
- 函数 `async main(无) -> None` （L1056）：执行模块级业务逻辑。；调用：`AsyncOpenAI`, `ask_deepseek`, `client.close`, `create_default_registry`, `format_openai_tools`, `print`, `registry.get_all_schemas`

### `mycodingagent/llm_runtime/context.py`

- 模块：`mycodingagent.llm_runtime.context`
- 职责：模型请求、流式响应、工具循环、Prompt 上下文和 Token 统计。
- 内部依赖：`mycodingagent.memory.budget`
- 类 `class WorkspaceChanges`（L16）：封装该模块的状态与行为。
- 类 `class ContextBudgetState`（L22）：封装该模块的状态与行为。
- 类 `class RuntimeContextMetadata`（L30）：封装该模块的状态与行为。
- 类 `class RuntimeContext`（L36）：封装该模块的状态与行为。
  - `to_payload(self) -> dict[str, Any]` （L45）；调用：`asdict`
- 类 `class RenderedPrompt`（L50）：封装该模块的状态与行为。
- 类 `class RuntimeContextBuilder`（L63）：封装该模块的状态与行为。
  - `__init__(self, workspace_tracker, context_budget, capabilities, task_snapshot, recovery_hint) -> None` （L64）；调用：无
  - `build(self) -> RuntimeContext` （L79）；调用：`RuntimeContext`, `self._capability_payload`, `self._workspace_changes`
  - `_workspace_changes(self) -> WorkspaceChanges` （L88）；调用：`WorkspaceChanges`, `callable`, `consume`, `getattr`, `int`, `str`, `tuple`
  - `_capability_payload(self) -> dict[str, Any] | None` （L97）；调用：`callable`, `getattr`, `isinstance`, `to_runtime_payload`
- 类 `class PromptRenderer`（L108）：封装该模块的状态与行为。
  - `render_current_user_message(runtime_context, user_prompt) -> RenderedPrompt` （L110）；调用：`RenderedPrompt`, `estimate_tokens`, `hashlib.sha256`, `hexdigest`, `json.dumps`, `runtime_context.to_payload`, `runtime_context_json.encode`
- 函数 `render_current_turn_for_model(messages, current_turn_start, rendered_prompt) -> list[dict[str, Any]]` （L141）：执行模块级业务逻辑。；调用：`dict`, `get`, `len`, `range`
- 函数 `is_rendered_runtime_prompt(content) -> bool` （L157）：执行模块级业务逻辑。；调用：无
- 函数 `extract_user_request_from_rendered_prompt(content) -> str | None` （L161）：执行模块级业务逻辑。；调用：`content.find`, `is_rendered_runtime_prompt`, `len`, `strip`

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
  - `summary(self) -> MCPServerSummary` （L21）；调用：`MCPServerSummary`, `len`
- 类 `class MCPMetadataCache`（L39）：封装该模块的状态与行为。
  - `__init__(self) -> None` （L40）；调用：无
  - `sync_configs(self, configs) -> None` （L43）；调用：`MCPMetadataEntry`, `configs.items`, `self._entries.get`
  - `get(self, server) -> MCPMetadataEntry | None` （L53）；调用：`self._entries.get`
  - `servers(self) -> list[MCPServerSummary]` （L56）；调用：`entry.summary`, `self._entries.values`, `sorted`
  - `update_discovery(self, server, tools, resources, prompts, connected, error) -> None` （L59）；调用：`self._entries.get`, `time.time`
  - `mark_error(self, server, error) -> None` （L83）；调用：`self._entries.get`, `time.time`
  - `mark_available(self, server) -> None` （L92）；调用：`self._entries.get`, `time.time`
  - `unavailable_servers(self) -> list[str]` （L100）；调用：`self._entries.values`, `sorted`

### `mycodingagent/mcp_integration/config.py`

- 模块：`mycodingagent.mcp_integration.config`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：无
- 类 `class MCPPermissionConfig`（L11）：封装该模块的状态与行为。
- 类 `class MCPServerConfig`（L19）：封装该模块的状态与行为。
  - `searchable_terms(self) -> tuple[str, ...]` （L34）；调用：`tuple`
- 类 `class MCPConfigLoader`（L47）：Load project, user, and explicit MCP server configuration files.
  - `__init__(self, project_path, user_path, env_path_var) -> None` （L50）；调用：`Path.cwd`, `Path.home`
  - `load(self) -> dict[str, MCPServerConfig]` （L61）；调用：`merged.items`, `merged.update`, `self._load_path`, `self.config_paths`
  - `config_paths(self) -> list[Path]` （L68）；调用：`Path`, `expanduser`, `os.getenv`, `paths.append`
  - `_load_path(self, path) -> dict[str, MCPServerConfig]` （L75）；调用：`ValueError`, `_server_config_from_dict`, `isinstance`, `json.loads`, `path.exists`, `path.read_text`, `raw.get`, `servers.items`, `str`
- 函数 `_server_config_from_dict(name, data) -> MCPServerConfig | None` （L95）：执行模块级业务逻辑。；调用：`MCPServerConfig`, `ValueError`, `_permission_config`, `_string_tuple`, `bool`, `data.get`, `dict`, `items`, `str`, `strip`
- 函数 `_string_tuple(value) -> tuple[str, ...]` （L116）：执行模块级业务逻辑。；调用：`isinstance`, `str`, `strip`, `tuple`
- 函数 `_permission_config(value) -> MCPPermissionConfig` （L126）：执行模块级业务逻辑。；调用：`MCPPermissionConfig`, `_string_tuple`, `bool`, `isinstance`, `value.get`

### `mycodingagent/mcp_integration/execution.py`

- 模块：`mycodingagent.mcp_integration.execution`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：`mycodingagent.mcp_integration.models`
- 函数 `normalize_mcp_result(server, operation, name, result) -> MCPExecutionResult` （L9）：执行模块级业务逻辑。；调用：`MCPExecutionResult`, `_content_metadata`, `append`, `bool`, `getattr`, `isinstance`, `join`, `json.dumps`, `metadata.setdefault`, `other_parts.append`, `str`, `text_parts.append`
- 函数 `_content_metadata(item) -> dict[str, Any]` （L71）：执行模块级业务逻辑。；调用：`getattr`, `str`, `type`

### `mycodingagent/mcp_integration/hooks.py`

- 模块：`mycodingagent.mcp_integration.hooks`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：`mycodingagent.mcp_integration.policy`
- 类 `class MCPToolApprovalHook`（L11）：封装该模块的状态与行为。
  - `async approve(self, request) -> MCPApprovalDecision` （L12）；调用：`MCPApprovalDecision`
- 类 `class CLIApprovalHook`（L17）：封装该模块的状态与行为。
  - `async approve(self, request) -> MCPApprovalDecision` （L20）；调用：`MCPApprovalDecision`, `input`, `json.dumps`, `len`, `lower`, `print`, `strip`

### `mycodingagent/mcp_integration/manager.py`

- 模块：`mycodingagent.mcp_integration.manager`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：`mycodingagent.mcp_integration.cache`, `mycodingagent.mcp_integration.config`, `mycodingagent.mcp_integration.execution`, `mycodingagent.mcp_integration.models`
- 类 `class MCPClientManager`（L14）：Own real MCP protocol connections, discovery metadata, and protocol calls.
  - `__init__(self, config_loader, metadata_cache) -> None` （L17）；调用：`MCPConfigLoader`, `MCPMetadataCache`
  - `async initialize(self) -> None` （L30）；调用：`self.reload_config`
  - `reload_config(self) -> None` （L33）；调用：`self.config_loader.load`, `self.metadata_cache.sync_configs`
  - `async close(self) -> None` （L37）；调用：`contextlib.suppress`, `list`, `self._close_session`, `self._reconnect_task.cancel`, `self._reconnect_task.done`
  - `server_count(self) -> int` （L45）；调用：`len`
  - `connected_count(self) -> int` （L48）；调用：`self.available_count`
  - `available_count(self) -> int` （L51）；调用：`self.metadata_cache.servers`, `sum`
  - `list_servers(self) -> list[MCPServerSummary]` （L54）；调用：`self.metadata_cache.servers`
  - `async refresh_server(self, server) -> MCPServerSummary | None` （L57）；调用：`entry.summary`, `self._ensure_session`, `self._list_prompts_from_session`, `self._list_resources_from_session`, `self._list_tools_from_session`, `self._mark_server_unavailable`, `self.metadata_cache.get`, `self.metadata_cache.update_discovery`, `str`
  - `async list_tools(self, server) -> dict[str, Any]` （L78）；调用：`item.to_payload`, `self._ensure_discovered`, `self.metadata_cache.get`, `summary.to_payload`
  - `async list_resources(self, server) -> dict[str, Any]` （L87）；调用：`item.to_payload`, `self._ensure_discovered`, `self.metadata_cache.get`, `summary.to_payload`
  - `async list_prompts(self, server) -> dict[str, Any]` （L96）；调用：`item.to_payload`, `self._ensure_discovered`, `self.metadata_cache.get`, `summary.to_payload`
  - `async call_tool(self, server, tool, arguments) -> MCPExecutionResult` （L105）；调用：`MCPExecutionResult`, `normalize_mcp_result`, `self._ensure_session`, `self._mark_server_unavailable`, `self._unavailable_result`, `session.call_tool`, `str`
  - `async read_resource(self, server, uri) -> MCPExecutionResult` （L119）；调用：`MCPExecutionResult`, `normalize_mcp_result`, `self._ensure_session`, `self._mark_server_unavailable`, `self._unavailable_result`, `session.read_resource`, `str`
  - `async get_prompt(self, server, prompt, arguments) -> MCPExecutionResult` （L133）；调用：`MCPExecutionResult`, `normalize_mcp_result`, `self._ensure_session`, `self._mark_server_unavailable`, `self._unavailable_result`, `session.get_prompt`, `str`
  - `unavailable_servers(self) -> list[str]` （L147）；调用：`self.metadata_cache.unavailable_servers`
  - `schedule_reconnect_unavailable_servers(self) -> asyncio.Task | None` （L150）；调用：`asyncio.create_task`, `self._reconnect_task.done`, `self.reconnect_unavailable_servers`, `self.unavailable_servers`
  - `async reconnect_unavailable_servers(self) -> list[MCPServerSummary]` （L158）；调用：`restored.append`, `self.refresh_server`, `self.unavailable_servers`
  - `async _ensure_discovered(self, server) -> MCPServerSummary | None` （L166）；调用：`entry.summary`, `self.metadata_cache.get`, `self.refresh_server`
  - `async _ensure_session(self, server) -> Any` （L174）；调用：`ClientSession`, `RuntimeError`, `StdioServerParameters`, `contextlib.suppress`, `env.setdefault`, `env.update`, `list`, `os.environ.copy`, `self._sessions.get`, `session.initialize`, `session_context.__aenter__`, `session_context.__aexit__`
  - `async _close_session(self, server) -> None` （L207）；调用：`contextlib.suppress`, `self._session_contexts.pop`, `self._sessions.pop`, `session_context.__aexit__`, `stdio_context.__aexit__`
  - `async _mark_server_unavailable(self, server, error) -> None` （L218）；调用：`self._close_session`, `self.metadata_cache.mark_error`
  - `_unavailable_result(self, server, operation, name) -> MCPExecutionResult | None` （L222）；调用：`MCPExecutionResult`, `self.metadata_cache.get`
  - `async _list_tools_from_session(self, server) -> list[MCPItemSummary]` （L236）；调用：`_item_summary`, `getattr`, `self._ensure_session`, `session.list_tools`
  - `async _list_resources_from_session(self, server) -> list[MCPItemSummary]` （L241）；调用：`_item_summary`, `contextlib.suppress`, `getattr`, `self._ensure_session`, `session.list_resources`
  - `async _list_prompts_from_session(self, server) -> list[MCPItemSummary]` （L248）；调用：`_item_summary`, `contextlib.suppress`, `getattr`, `self._ensure_session`, `session.list_prompts`
- 函数 `_item_summary(item) -> MCPItemSummary` （L256）：执行模块级业务逻辑。；调用：`MCPItemSummary`, `getattr`, `str`

### `mycodingagent/mcp_integration/models.py`

- 模块：`mycodingagent.mcp_integration.models`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：无
- 类 `class MCPItemSummary`（L8）：封装该模块的状态与行为。
  - `to_payload(self) -> dict[str, Any]` （L13）；调用：`asdict`
- 类 `class MCPServerSummary`（L18）：封装该模块的状态与行为。
  - `to_payload(self) -> dict[str, Any]` （L33）；调用：`asdict`
- 类 `class MCPExecutionResult`（L38）：封装该模块的状态与行为。
  - `to_payload(self) -> dict[str, Any]` （L47）；调用：`asdict`

### `mycodingagent/mcp_integration/policy.py`

- 模块：`mycodingagent.mcp_integration.policy`
- 职责：MCP 配置、连接、元数据发现、调用和审批策略。
- 内部依赖：`mycodingagent.mcp_integration.config`
- 类 `class MCPApprovalRequest`（L16）：封装该模块的状态与行为。
- 类 `class MCPApprovalDecision`（L25）：封装该模块的状态与行为。
- 类 `class MCPToolPermissionPolicy`（L30）：封装该模块的状态与行为。
  - `classify(self, server_config, tool_name) -> MCPToolRisk` （L31）；调用：`_matches`, `any`, `lower`, `normalized.startswith`, `tool_name.strip`
  - `requires_approval(self, risk) -> bool` （L51）；调用：无
- 函数 `_matches(tool_name, configured) -> bool` （L55）：执行模块级业务逻辑。；调用：`any`, `item.strip`, `lower`

### `mycodingagent/memory/__init__.py`

- 模块：`mycodingagent.memory`
- 职责：会话持久化、上下文预算、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.memory.budget`, `mycodingagent.memory.checkpoint`, `mycodingagent.memory.compressor`, `mycodingagent.memory.context_objects`, `mycodingagent.memory.models`, `mycodingagent.memory.runtime`, `mycodingagent.memory.stores`
- 定义：无公开类或函数。

### `mycodingagent/memory/budget.py`

- 模块：`mycodingagent.memory.budget`
- 职责：会话持久化、上下文预算、虚拟化、检查点和恢复。
- 内部依赖：无
- 类 `class BudgetStage`（L9）：封装该模块的状态与行为。
- 类 `class PromptBudgetSnapshot`（L17）：封装该模块的状态与行为。
  - `to_prompt_text(self) -> str` （L28）；调用：无
- 类 `class PromptBudgetManager`（L43）：封装该模块的状态与行为。
  - `__init__(self, context_window, soft_ratio, working_ratio, emergency_ratio, reserved_reasoning_tokens, reserved_output_tokens, reserved_tool_tokens) -> None` （L44）；调用：无
  - `snapshot(self, messages, tools, current_prompt, extra_tokens) -> PromptBudgetSnapshot` （L63）；调用：`PromptBudgetSnapshot`, `estimate_tokens`, `max`, `self.stage_for_usage`
  - `stage_for_usage(self, usage_ratio) -> BudgetStage` （L93）；调用：无
- 函数 `estimate_tokens(value) -> int` （L103）：执行模块级业务逻辑。；调用：`isinstance`, `json.dumps`, `len`, `max`

### `mycodingagent/memory/checkpoint.py`

- 模块：`mycodingagent.memory.checkpoint`
- 职责：会话持久化、上下文预算、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.memory.budget`, `mycodingagent.memory.models`
- 类 `class TurnState`（L31）：封装该模块的状态与行为。
- 类 `class CheckpointDecision`（L40）：封装该模块的状态与行为。
- 类 `class RolloverResult`（L47）：封装该模块的状态与行为。
- 类 `class SnapshotGenerator`（L54）：封装该模块的状态与行为。
  - `generate_delta(self, session_id, previous_snapshot, new_messages, runtime_state, turn_start_index, turn_end_index) -> SnapshotDelta` （L55）；调用：无
  - `merge_snapshot(self, session_id, previous_snapshot, delta, runtime_state) -> ConversationSnapshot` （L67）；调用：无
- 类 `class StructuredSnapshotGenerator`（L78）：封装该模块的状态与行为。
  - `generate_delta(self, session_id, previous_snapshot, new_messages, runtime_state, turn_start_index, turn_end_index) -> SnapshotDelta` （L79）；调用：`SnapshotDelta`, `conclusions.append`, `context_refs.append`, `context_refs.extend`, `dedupe`, `extract_context_refs`, `extracted_action_lines`, `isinstance`, `looks_like_decision`, `message.get`, `message_text`, `metadata.get`
  - `merge_snapshot(self, session_id, previous_snapshot, delta, runtime_state) -> ConversationSnapshot` （L132）；调用：`ConversationSnapshot`, `build_summary`, `dict`, `infer_project_status`, `memory_state.update`, `merge_lists`, `runtime_state.get`, `uuid4`, `workspace_state.update`
- 类 `class CheckpointManager`（L185）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime, prompt_budget_manager, snapshot_generator) -> None` （L186）；调用：`StructuredSnapshotGenerator`
  - `should_checkpoint(self, turn_state, budget_snapshot) -> CheckpointDecision` （L199）；调用：`CheckpointDecision`, `max`
  - `create_session_delta(self, session_id, messages, previous_checkpoint_index, runtime_state) -> SnapshotDelta` （L219）；调用：`len`, `max`, `min`, `self.memory_runtime.store.get_latest_snapshot_for_session`, `self.snapshot_generator.generate_delta`
  - `create_incremental_snapshot(self, previous_snapshot, delta, runtime_state) -> ConversationSnapshot` （L240）；调用：`self.snapshot_generator.merge_snapshot`
  - `checkpoint_session(self, session_id, messages, runtime_state, trigger_reason, usage_ratio) -> ConversationSnapshot` （L253）；调用：`CheckpointRecord`, `len`, `self._latest_runtime_snapshot`, `self.create_incremental_snapshot`, `self.create_session_delta`, `self.memory_runtime.store.save_checkpoint_record`, `self.memory_runtime.store.save_conversation_snapshot`, `self.memory_runtime.store.save_snapshot_delta`, `uuid4`
  - `rollover_session(self, session_id, snapshot, system_prompt_source) -> RolloverResult` （L281）；调用：`RolloverResult`, `copy_system_message`, `format_snapshot_prompt`, `len`, `self.memory_runtime.store.ensure_session`, `self.memory_runtime.store.mark_session_historical`, `self.memory_runtime.store.save_messages`, `uuid4`
  - `restore_session_snapshot(self, session_id) -> ConversationSnapshot | None` （L316）；调用：`self.memory_runtime.store.get_conversation_snapshot`, `self.memory_runtime.store.get_historical_session`, `self.memory_runtime.store.touch_historical_session`
  - `_latest_runtime_snapshot(self, session_id) -> ConversationSnapshot | None` （L323）；调用：`getattr`, `self.memory_runtime.store.get_conversation_snapshot`, `self.memory_runtime.store.get_latest_snapshot_for_session`
- 函数 `format_snapshot_prompt(snapshot) -> str` （L332）：执行模块级业务逻辑。；调用：`asdict`, `join`, `json.dumps`, `lines.append`, `payload.get`
- 函数 `copy_system_message(system_prompt_source) -> dict[str, Any]` （L340）：执行模块级业务逻辑。；调用：`system_prompt_source.get`
- 函数 `message_text(message) -> str` （L346）：执行模块级业务逻辑。；调用：`content.strip`, `isinstance`, `json.dumps`, `message.get`
- 函数 `extracted_action_lines(text) -> list[str]` （L353）：执行模块级业务逻辑。；调用：`lines.append`, `raw_line.strip`, `text.splitlines`
- 函数 `looks_like_decision(line) -> bool` （L362）：执行模块级业务逻辑。；调用：`any`, `line.lower`
- 函数 `extract_context_refs(text) -> list[str]` （L367）：执行模块级业务逻辑。；调用：`line.split`, `refs.append`, `strip`, `text.splitlines`
- 函数 `infer_project_status(delta, previous_snapshot) -> str` （L375）：执行模块级业务逻辑。；调用：无
- 函数 `build_summary(user_intentions, conclusions, project_status) -> str` （L385）：执行模块级业务逻辑。；调用：`join`, `parts.append`
- 函数 `merge_lists(existing, incoming, limit) -> list[str]` （L395）：执行模块级业务逻辑。；调用：`dedupe`
- 函数 `dedupe(items) -> list[str]` （L399）：执行模块级业务逻辑。；调用：`join`, `result.append`, `seen.add`, `set`, `split`, `str`
- 函数 `truncate(text, limit) -> str` （L411）：执行模块级业务逻辑。；调用：`join`, `len`, `text.split`

### `mycodingagent/memory/compressor.py`

- 模块：`mycodingagent.memory.compressor`
- 职责：会话持久化、上下文预算、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.memory.models`
- 类 `class ToolOutputRef`（L23）：封装该模块的状态与行为。
- 类 `class ContextCompressor`（L31）：封装该模块的状态与行为。
  - `__init__(self, context_window, tool_preview_chars, recent_rounds_for_average, recent_messages_after_summary) -> None` （L32）；调用：无
  - `compress_messages(self, messages, tools, current_prompt, tool_output_refs, summary_text) -> CompressionResult` （L45）；调用：`CompressionResult`, `dict`, `estimate_size`, `json.dumps`, `len`, `max`, `sanitize_message_for_model`, `self._preview_tool_outputs`, `self._summarized_context`, `self.predict_next_context_size`
  - `should_compress(self, messages) -> bool` （L101）；调用：`self.predict_next_context_size`
  - `predict_next_context_size(self, messages, tools, current_prompt) -> int` （L104）；调用：`estimate_size`, `len`, `self.average_recent_output_size`
  - `average_recent_output_size(self, messages) -> int` （L118）；调用：`estimate_size`, `int`, `len`, `message.get`, `sum`
  - `_preview_tool_outputs(self, messages, refs, reproducible_only) -> list[dict[str, Any]]` （L128）；调用：`dict`, `get`, `message.get`, `refs.get`, `refs.values`, `result.append`, `sorted`, `tool_output_reference_text`
  - `_summarized_context(self, messages, summary_text) -> list[dict[str, Any]]` （L156）；调用：`message.get`
- 函数 `estimate_size(value) -> int` （L166）：执行模块级业务逻辑。；调用：`json.dumps`, `len`
- 函数 `sanitize_message_for_model(message) -> dict[str, Any]` （L170）：执行模块级业务逻辑。；调用：`message.items`
- 函数 `is_reproducible_tool(tool_name, output) -> bool` （L175）：执行模块级业务逻辑。；调用：`output.startswith`
- 函数 `tool_output_reference_text(ref) -> str` （L183）：执行模块级业务逻辑。；调用：`lower`, `str`

### `mycodingagent/memory/context_objects.py`

- 模块：`mycodingagent.memory.context_objects`
- 职责：会话持久化、上下文预算、虚拟化、检查点和恢复。
- 内部依赖：无
- 类 `class ContextContentType`（L12）：封装该模块的状态与行为。
- 类 `class ContextLifecycleState`（L19）：封装该模块的状态与行为。
- 类 `class RecoverableContextObject`（L27）：封装该模块的状态与行为。
  - `to_dict(self) -> dict[str, Any]` （L48）；调用：`asdict`
  - `from_dict(cls, payload) -> RecoverableContextObject` （L55）；调用：`ContextContentType`, `ContextLifecycleState`, `cls`, `data.get`, `dict`
- 函数 `build_recoverable_context(session_id, tool_call_id, tool_name, arguments_json, content, reproducible, token_count, metadata) -> RecoverableContextObject` （L64）：执行模块级业务逻辑。；调用：`RecoverableContextObject`, `extract_entities`, `extract_keywords`, `extract_related_files`, `infer_content_type`, `len`, `short_summary_for_tool_output`, `uuid4`
- 函数 `infer_content_type(content) -> ContextContentType` （L97）：执行模块级业务逻辑。；调用：`content.lstrip`, `json.loads`, `stripped.startswith`
- 函数 `short_summary_for_tool_output(tool_name, arguments_json, content) -> str` （L110）：执行模块级业务逻辑。；调用：`args.get`, `isinstance`, `json.loads`, `len`, `str`
- 函数 `extract_related_files(arguments_json, content) -> list[str]` （L125）：执行模块级业务逻辑。；调用：`args.get`, `candidates.append`, `candidates.extend`, `dedupe_keep_order`, `isinstance`, `json.loads`, `re.findall`
- 函数 `extract_keywords(tool_name, arguments_json, content) -> list[str]` （L140）：执行模块级业务逻辑。；调用：`dedupe_keep_order`, `re.findall`, `word.lower`, `words.extend`
- 函数 `extract_entities(content) -> list[str]` （L148）：执行模块级业务逻辑。；调用：`dedupe_keep_order`, `re.findall`
- 函数 `dedupe_keep_order(values) -> list[str]` （L153）：执行模块级业务逻辑。；调用：`result.append`, `seen.add`, `set`, `value.strip`

### `mycodingagent/memory/context_store.py`

- 模块：`mycodingagent.memory.context_store`
- 职责：会话持久化、上下文预算、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.memory.context_objects`
- 类 `class ExternalContextStore`（L8）：封装该模块的状态与行为。
  - `save_context(self, context, content) -> str` （L9）；调用：无
  - `load_context(self, context_id) -> str | None` （L12）；调用：无
  - `load_partial_context(self, context_id, offset, limit) -> tuple[str, int | None] | None` （L15）；调用：无
  - `delete_context(self, context_id) -> bool` （L18）；调用：无
  - `query_metadata(self, context_id) -> RecoverableContextObject | None` （L21）；调用：无
  - `search_metadata(self, session_id, query, limit) -> list[RecoverableContextObject]` （L24）；调用：无

### `mycodingagent/memory/message_filters.py`

- 模块：`mycodingagent.memory.message_filters`
- 职责：会话持久化、上下文预算、虚拟化、检查点和恢复。
- 内部依赖：无
- 函数 `is_skill_related_tool(tool_name) -> bool` （L15）：执行模块级业务逻辑。；调用：`tool_name.startswith`
- 函数 `persistent_assistant_tool_message(assistant_message) -> dict[str, Any] | None` （L19）：执行模块级业务逻辑。；调用：`assistant_message.get`, `list`

### `mycodingagent/memory/models.py`

- 模块：`mycodingagent.memory.models`
- 职责：会话持久化、上下文预算、虚拟化、检查点和恢复。
- 内部依赖：无
- 类 `class MemoryScope`（L10）：封装该模块的状态与行为。
- 类 `class MemoryEntry`（L17）：封装该模块的状态与行为。
- 类 `class MemoryQuery`（L27）：封装该模块的状态与行为。
- 类 `class CompressionResult`（L35）：封装该模块的状态与行为。
- 类 `class TokenUsageRecord`（L42）：封装该模块的状态与行为。
- 类 `class TokenUsageSummary`（L59）：封装该模块的状态与行为。
  - `add(self, record) -> None` （L67）；调用：无
- 类 `class ToolOutputRecord`（L77）：封装该模块的状态与行为。
- 类 `class ToolInvocationMetadata`（L90）：封装该模块的状态与行为。
- 类 `class HistoricalTurn`（L118）：封装该模块的状态与行为。
- 类 `class ConversationSnapshot`（L129）：封装该模块的状态与行为。
- 类 `class SnapshotDelta`（L147）：封装该模块的状态与行为。
- 类 `class CheckpointRecord`（L162）：封装该模块的状态与行为。
- 类 `class HistoricalSessionRef`（L173）：封装该模块的状态与行为。
- 类 `class SessionState`（L184）：封装该模块的状态与行为。
- 类 `class SessionListItem`（L199）：封装该模块的状态与行为。

### `mycodingagent/memory/runtime.py`

- 模块：`mycodingagent.memory.runtime`
- 职责：会话持久化、上下文预算、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.memory.budget`, `mycodingagent.memory.checkpoint`, `mycodingagent.memory.compressor`, `mycodingagent.memory.context_objects`, `mycodingagent.memory.message_filters`, `mycodingagent.memory.models`, `mycodingagent.memory.stores`, `mycodingagent.memory.working_context`, `mycodingagent.workspace.identity`
- 类 `class MemoryWriteTask`（L42）：封装该模块的状态与行为。
- 类 `class ContextMode`（L47）：封装该模块的状态与行为。
- 类 `class ContextRenderDecision`（L53）：封装该模块的状态与行为。
- 类 `class MemoryRuntime`（L62）：封装该模块的状态与行为。
  - `__init__(self, store, compressor, model, workspace_root) -> None` （L63）；调用：`CONFIG.memory.context_window_for`, `CheckpointManager`, `ContextCompressor`, `PromptBudgetManager`, `SQLiteMemoryStore`, `WorkingContext`, `self.start_async_writer`, `threading.Lock`, `workspace_fingerprint`, `workspace_label`, `workspace_root_text`
  - `start_async_writer(self) -> None` （L113）；调用：`asyncio.Queue`, `asyncio.get_running_loop`, `loop.create_task`, `self._run_writer`
  - `async _run_writer(self) -> None` （L123）；调用：`asyncio.get_running_loop`, `loop.run_in_executor`, `self._record_writer_error`, `self._write_queue.get`, `self._write_queue.task_done`
  - `async drain(self) -> None` （L136）；调用：`self._write_queue.join`
  - `async close(self) -> None` （L140）；调用：`contextlib.suppress`, `len`, `print`, `self._worker_task.cancel`, `self.await_pending_rollover`, `self.drain`
  - `_enqueue_write(self, description, callback) -> None` （L153）；调用：`MemoryWriteTask`, `self._record_writer_error`, `self._write_queue.put_nowait`, `task.callback`
  - `_record_writer_error(self, description, exc) -> None` （L163）；调用：`print`, `self._writer_errors.append`
  - `start_session(self, model) -> str` （L167）；调用：`self._current_turn_summaries.clear`, `self._enqueue_write`, `self.store.ensure_session`, `uuid4`
  - `get_current_session_id(self) -> str | None` （L186）；调用：无
  - `clear_current_session_id(self) -> None` （L189）；调用：`self._current_turn_summaries.clear`
  - `context_mode(self, session_id) -> ContextMode` （L194）；调用：`self._context_modes.get`
  - `is_context_virtualized(self, session_id) -> bool` （L200）；调用：`self.context_mode`
  - `force_context_virtualized(self, session_id) -> None` （L203）；调用：无
  - `save_messages(self, session_id, messages) -> None` （L208）；调用：`build_historical_turns`, `copy.deepcopy`, `self._enqueue_write`, `self._next_message_version`, `self._save_messages_if_current`
  - `save_messages_now(self, session_id, messages) -> None` （L217）；调用：`build_historical_turns`, `copy.deepcopy`, `self._next_message_version`, `self.store.ensure_session`, `self.store.save_historical_turns`, `self.store.save_messages`
  - `_next_message_version(self, session_id) -> int` （L232）；调用：`self._message_versions.get`
  - `_save_messages_if_current(self, session_id, messages, historical_turns, version) -> None` （L237）；调用：`self._message_versions.get`, `self.store.save_historical_turns`, `self.store.save_messages`
  - `load_session(self, session_id) -> SessionState | None` （L250）；调用：`self.store.load_session`, `self.store.touch_session`
  - `record_token_usage(self, session_id, prompt_tokens, prompt_cache_hit_tokens, prompt_cache_miss_tokens, completion_tokens, total_tokens, model, prompt_hash, tools_hash, metadata) -> TokenUsageSummary` （L257）；调用：`TokenUsageRecord`, `self.store.ensure_session`, `self.store.load_token_usage_summary`, `self.store.next_token_usage_request_index`, `self.store.save_token_usage`, `time`, `uuid4`
  - `load_token_usage_summary(self, session_id) -> TokenUsageSummary` （L297）；调用：`self.store.load_token_usage_summary`
  - `fork_session(self, source_session_id, model, messages) -> str | None` （L300）；调用：`copy.deepcopy`, `self.save_messages_now`, `self.store.ensure_session`, `self.store.load_session`, `self.store.save_file_state_snapshot`, `self.store.save_lrfu_snapshot`, `uuid4`
  - `touch_session(self, session_id) -> bool` （L340）；调用：`self.store.touch_session`
  - `delete_session(self, session_id) -> bool` （L343）；调用：`self._context_modes.pop`, `self._last_raw_rendered_messages.pop`, `self.store.delete_session`
  - `delete_sessions(self, session_ids) -> int` （L352）；调用：`self.delete_session`
  - `cleanup_expired_sessions(self) -> int` （L359）；调用：`max`, `self.store.delete_expired_sessions`
  - `list_sessions(self, limit, include_all) -> list[SessionListItem]` （L365）；调用：`self.store.list_sessions`
  - `list_migrated_workspace_sessions(self, limit) -> list[SessionListItem]` （L370）；调用：`self.store.list_sessions`
  - `save_tool_output(self, session_id, tool_call_id, tool_name, arguments, output, metadata) -> str` （L374）；调用：`ToolOutputRecord`, `ToolOutputRef`, `build_recoverable_context`, `estimate_tokens`, `is_reproducible_tool`, `len`, `self._enqueue_write`, `self.store.save_context`, `self.store.save_tool_output`, `time`
  - `get_tool_output(self, output_id) -> ToolOutputRecord | None` （L424）；调用：`self.store.get_tool_output`
  - `get_context_metadata(self, context_id) -> RecoverableContextObject | None` （L427）；调用：`self._context_metadata_refs.get`, `self.store.query_metadata`
  - `load_context(self, context_id) -> str | None` （L430）；调用：`self.store.load_context`
  - `load_partial_context(self, context_id, offset, limit) -> tuple[str, int | None] | None` （L433）；调用：`self.store.load_partial_context`
  - `search_context_metadata(self, session_id, query, limit) -> list[RecoverableContextObject]` （L436）；调用：`join`, `lower`, `query.split`, `self._context_metadata_refs.values`, `self.store.search_metadata`
  - `prompt_budget_snapshot(self, messages, tools, current_prompt, extra_tokens) -> PromptBudgetSnapshot` （L461）；调用：`self.budget_manager.snapshot`
  - `tool_output_prompt_content(self, output_id, output, messages, tools, current_prompt) -> str` （L476）；调用：`estimate_tokens`, `self.context_reference_text`, `self.force_context_virtualized`, `self.get_context_metadata`, `self.is_context_virtualized`, `self.prompt_budget_snapshot`, `self.working_context.add`
  - `context_reference_text(self, context_id, preview, snapshot) -> str` （L515）；调用：`join`, `lower`, `self._tool_output_refs.get`, `self.get_context_metadata`, `snapshot.to_prompt_text`, `str`
  - `prepare_messages_for_model(self, session_id, messages, tools, current_prompt, summary_text, persist_snapshot, current_turn_start) -> list[dict[str, Any]]` （L557）；调用：`self.render_messages_for_model`
  - `render_messages_for_model(self, session_id, messages, tools, current_prompt, current_turn_start, summary_text, persist_snapshot) -> list[dict[str, Any]]` （L578）；调用：`build_historical_turns`, `copy.deepcopy`, `format_virtualization_report`, `message.get`, `print`, `render_virtualized_messages`, `sanitize_messages_for_model`, `self._enqueue_write`, `self._select_context_render`, `self.prompt_budget_snapshot`, `self.store.load_historical_turns`, `self.store.save_context_snapshot`
  - `_select_context_render(self, session_id, raw_messages, virtualized_messages, tools, current_prompt) -> ContextRenderDecision` （L635）；调用：`ContextRenderDecision`, `estimate_raw_uncached_tokens`, `self._last_raw_rendered_messages.get`, `self._should_switch_to_virtualized`, `self.context_mode`, `self.prompt_budget_snapshot`
  - `_should_switch_to_virtualized(self, raw_snapshot, raw_uncached_tokens, virtualized_tokens) -> bool` （L673）；调用：`int`
  - `summarize_current_turn_message(self, message_id, summary, reason, focus, context_id) -> ToolInvocationMetadata` （L686）；调用：`ToolInvocationMetadata`, `ValueError`, `estimate_tokens`, `extract_keywords_from_text`, `int`, `json.dumps`, `len`, `previous.get`, `reason.strip`, `self._current_turn_summaries.get`, `stable_hash`, `stable_id`
  - `save_lrfu_snapshot(self, session_id, skill_runtime) -> None` （L745）；调用：`callable`, `copy.deepcopy`, `getattr`, `self._enqueue_write`, `self.store.save_lrfu_snapshot`, `to_dict`
  - `save_file_state_snapshot(self, session_id, file_state_cache) -> None` （L757）；调用：`callable`, `copy.deepcopy`, `getattr`, `self._enqueue_write`, `self.store.save_file_state_snapshot`, `to_dict`
  - `async on_turn_completed(self, messages, skill_runtime, file_state_cache, workspace_tracker, system_prompt_source, tools, current_prompt) -> RolloverResult` （L769）；调用：`RolloverResult`, `TurnState`, `asyncio.create_task`, `copy.deepcopy`, `has_pending_tool_call`, `len`, `self._checkpoint_runtime_state`, `self._pending_rollover_task.done`, `self._perform_rollover`, `self._record_writer_error`, `self.checkpoint_manager.should_checkpoint`, `self.drain`
  - `async _perform_rollover(self, session_id, messages, runtime_state, trigger_reason, usage_ratio, system_prompt_source) -> RolloverResult` （L838）；调用：`RolloverResult`, `asyncio.get_running_loop`, `loop.run_in_executor`, `self._record_writer_error`, `self.create_checkpoint`, `self.rollover_to_new_session`
  - `create_checkpoint(self, session_id, messages, runtime_state, trigger_reason, usage_ratio) -> ConversationSnapshot` （L873）；调用：`self.checkpoint_manager.checkpoint_session`
  - `rollover_to_new_session(self, session_id, snapshot, system_prompt_source) -> RolloverResult` （L890）；调用：`self.checkpoint_manager.rollover_session`
  - `restore_historical_session_snapshot(self, session_id) -> ConversationSnapshot | None` （L903）；调用：`self.checkpoint_manager.restore_session_snapshot`
  - `async await_pending_rollover(self) -> RolloverResult` （L906）；调用：`RolloverResult`, `isinstance`
  - `_checkpoint_runtime_state(self, skill_runtime, file_state_cache, workspace_tracker) -> dict[str, Any]` （L916）；调用：`getattr`, `list`, `self._context_metadata_refs.keys`, `snapshot_dict`
  - `load_lrfu_snapshot(self, session_id, skill_runtime) -> None` （L941）；调用：`callable`, `getattr`, `load_dict`, `self.store.load_session`
  - `load_file_state_snapshot(self, session_id, file_state_cache, workspace_tracker) -> dict` （L952）；调用：`callable`, `file_state_paths`, `getattr`, `load_dict`, `mark_paths_for_recheck`, `self.store.load_session`
  - `save_short_term(self, content, metadata) -> MemoryEntry` （L971）；调用：`MemoryEntry`, `json.dumps`, `messages.append`, `self._enqueue_write`, `self.start_session`, `self.store.load_messages`, `self.store.save_messages`
  - `save_long_term(self, content, metadata) -> MemoryEntry` （L984）；调用：`MemoryEntry`
  - `recall_short_term(self, query) -> list[MemoryEntry]` （L987）；调用：无
  - `recall_long_term(self, query) -> list[MemoryEntry]` （L990）；调用：无
  - `compress_context(self, messages) -> CompressionResult` （L993）；调用：`self.compressor.compress_messages`
  - `should_compress_context(self, messages) -> bool` （L996）；调用：`self.compressor.should_compress`
- 函数 `format_compression_report(result) -> str` （L1000）：执行模块级业务逻辑。；调用：`float`, `int`, `metadata.get`
- 函数 `format_virtualization_report(snapshot, decision) -> str` （L1017）：执行模块级业务逻辑。；调用：`join`, `lines.extend`, `lower`, `str`
- 函数 `estimate_raw_uncached_tokens(previous_messages, current_messages) -> int` （L1049）：执行模块级业务逻辑。；调用：`enumerate`, `estimate_tokens`, `len`, `min`, `zip`
- 函数 `split_historical_and_current(messages, current_turn_start) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]` （L1065）：执行模块级业务逻辑。；调用：`get`, `len`, `max`, `min`
- 函数 `insert_budget_notice(messages, notice) -> list[dict[str, Any]]` （L1077）：执行模块级业务逻辑。；调用：`get`
- 函数 `format_budget_notice(snapshot) -> str` （L1084）：执行模块级业务逻辑。；调用：`join`, `lines.append`, `lines.extend`
- 函数 `render_virtualized_messages(system_messages, historical_messages, session_id, historical_turns, current_messages, current_summaries) -> list[dict[str, Any]]` （L1104）：执行模块级业务逻辑。；调用：`apply_current_summaries`, `render_historical_topology`, `rendered.extend`
- 函数 `render_historical_topology(session_id, messages, turns) -> list[dict[str, Any]]` （L1120）：执行模块级业务逻辑。；调用：`build_historical_turns`, `dict`, `get`, `message.get`, `metadata_by_call_id.get`, `render_historical_assistant_message`, `render_historical_tool_message`, `rendered.append`, `str`
- 函数 `render_historical_assistant_message(message) -> dict[str, Any]` （L1148）：执行模块级业务逻辑。；调用：`copy.deepcopy`, `message.get`
- 函数 `render_historical_tool_message(message, metadata) -> dict[str, Any]` （L1157）：执行模块级业务逻辑。；调用：`historical_tool_content`, `message.get`, `str`
- 函数 `historical_tool_content(metadata, message) -> str` （L1170）：执行模块级业务逻辑。；调用：`json.dumps`, `message.get`, `tool_metadata_prompt_dict`
- 函数 `tool_metadata_prompt_dict(metadata) -> dict[str, Any]` （L1197）：执行模块级业务逻辑。；调用：无
- 函数 `apply_current_summaries(messages, summaries) -> list[dict[str, Any]]` （L1229）：执行模块级业务逻辑。；调用：`dict`, `isinstance`, `message.get`, `metadata.get`, `replacement.get`, `result.append`, `str`, `summaries.get`
- 函数 `sanitize_messages_for_model(messages) -> list[dict[str, Any]]` （L1263）：执行模块级业务逻辑。；调用：`message.items`
- 函数 `build_historical_turns(session_id, messages) -> list[HistoricalTurn]` （L1271）：执行模块级业务逻辑。；调用：`HistoricalTurn`, `build_tool_invocation_metadata`, `current.get`, `enumerate`, `get`, `isinstance`, `len`, `message.get`, `message_content_text`, `pending_calls.get`, `stable_id`, `str`, `tool_call.get`, `tool_metadata.append`, `turns.append`
- 函数 `build_tool_invocation_metadata(session_id, turn_id, turn_index, call_index, tool_call_id, tool_name, arguments, tool_message) -> ToolInvocationMetadata` （L1353）：执行模块级业务逻辑。；调用：`ToolInvocationMetadata`, `bool`, `estimate_tokens`, `extract_keywords_from_text`, `extract_reference_paths`, `extract_related_files_from_text`, `extract_tool_intent`, `get`, `infer_prompt_content_type`, `is_error_text`, `is_reproducible_tool`, `is_skill_related_tool`, `isinstance`, `join`, `len`, `message_content_text`
- 函数 `message_content_text(message) -> str` （L1404）：执行模块级业务逻辑。；调用：`isinstance`, `json.dumps`, `message.get`
- 函数 `stable_hash(text) -> str` （L1411）：执行模块级业务逻辑。；调用：`hashlib.sha256`, `hexdigest`, `text.encode`
- 函数 `stable_id(*parts) -> str` （L1415）：执行模块级业务逻辑。；调用：`join`, `stable_hash`
- 函数 `truncate_one_line(text, max_chars) -> str` （L1419）：执行模块级业务逻辑。；调用：`join`, `len`, `max`, `split`, `str`
- 函数 `parse_arguments_object(arguments) -> dict[str, Any]` （L1426）：执行模块级业务逻辑。；调用：`isinstance`, `json.loads`
- 函数 `extract_tool_intent(tool_name, arguments, metadata) -> str` （L1434）：执行模块级业务逻辑。；调用：`metadata.get`, `parse_arguments_object`, `parsed.get`, `str`, `truncate_one_line`
- 函数 `extract_keywords_from_text(text) -> list[str]` （L1448）：执行模块级业务逻辑。；调用：`dedupe_keep_order`, `re.findall`, `word.lower`
- 函数 `extract_related_files_from_text(text) -> list[str]` （L1454）：执行模块级业务逻辑。；调用：`dedupe_keep_order`, `re.findall`
- 函数 `extract_reference_paths(arguments, content) -> list[str]` （L1460）：执行模块级业务逻辑。；调用：`dedupe_keep_order`, `re.findall`
- 函数 `dedupe_keep_order(values) -> list[str]` （L1465）：执行模块级业务逻辑。；调用：`result.append`, `seen.add`, `set`, `value.strip`
- 函数 `tool_short_summary(tool_name, arguments, content, context_id, intent) -> str` （L1477）：执行模块级业务逻辑。；调用：`is_error_text`, `join`, `len`, `parse_arguments_object`, `parsed.get`, `parts.append`, `str`, `truncate_one_line`
- 函数 `skill_invocation_kind(tool_name) -> str` （L1498）：执行模块级业务逻辑。；调用：`tool_name.startswith`
- 函数 `infer_prompt_content_type(content) -> str` （L1510）：执行模块级业务逻辑。；调用：`content.lstrip`, `is_error_text`, `json.loads`, `stripped.startswith`
- 函数 `is_error_text(text) -> bool` （L1523）：执行模块级业务逻辑。；调用：`text.startswith`
- 函数 `file_state_paths(snapshot) -> list[str]` （L1527）：执行模块级业务逻辑。；调用：`isinstance`, `item.get`, `snapshot.get`
- 函数 `has_pending_tool_call(messages) -> bool` （L1536）：执行模块级业务逻辑。；调用：`bool`, `last_message.get`
- 函数 `snapshot_dict(value) -> dict` （L1543）：执行模块级业务逻辑。；调用：`callable`, `getattr`, `isinstance`, `to_dict`

### `mycodingagent/memory/session_switch.py`

- 模块：`mycodingagent.memory.session_switch`
- 职责：会话持久化、上下文预算、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.memory`
- 函数 `has_conversation_content(messages) -> bool` （L8）：执行模块级业务逻辑。；调用：`any`, `bool`, `message.get`
- 函数 `save_current_session_if_needed(memory_runtime, messages, skill_runtime, file_state_cache) -> str` （L16）：执行模块级业务逻辑。；调用：`has_conversation_content`, `memory_runtime.get_current_session_id`, `memory_runtime.save_file_state_snapshot`, `memory_runtime.save_lrfu_snapshot`, `memory_runtime.save_messages`, `memory_runtime.start_session`

### `mycodingagent/memory/stores.py`

- 模块：`mycodingagent.memory.stores`
- 职责：会话持久化、上下文预算、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.memory.context_objects`, `mycodingagent.memory.models`
- 类 `class SQLiteMemoryStore`（L25）：封装该模块的状态与行为。
  - `__init__(self, db_path) -> None` （L26）；调用：`Path`, `expanduser`, `self._init_db`, `self.db_path.parent.mkdir`
  - `_connect(self) -> sqlite3.Connection` （L31）；调用：`sqlite3.connect`
  - `_init_db(self) -> None` （L36）；调用：`conn.execute`, `self._connect`, `self._ensure_column`
  - `_ensure_column(self, conn, table, column, definition) -> None` （L258）；调用：`conn.execute`, `fetchall`
  - `ensure_session(self, session_id, model, status, workspace_root, workspace_label, workspace_fingerprint) -> None` （L263）；调用：`conn.execute`, `self._connect`, `time`
  - `save_messages(self, session_id, messages) -> None` （L307）；调用：`conn.execute`, `conn.executemany`, `enumerate`, `json.dumps`, `message.get`, `self._connect`, `self._session_status`, `str`, `time`
  - `_session_status(self, conn, session_id) -> str | None` （L334）；调用：`conn.execute`, `fetchone`, `str`
  - `load_messages(self, session_id) -> list[dict]` （L338）；调用：`conn.execute`, `fetchall`, `json.loads`, `self._connect`
  - `save_historical_turns(self, session_id, turns) -> None` （L350）；调用：`conn.execute`, `conn.executemany`, `int`, `json.dumps`, `self._connect`, `self._session_status`, `time`
  - `save_token_usage(self, record) -> None` （L420）；调用：`conn.execute`, `json.dumps`, `self._connect`, `self._session_status`, `time`
  - `next_token_usage_request_index(self, session_id) -> int` （L456）；调用：`conn.execute`, `fetchone`, `int`, `self._connect`
  - `load_token_usage_summary(self, session_id) -> TokenUsageSummary` （L464）；调用：`TokenUsageSummary`, `conn.execute`, `fetchone`, `int`, `self._connect`
  - `load_historical_turns(self, session_id, limit) -> list[HistoricalTurn]` （L491）；调用：`HistoricalTurn`, `append`, `conn.execute`, `fetchall`, `float`, `int`, `max`, `metadata_by_turn.get`, `metadata_by_turn.setdefault`, `params.append`, `self._connect`, `tool_metadata_from_row`
  - `search_historical_turns(self, session_id, query, limit) -> list[HistoricalTurn]` （L528）；调用：`haystack_parts.extend`, `join`, `json.dumps`, `len`, `lower`, `matches.append`, `query.split`, `self.load_historical_turns`
  - `list_sessions(self, limit, workspace_root, workspace_fingerprint) -> list[SessionListItem]` （L554）；调用：`SessionListItem`, `conn.execute`, `fetchall`, `float`, `items.append`, `join`, `len`, `params.append`, `self._connect`, `self.load_messages`, `session_preview`, `tuple`
  - `save_tool_output(self, record) -> None` （L600）；调用：`conn.execute`, `int`, `self._connect`
  - `save_context(self, context, content) -> str` （L623）；调用：`conn.execute`, `int`, `json.dumps`, `self._connect`
  - `load_context(self, context_id) -> str | None` （L661）；调用：`conn.execute`, `fetchone`, `self._connect`, `self._touch_context`
  - `load_partial_context(self, context_id, offset, limit) -> tuple[str, int | None] | None` （L672）；调用：`conn.execute`, `fetchone`, `len`, `max`, `min`, `self._connect`, `self._touch_context`
  - `delete_context(self, context_id) -> bool` （L686）；调用：`conn.execute`, `self._connect`
  - `query_metadata(self, context_id) -> RecoverableContextObject | None` （L691）；调用：`conn.execute`, `context_from_row`, `fetchone`, `self._connect`
  - `search_metadata(self, session_id, query, limit) -> list[RecoverableContextObject]` （L699）；调用：`conn.execute`, `context_from_row`, `fetchall`, `join`, `len`, `lower`, `matches.append`, `max`, `query.split`, `self._connect`
  - `_touch_context(self, conn, context_id) -> None` （L731）；调用：`conn.execute`, `time`
  - `get_tool_output(self, output_id) -> ToolOutputRecord | None` （L741）；调用：`ToolOutputRecord`, `bool`, `conn.execute`, `fetchone`, `self._connect`
  - `save_context_snapshot(self, snapshot_id, session_id, compressed_messages, summary_text, pressure_ratio) -> None` （L761）；调用：`conn.execute`, `json.dumps`, `self._connect`, `time`
  - `save_lrfu_snapshot(self, session_id, lrfu) -> None` （L792）；调用：`conn.execute`, `json.dumps`, `self._connect`, `time`
  - `save_file_state_snapshot(self, session_id, file_state) -> None` （L804）；调用：`conn.execute`, `json.dumps`, `self._connect`, `time`
  - `touch_session(self, session_id) -> bool` （L816）；调用：`conn.execute`, `self._connect`, `self._session_status`, `time`
  - `delete_session(self, session_id) -> bool` （L839）；调用：`conn.execute`, `self._connect`
  - `delete_expired_sessions(self, max_age_seconds) -> int` （L855）；调用：`conn.execute`, `fetchall`, `len`, `self._connect`, `time`
  - `load_session(self, session_id) -> SessionState | None` （L878）；调用：`SessionState`, `conn.execute`, `fetchone`, `float`, `json.loads`, `self._connect`, `self.load_historical_turns`, `self.load_messages`, `self.load_token_usage_summary`
  - `save_conversation_snapshot(self, snapshot) -> None` （L911）；调用：`asdict`, `conn.execute`, `json.dumps`, `self._connect`
  - `get_conversation_snapshot(self, snapshot_id) -> ConversationSnapshot | None` （L931）；调用：`conn.execute`, `conversation_snapshot_from_dict`, `fetchone`, `json.loads`, `self._connect`
  - `get_latest_snapshot_for_session(self, session_id) -> ConversationSnapshot | None` （L941）；调用：`conn.execute`, `conversation_snapshot_from_dict`, `fetchone`, `json.loads`, `self._connect`
  - `save_snapshot_delta(self, delta) -> None` （L956）；调用：`asdict`, `conn.execute`, `json.dumps`, `self._connect`
  - `save_checkpoint_record(self, record) -> None` （L977）；调用：`conn.execute`, `self._connect`
  - `mark_session_historical(self, session_id, snapshot_id, summary, context_refs) -> None` （L998）；调用：`conn.execute`, `fetchone`, `float`, `json.dumps`, `self._connect`, `time`
  - `get_historical_session(self, session_id) -> HistoricalSessionRef | None` （L1039）；调用：`conn.execute`, `fetchone`, `historical_session_from_row`, `self._connect`
  - `list_historical_sessions(self, limit) -> list[HistoricalSessionRef]` （L1047）；调用：`conn.execute`, `fetchall`, `historical_session_from_row`, `self._connect`
  - `touch_historical_session(self, session_id) -> bool` （L1059）；调用：`conn.execute`, `self._connect`, `time`
- 函数 `session_preview(messages, max_chars) -> str` （L1077）：执行模块级业务逻辑。；调用：`content.strip`, `lower`, `message.get`, `message_content_to_text`, `reversed`, `truncate_one_line`
- 函数 `message_content_to_text(content) -> str` （L1092）：执行模块级业务逻辑。；调用：`isinstance`, `json.dumps`
- 函数 `truncate_one_line(text, max_chars) -> str` （L1098）：执行模块级业务逻辑。；调用：`join`, `len`, `split`, `text.strip`
- 函数 `context_from_row(row) -> RecoverableContextObject` （L1105）：执行模块级业务逻辑。；调用：`ContextContentType`, `ContextLifecycleState`, `RecoverableContextObject`, `bool`, `float`, `int`, `json.loads`
- 函数 `tool_metadata_from_row(row) -> ToolInvocationMetadata` （L1129）：执行模块级业务逻辑。；调用：`ToolInvocationMetadata`, `bool`, `float`, `int`, `json.loads`
- 函数 `conversation_snapshot_from_dict(data) -> ConversationSnapshot` （L1158）：执行模块级业务逻辑。；调用：`ConversationSnapshot`, `data.get`, `dict`, `float`, `list`, `str`, `time`
- 函数 `historical_session_from_row(row) -> HistoricalSessionRef` （L1177）：执行模块级业务逻辑。；调用：`HistoricalSessionRef`, `float`, `json.loads`

### `mycodingagent/memory/working_context.py`

- 模块：`mycodingagent.memory.working_context`
- 职责：会话持久化、上下文预算、虚拟化、检查点和恢复。
- 内部依赖：`mycodingagent.memory.context_objects`
- 类 `class WorkingContext`（L9）：封装该模块的状态与行为。
  - `add(self, context) -> None` （L12）；调用：无
  - `evict(self, context_id) -> RecoverableContextObject | None` （L16）；调用：`self.contexts.pop`
  - `archive(self, context_id) -> RecoverableContextObject | None` （L22）；调用：`self.contexts.pop`
  - `metadata(self) -> list[dict]` （L28）；调用：`context.to_dict`, `self.contexts.values`
  - `clear(self) -> None` （L31）；调用：`self.contexts.clear`, `self.contexts.values`

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
- 类 `class AgentRuntime`（L9）：封装该模块的状态与行为。
  - `async run(self, request) -> AgentResult` （L10）；调用：无
- 类 `class DirectResponder`（L13）：封装该模块的状态与行为。
  - `async respond(self, prompt, messages) -> tuple[str, list[dict[str, Any]]]` （L14）；调用：无
- 类 `class RuntimeEventSink`（L21）：封装该模块的状态与行为。
  - `async emit(self, event) -> None` （L22）；调用：无
- 类 `class MultiAgentSettings`（L25）：封装该模块的状态与行为。
- 类 `class ConversationRecorder`（L38）：封装该模块的状态与行为。
  - `start_session(self, model) -> str` （L39）；调用：无
  - `save_messages(self, session_id, messages) -> None` （L41）；调用：无
- 类 `class RunJournal`（L44）：封装该模块的状态与行为。
  - `save(self, record) -> str` （L45）；调用：无
  - `latest(self) -> dict[str, Any] | None` （L47）；调用：无
  - `get(self, run_id) -> dict[str, Any] | None` （L49）；调用：无
- 类 `class ArchitectureApprovalDecision`（L53）：封装该模块的状态与行为。
- 类 `class ArchitectureApprovalPort`（L58）：封装该模块的状态与行为。
  - `async approve(self, proposal) -> ArchitectureApprovalDecision` （L59）；调用：无

### `mycodingagent/multi_agent/domain/models.py`

- 模块：`mycodingagent.multi_agent.domain.models`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：无
- 类 `class AgentRole`（L8）：封装该模块的状态与行为。
- 类 `class WorkflowStatus`（L17）：封装该模块的状态与行为。
- 类 `class WorkflowMode`（L23）：封装该模块的状态与行为。
- 函数 `_strings(value) -> tuple[str, ...]` （L29）：执行模块级业务逻辑。；调用：`isinstance`, `str`, `strip`, `tuple`
- 类 `class QueryDecision`（L36）：封装该模块的状态与行为。
  - `needs_planning(self) -> bool` （L42）；调用：无
  - `from_mapping(cls, value, fallback_query) -> QueryDecision` （L46）；调用：`WorkflowMode`, `bool`, `cls`, `lower`, `str`, `strip`, `value.get`
- 类 `class AuditScope`（L62）：封装该模块的状态与行为。
  - `from_mapping(cls, value, index) -> AuditScope` （L68）；调用：`_strings`, `cls`, `str`, `strip`, `value.get`
- 类 `class FunctionNode`（L77）：封装该模块的状态与行为。
  - `from_mapping(cls, value) -> FunctionNode` （L87）；调用：`_strings`, `cls`, `str`, `strip`, `value.get`
- 类 `class CallEdge`（L100）：封装该模块的状态与行为。
  - `from_mapping(cls, value) -> CallEdge` （L108）；调用：`cls`, `float`, `max`, `min`, `str`, `strip`, `value.get`
- 类 `class ProjectAuditReport`（L123）：封装该模块的状态与行为。
  - `from_mapping(cls, value) -> ProjectAuditReport` （L133）；调用：`CallEdge.from_mapping`, `FunctionNode.from_mapping`, `_strings`, `cls`, `isinstance`, `str`, `strip`, `tuple`, `value.get`
  - `to_dict(self) -> dict[str, Any]` （L153）；调用：`asdict`
- 类 `class ArchitectureProposal`（L158）：封装该模块的状态与行为。
  - `from_mapping(cls, value) -> ArchitectureProposal` （L168）；调用：`_strings`, `bool`, `cls`, `str`, `strip`, `value.get`
  - `to_dict(self) -> dict[str, Any]` （L179）；调用：`asdict`
- 类 `class WorkItem`（L184）：封装该模块的状态与行为。
  - `from_mapping(cls, value, index) -> WorkItem` （L193）；调用：`_strings`, `cls`, `str`, `strip`, `value.get`
  - `to_dict(self) -> dict[str, Any]` （L203）；调用：`asdict`
- 类 `class VerificationReport`（L208）：封装该模块的状态与行为。
  - `from_mapping(cls, value) -> VerificationReport` （L216）；调用：`_strings`, `bool`, `cls`, `isinstance`, `str`, `strip`, `tuple`, `value.get`
  - `to_dict(self) -> dict[str, Any]` （L226）；调用：`asdict`
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
  - `__init__(self, api_client, registry, tools, core_tool_schemas, skill_runtime, workspace_tracker, memory_runtime, capability_router) -> None` （L12）；调用：无
  - `async respond(self, prompt, messages) -> tuple[str, list[dict[str, Any]]]` （L33）；调用：`agent_client.ask_deepseek`

### `mycodingagent/multi_agent/infrastructure/events.py`

- 模块：`mycodingagent.multi_agent.infrastructure.events`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.domain.contracts`, `mycodingagent.multi_agent.domain.models`
- 类 `class RuntimeEventHook`（L9）：封装该模块的状态与行为。
  - `async emit(self, event) -> None` （L10）；调用：无
- 类 `class CLIRuntimeEventHook`（L14）：封装该模块的状态与行为。
  - `async emit(self, event) -> None` （L15）；调用：`event.metadata.items`, `join`, `print`
- 类 `class ArchitectureApprovalHook`（L23）：封装该模块的状态与行为。
  - `async approve(self, proposal) -> ArchitectureApprovalDecision` （L24）；调用：`ArchitectureApprovalDecision`
- 类 `class CLIArchitectureApprovalHook`（L28）：封装该模块的状态与行为。
  - `async approve(self, proposal) -> ArchitectureApprovalDecision` （L29）；调用：`ArchitectureApprovalDecision`, `input`, `lower`, `print`, `strip`
- 类 `class StaticArchitectureApprovalHook`（L51）：封装该模块的状态与行为。
  - `__init__(self, allowed) -> None` （L52）；调用：无
  - `async approve(self, proposal) -> ArchitectureApprovalDecision` （L55）；调用：`ArchitectureApprovalDecision`
- 类 `class CollectingRuntimeEventHook`（L60）：封装该模块的状态与行为。
  - `__init__(self) -> None` （L61）；调用：无
  - `async emit(self, event) -> None` （L64）；调用：`self.events.append`

### `mycodingagent/multi_agent/infrastructure/history_tool.py`

- 模块：`mycodingagent.multi_agent.infrastructure.history_tool`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.domain.contracts`, `mycodingagent.tool_runtime.base`
- 类 `class GetMultiAgentRunParams`（L11）：封装该模块的状态与行为。
- 类 `class GetMultiAgentRun`（L18）：封装该模块的状态与行为。
  - `__init__(self, journal) -> None` （L29）；调用：无
  - `async execute(self, params) -> ToolResult` （L32）；调用：`ToolResult`, `json.dumps`, `self._journal.get`, `self._journal.latest`

### `mycodingagent/multi_agent/infrastructure/path_locks.py`

- 模块：`mycodingagent.multi_agent.infrastructure.path_locks`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.infrastructure.permissions`
- 类 `class PathLockManager`（L11）：封装该模块的状态与行为。
  - `__init__(self, workspace_root) -> None` （L12）；调用：`asyncio.Lock`, `workspace_root.resolve`
  - `async acquire(self, paths) -> AsyncIterator[None]` （L18）；调用：`lock.acquire`, `lock.release`, `normalize_workspace_path`, `reversed`, `self._get_locks`, `sorted`, `str`
  - `async _get_locks(self, keys) -> list[asyncio.Lock]` （L29）；调用：`asyncio.Lock`, `self._locks.setdefault`

### `mycodingagent/multi_agent/infrastructure/permissions.py`

- 模块：`mycodingagent.multi_agent.infrastructure.permissions`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.tool_runtime`
- 类 `class ToolPermissionError`（L11）：封装该模块的状态与行为。
- 类 `class ToolAccessPolicy`（L22）：封装该模块的状态与行为。
  - `schemas(self, registry) -> list[dict[str, Any]]` （L28）；调用：`registry.list_tools`, `schemas.append`, `tool.get_schema`
  - `authorize(self, tool_name, arguments) -> None` （L43）；调用：`ToolPermissionError`, `arguments.get`, `is_validation_command`, `self._authorize_write_path`, `str`, `strip`
  - `_authorize_write_path(self, raw_path) -> None` （L55）；调用：`ToolPermissionError`, `any`, `join`, `normalize_workspace_path`, `str`
- 函数 `normalize_workspace_path(raw_path, workspace_root) -> Path` （L67）：执行模块级业务逻辑。；调用：`Path`, `len`, `path.is_absolute`, `path.resolve`, `raw_path.strip`, `text.startswith`, `workspace_root.resolve`
- 函数 `is_validation_command(command) -> bool` （L80）：执行模块级业务逻辑。；调用：`Path`, `_allowed_validation_subcommand`, `any`, `len`, `shlex.split`
- 函数 `_allowed_validation_subcommand(executable, args) -> bool` （L105）：执行模块级业务逻辑。；调用：`any`, `bool`

### `mycodingagent/multi_agent/infrastructure/run_journal.py`

- 模块：`mycodingagent.multi_agent.infrastructure.run_journal`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：无
- 类 `class JsonRunJournal`（L10）：封装该模块的状态与行为。
  - `__init__(self, root) -> None` （L11）；调用：`Lock`
  - `save(self, record) -> str` （L15）；调用：`json.dumps`, `record.get`, `self.root.mkdir`, `str`, `target.write_text`, `uuid4`, `write_text`
  - `latest(self) -> dict[str, Any] | None` （L25）；调用：`marker.exists`, `marker.read_text`, `self.get`, `strip`
  - `get(self, run_id) -> dict[str, Any] | None` （L31）；调用：`isinstance`, `json.loads`, `target.exists`, `target.read_text`

### `mycodingagent/multi_agent/infrastructure/runner.py`

- 模块：`mycodingagent.multi_agent.infrastructure.runner`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.llm_runtime`, `mycodingagent.multi_agent.domain.contracts`, `mycodingagent.multi_agent.domain.models`, `mycodingagent.multi_agent.infrastructure.permissions`, `mycodingagent.tool_runtime`
- 类 `class AgentOutputError`（L16）：封装该模块的状态与行为。
- 类 `class AgentRunner`（L20）：封装该模块的状态与行为。
  - `__init__(self, api_client, registry, workspace_root, event_sink) -> None` （L21）；调用：无
  - `async run(self, request) -> AgentResult` （L34）；调用：`AgentResult`, `ToolAccessPolicy`, `_parse_arguments`, `agent_client.execute_local_tool`, `agent_client.format_openai_tools`, `agent_client.stream_one_round`, `enumerate`, `messages.append`, `policy.authorize`, `policy.schemas`, `range`, `self._emit`
  - `async _emit(self, phase, message, **metadata) -> None` （L126）；调用：`RuntimeEvent`, `self.event_sink.emit`
- 函数 `parse_json_object(text) -> dict[str, Any]` （L131）：执行模块级业务逻辑。；调用：`AgentOutputError`, `isinstance`, `join`, `json.loads`, `startswith`, `strip`, `text.strip`, `value.find`, `value.rfind`, `value.splitlines`, `value.startswith`
- 函数 `_parse_arguments(raw) -> dict[str, Any]` （L156）：执行模块级业务逻辑。；调用：`isinstance`, `json.loads`

### `mycodingagent/multi_agent/infrastructure/workspace_state.py`

- 模块：`mycodingagent.multi_agent.infrastructure.workspace_state`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.infrastructure.permissions`
- 函数 `capture_workspace_state(root) -> dict[str, str]` （L24）：执行模块级业务逻辑。；调用：`any`, `as_posix`, `hashlib.sha256`, `hexdigest`, `path.is_file`, `path.read_bytes`, `path.relative_to`, `resolved_root.rglob`, `root.resolve`
- 函数 `changed_paths(before, after) -> set[str]` （L38）：执行模块级业务逻辑。；调用：`after.get`, `after.keys`, `before.get`, `before.keys`
- 函数 `outside_scopes(paths, scopes, root) -> set[str]` （L46）：执行模块级业务逻辑。；调用：`any`, `normalize_workspace_path`, `outside.add`, `set`

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
  - `__init__(self, orchestrator, config) -> None` （L10）；调用：无
  - `enable(self) -> None` （L17）；调用：无
  - `disable(self) -> None` （L20）；调用：`RuntimeError`
  - `status_text(self) -> str` （L25）；调用：无
  - `async run(self, prompt, messages) -> tuple[str, list[dict[str, Any]]]` （L34）；调用：`RuntimeError`, `self.orchestrator.run`

### `mycodingagent/multi_agent/orchestration/orchestrator.py`

- 模块：`mycodingagent.multi_agent.orchestration.orchestrator`
- 职责：多智能体领域模型、角色、编排状态机和基础设施适配器。
- 内部依赖：`mycodingagent.multi_agent.agents.auditor`, `mycodingagent.multi_agent.agents.executor`, `mycodingagent.multi_agent.agents.optimizer`, `mycodingagent.multi_agent.agents.planner`, `mycodingagent.multi_agent.agents.router`, `mycodingagent.multi_agent.agents.validator`, `mycodingagent.multi_agent.domain.contracts`, `mycodingagent.multi_agent.domain.models`, `mycodingagent.multi_agent.infrastructure.path_locks`, `mycodingagent.multi_agent.infrastructure.permissions`, `mycodingagent.multi_agent.infrastructure.runner`, `mycodingagent.multi_agent.infrastructure.workspace_state`
- 类 `class WorkflowError`（L57）：封装该模块的状态与行为。
- 类 `class MultiCodingOrchestrator`（L61）：封装该模块的状态与行为。
  - `__init__(self, workspace_root, config, event_hook, approval_hook, runner, direct_responder, conversation_recorder, run_journal, default_model) -> None` （L62）；调用：`PathLockManager`, `workspace_root.resolve`
  - `async run(self, prompt, messages) -> tuple[WorkflowResult, list[dict[str, Any]]]` （L86）；调用：`VerificationReport`, `WorkflowError`, `WorkflowResult`, `all_execution_reports.extend`, `all_work_items.extend`, `capture_workspace_state`, `changed.update`, `changed_paths`, `len`, `list`, `print`, `self._architecture_phase`
  - `async _decide_query(self, prompt) -> QueryDecision` （L304）；调用：`QueryDecision`, `QueryDecision.from_mapping`, `frozenset`, `heuristic_workflow_mode`, `join`, `prompt.split`, `self._agent_json`
  - `async _audit(self, query) -> ProjectAuditReport` （L320）；调用：`AuditScope`, `AuditScope.from_mapping`, `ProjectAuditReport.from_mapping`, `_compact_json`, `_json`, `asyncio.Semaphore`, `asyncio.gather`, `enumerate`, `frozenset`, `isinstance`, `len`, `list`
  - `async _architecture_phase(self, query, audit_report, request_approval) -> tuple[ArchitectureProposal | None, str]` （L419）；调用：`ArchitectureProposal.from_mapping`, `_compact_json`, `architecture_approval_required`, `audit_report.to_dict`, `bool`, `decision.get`, `self._agent_json`, `self._emit`, `self.approval_hook.approve`, `user_forbids_architecture_change`
  - `async _plan_work_items(self, query, audit_report, proposal, architecture_constraint, planner_prompt, verification) -> tuple[WorkItem, ...]` （L464）；调用：`WorkflowError`, `_compact_json`, `audit_report.to_dict`, `ensure_framework_work_item`, `len`, `parse_work_items`, `proposal.to_dict`, `range`, `self._agent_json`, `self._emit`, `str`, `validate_work_items`
  - `async _execute_work_items(self, query, audit_report, proposal, work_items) -> tuple[list[dict[str, Any]], set[str]]` （L502）；调用：`WorkflowError`, `asyncio.gather`, `capture_workspace_state`, `changed.update`, `changed_paths`, `completed.add`, `failures.append`, `isinstance`, `join`, `outside_scopes`, `pending.pop`, `pending.values`
  - `async _execute_item(self, query, audit_report, proposal, item) -> dict[str, Any]` （L564）；调用：`AgentRequest`, `WorkflowError`, `_compact_json`, `item.to_dict`, `parse_json_object`, `proposal.to_dict`, `result.text.strip`, `self._model_for`, `self.path_locks.acquire`, `self.runner.run`
  - `async _validate(self, query, audit_report, proposal, work_items, execution_reports, changed_files) -> VerificationReport` （L597）；调用：`VerificationReport`, `VerificationReport.from_mapping`, `_compact_json`, `item.to_dict`, `len`, `proposal.to_dict`, `self._agent_json`, `self._emit`, `sorted`
  - `async _synthesize(self, query, status, audit_report, proposal, work_items, verification, repair_rounds, changed_files, execution_reports) -> str` （L641）；调用：`AgentRequest`, `_compact_json`, `frozenset`, `item.to_dict`, `join`, `proposal.to_dict`, `result.text.strip`, `self._model_for`, `self.runner.run`, `sorted`, `verification.to_dict`
  - `async _agent_json(self, role, system_prompt, user_prompt, allowed_tools, allow_validation_bash) -> dict[str, Any]` （L680）；调用：`AgentRequest`, `WorkflowError`, `errors.append`, `join`, `parse_json_object`, `range`, `self._model_for`, `self.runner.run`, `str`
  - `async _emit(self, phase, message, **metadata) -> None` （L717）；调用：`RuntimeEvent`, `self.event_hook.emit`
  - `_model_for(self, role) -> str` （L720）；调用：无
  - `_record_turn(self, messages, prompt, response) -> list[dict[str, Any]]` （L731）；调用：`list`, `self.conversation_recorder.save_messages`, `self.conversation_recorder.start_session`, `updated.append`
  - `_save_run(self, run_id, started_at, prompt, decision, status, response, audit_report, proposal, work_items, execution_reports, verification, changed_files, errors) -> None` （L747）；调用：`audit_report.to_dict`, `item.to_dict`, `list`, `proposal.to_dict`, `self.run_journal.save`, `set`, `sorted`, `time`, `verification.to_dict`
- 函数 `parse_work_items(payload) -> tuple[WorkItem, ...]` （L787）：执行模块级业务逻辑。；调用：`WorkItem.from_mapping`, `WorkflowError`, `enumerate`, `isinstance`, `payload.get`, `tuple`
- 函数 `ensure_framework_work_item(items) -> tuple[WorkItem, ...]` （L798）：执行模块级业务逻辑。；调用：`WorkItem`, `any`, `path.rstrip`, `tuple`
- 函数 `validate_work_items(items) -> None` （L818）：执行模块级业务逻辑。；调用：`WorkflowError`, `any`, `join`, `len`, `set`, `sorted`
- 函数 `select_runnable_batch(items, completed, limit, workspace_root) -> tuple[WorkItem, ...]` （L839）：执行模块级业务逻辑。；调用：`any`, `issubset`, `len`, `max`, `path_scopes_overlap`, `selected.append`, `set`, `sorted`, `tuple`
- 函数 `path_scopes_overlap(left, right, root) -> bool` （L861）：执行模块级业务逻辑。；调用：`any`, `normalize_workspace_path`
- 函数 `merge_audit_reports(reports) -> dict[str, Any]` （L871）：执行模块级业务逻辑。；调用：`append`, `isinstance`, `join`, `json.dumps`, `report.get`, `seen.add`, `set`, `str`, `strip`
- 函数 `architecture_approval_required(proposal) -> bool` （L898）：执行模块级业务逻辑。；调用：`bool`
- 函数 `user_forbids_architecture_change(query) -> bool` （L907）：执行模块级业务逻辑。；调用：`any`, `join`, `query.lower`, `split`
- 函数 `heuristic_workflow_mode(prompt) -> WorkflowMode` （L922）：执行模块级业务逻辑。；调用：`any`, `prompt.lower`
- 函数 `_json(value) -> str` （L969）：执行模块级业务逻辑。；调用：`json.dumps`
- 函数 `_compact_json(value, limit) -> str` （L973）：执行模块级业务逻辑。；调用：`_json`, `len`

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
  - `__init__(self, decay, max_entries) -> None` （L22）；调用：`max`
  - `touch(self, skill_name, current_round, reward) -> float` （L27）；调用：`LRFUEntry`, `max`, `self._entries.get`, `self._prune_if_needed`, `self.decayed_score`
  - `get_score(self, skill_name, current_round) -> float` （L42）；调用：`max`, `self._entries.get`, `self.decayed_score`
  - `top_candidates(self, limit, current_round) -> list[LRFUCandidate]` （L55）；调用：`LRFUCandidate`, `candidates.sort`, `list`, `self.get_score`
  - `to_dict(self) -> dict` （L65）；调用：`self._entries.values`
  - `load_dict(self, data) -> None` （L79）；调用：`LRFUEntry`, `data.get`, `float`, `int`, `isinstance`, `item.get`, `max`, `str`, `strip`
  - `decayed_score(score, last_update_round, current_round, decay) -> float` （L97）；调用：`max`
  - `_prune_if_needed(self, current_round) -> None` （L109）；调用：`len`, `self._entries.items`, `self.top_candidates`

### `mycodingagent/skill_runtime/__init__.py`

- 模块：`mycodingagent.skill_runtime`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.skill_runtime.runtime`
- 函数 `__getattr__(name) -> 未声明` （L6）：执行模块级业务逻辑。；调用：`AttributeError`

### `mycodingagent/skill_runtime/contracts.py`

- 模块：`mycodingagent.skill_runtime.contracts`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：无
- 类 `class SkillService`（L6）：封装该模块的状态与行为。
  - `async search_skill_schemas(self, query, max_results, tool_names) -> dict[str, Any]` （L7）；调用：无
  - `async list_skill_tools(self) -> dict[str, Any]` （L15）；调用：无
  - `async get_tool_schema_by_name(self, tool_name) -> dict[str, Any]` （L17）；调用：无
  - `async search_skill_references(self, query, skill_name, max_results) -> dict[str, Any]` （L19）；调用：无
  - `async get_skill_reference(self, skill_name, reference_path) -> dict[str, Any]` （L27）；调用：无
  - `get_record(self, tool_name) -> Any | None` （L34）；调用：无
  - `record_skill_invocation(self, tool_name) -> None` （L36）；调用：无
  - `list_references_for_skill(self, tool_name) -> list[dict[str, Any]]` （L38）；调用：无
- 类 `class ToolRegistrar`（L41）：封装该模块的状态与行为。
  - `register(self, tool) -> None` （L42）；调用：无

### `mycodingagent/skill_runtime/discovery.py`

- 模块：`mycodingagent.skill_runtime.discovery`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.skill_runtime.models`
- 函数 `discover_skill_records(skills_root) -> list[SkillRecord]` （L33）：执行模块级业务逻辑。；调用：`_discover_single_root`, `isinstance`, `list`, `records_by_tool_name.values`
- 函数 `discover_reference_records(records) -> list[SkillReferenceRecord]` （L44）：执行模块级业务逻辑。；调用：`_discover_record_references`, `isinstance`, `records.values`, `reference_records.append`, `seen.add`, `set`
- 函数 `_discover_single_root(skills_root) -> list[SkillRecord]` （L57）：执行模块级业务逻辑。；调用：`_iter_skill_files`, `_load_skill_file`, `records.append`, `skills_root.exists`, `sorted`
- 函数 `_discover_record_references(record) -> list[SkillReferenceRecord]` （L69）：执行模块级业务逻辑。；调用：`SkillReferenceRecord`, `_is_reference_text_file`, `_should_skip`, `as_posix`, `content.encode`, `hashlib.sha256`, `hexdigest`, `path.is_file`, `path.read_text`, `path.relative_to`, `path.resolve`, `references_root.exists`, `references_root.is_dir`, `references_root.rglob`, `result.append`, `sorted`
- 函数 `_iter_skill_files(skills_root) -> list[Path]` （L104）：执行模块级业务逻辑。；调用：`_should_skip`, `path.is_file`, `path.name.endswith`, `skill_files.append`, `skills_root.rglob`
- 函数 `_should_skip(path) -> bool` （L116）：执行模块级业务逻辑。；调用：`any`
- 函数 `_is_reference_text_file(path) -> bool` （L120）：执行模块级业务逻辑。；调用：`path.name.startswith`, `path.suffix.lower`
- 函数 `_load_skill_file(path) -> SkillRecord | None` （L126）：执行模块级业务逻辑。；调用：`_load_json_skill`, `_load_markdown_skill`, `path.name.endswith`, `path.read_text`
- 函数 `_load_json_skill(path, content) -> SkillRecord | None` （L137）：执行模块级业务逻辑。；调用：`_first_nonempty_line`, `_make_record`, `data.get`, `isinstance`, `json.loads`, `path.stem.removesuffix`, `str`, `strip`
- 函数 `_load_markdown_skill(path, content) -> SkillRecord` （L151）：执行模块级业务逻辑。；调用：`_first_markdown_heading`, `_first_paragraph`, `_frontmatter`, `_make_record`, `frontmatter.get`, `str`, `strip`
- 函数 `_make_record(path, name, description, content, metadata) -> SkillRecord` （L158）：执行模块级业务逻辑。；调用：`SkillRecord`, `content.encode`, `hashlib.sha256`, `hexdigest`, `normalize_tool_name`, `path.resolve`, `time.time`
- 函数 `normalize_tool_name(name) -> str` （L172）：执行模块级业务逻辑。；调用：`isalpha`, `lower`, `name.strip`, `normalized.startswith`, `re.sub`, `strip`
- 函数 `_first_markdown_heading(content) -> str | None` （L185）：执行模块级业务逻辑。；调用：`content.splitlines`, `line.strip`, `strip`, `stripped.lstrip`, `stripped.startswith`
- 函数 `_frontmatter(content) -> dict[str, str]` （L193）：执行模块级业务逻辑。；调用：`content.splitlines`, `key.strip`, `line.strip`, `strip`, `stripped.split`, `stripped.startswith`, `value.strip`
- 函数 `_first_paragraph(content) -> str | None` （L210）：执行模块级业务逻辑。；调用：`content.splitlines`, `join`, `line.strip`, `lines.append`, `stripped.startswith`
- 函数 `_first_nonempty_line(content) -> str` （L230）：执行模块级业务逻辑。；调用：`content.splitlines`, `line.strip`

### `mycodingagent/skill_runtime/embeddings.py`

- 模块：`mycodingagent.skill_runtime.embeddings`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.configuration`
- 类 `class EmbeddingService`（L19）：封装该模块的状态与行为。
  - `dim(self) -> int` （L21）；调用：无
  - `embed(self, text) -> list[float]` （L24）；调用：无
  - `embed_many(self, texts) -> list[list[float]]` （L27）；调用：无
  - `embed_query(self, text) -> list[float]` （L30）；调用：无
  - `embed_documents(self, texts) -> list[list[float]]` （L33）；调用：无
  - `signature(self) -> str` （L36）；调用：无
- 类 `class HashEmbeddingService`（L40）：Deterministic fallback used when local BGE dependencies are unavailable.
  - `__init__(self, dim) -> None` （L43）；调用：无
  - `dim(self) -> int` （L47）；调用：无
  - `embed(self, text) -> list[float]` （L50）；调用：`self.embed_many`
  - `embed_many(self, texts) -> list[list[float]]` （L53）；调用：`_hash_vector`
  - `embed_query(self, text) -> list[float]` （L56）；调用：`self.embed`
  - `embed_documents(self, texts) -> list[list[float]]` （L59）；调用：`self.embed_many`
  - `signature(self) -> str` （L62）；调用：无
- 类 `class BgeEmbeddingService`（L66）：封装该模块的状态与行为。
  - `__init__(self, model_name, device, batch_size, fallback_to_hash) -> None` （L67）；调用：`HashEmbeddingService`, `threading.Lock`
  - `dim(self) -> int` （L87）；调用：无
  - `embed(self, text) -> list[float]` （L90）；调用：`self.embed_many`
  - `embed_many(self, texts) -> list[list[float]]` （L93）；调用：`self._encode_with_model`, `self._fallback.embed_many`, `self._load_model`
  - `embed_query(self, text) -> list[float]` （L101）；调用：`self._encode_with_model`, `self._fallback.embed_query`, `self._load_model`
  - `embed_documents(self, texts) -> list[list[float]]` （L108）；调用：`self.embed_many`
  - `signature(self) -> str` （L111）；调用：`join`, `str`
  - `_load_model(self) -> 未声明` （L119）；调用：`RuntimeError`, `SentenceTransformer`, `int`, `self._model.get_sentence_embedding_dimension`
  - `_encode_with_model(self, model, texts) -> list[list[float]]` （L146）；调用：`_to_float_list`, `model.encode`
- 类 `class BgeHttpEmbeddingService`（L157）：封装该模块的状态与行为。
  - `__init__(self, endpoint, model_name, api_key, timeout, dim) -> None` （L158）；调用：无
  - `dim(self) -> int` （L176）；调用：无
  - `embed(self, text) -> list[float]` （L179）；调用：`self.embed_many`
  - `embed_many(self, texts) -> list[list[float]]` （L182）；调用：`self._request_embeddings`
  - `embed_query(self, text) -> list[float]` （L185）；调用：`self._request_embeddings`
  - `embed_documents(self, texts) -> list[list[float]]` （L189）；调用：`self.embed_many`
  - `signature(self) -> str` （L192）；调用：`join`, `str`
  - `_request_embeddings(self, texts) -> list[list[float]]` （L201）；调用：`RuntimeError`, `_extract_embeddings`, `decode`, `encode`, `json.dumps`, `json.loads`, `len`, `response.read`, `self._headers`, `self._openai_payload`, `self._request_ollama`, `urllib.request.Request`
  - `_request_ollama(self, texts) -> list[list[float]]` （L248）；调用：`RuntimeError`, `_extract_embeddings`, `decode`, `encode`, `json.dumps`, `json.loads`, `len`, `response.read`, `self._headers`, `urllib.request.Request`, `urllib.request.urlopen`
  - `_openai_payload(self, texts) -> dict` （L283）；调用：无
  - `_headers(self) -> dict[str, str]` （L289）；调用：无
- 函数 `create_embedding_service(无) -> EmbeddingService` （L299）：执行模块级业务逻辑。；调用：`BgeEmbeddingService`, `BgeHttpEmbeddingService`, `HashEmbeddingService`, `ValueError`
- 类 `class EmbeddingCache`（L312）：封装该模块的状态与行为。
  - `__init__(self, db_path) -> None` （L313）；调用：`self._init_db`, `self.db_path.parent.mkdir`
  - `_connect(self) -> sqlite3.Connection` （L318）；调用：`sqlite3.connect`
  - `_init_db(self) -> None` （L321）；调用：`conn.execute`, `self._connect`
  - `get(self, tool_name, text_hash, embedding_signature) -> list[float] | None` （L335）；调用：`_to_float_list`, `conn.execute`, `fetchone`, `json.loads`, `self._connect`
  - `put(self, tool_name, text_hash, embedding_signature, vector, updated_at) -> None` （L352）；调用：`conn.execute`, `json.dumps`, `self._connect`
  - `delete_missing(self, existing_tool_names) -> None` （L375）；调用：`conn.execute`, `join`, `self._connect`, `tuple`
  - `delete(self, tool_names) -> None` （L386）；调用：`conn.execute`, `join`, `self._connect`, `tuple`
- 函数 `embedding_text_hash(text) -> str` （L397）：执行模块级业务逻辑。；调用：`hashlib.sha256`, `hexdigest`, `text.encode`
- 函数 `_extract_embeddings(body) -> list[list[float]]` （L401）：执行模块级业务逻辑。；调用：`RuntimeError`, `_to_float_list`, `body.get`, `isinstance`, `item.get`, `sorted`, `str`
- 函数 `_hash_vector(text, dim) -> list[float]` （L417）：执行模块级业务逻辑。；调用：`_normalize`, `_tokens`, `digest`, `hashlib.sha256`, `int.from_bytes`, `token.encode`
- 函数 `_tokens(text) -> list[str]` （L427）：执行模块级业务逻辑。；调用：`TOKEN_RE.findall`, `token.lower`
- 函数 `_normalize(vector) -> list[float]` （L431）：执行模块级业务逻辑。；调用：`math.sqrt`, `sum`
- 函数 `_to_float_list(vector) -> list[float]` （L438）：执行模块级业务逻辑。；调用：`float`, `hasattr`, `vector.tolist`

### `mycodingagent/skill_runtime/index.py`

- 模块：`mycodingagent.skill_runtime.index`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.skill_runtime.models`
- 类 `class SkillSqlStore`（L9）：封装该模块的状态与行为。
  - `__init__(self, db_path) -> None` （L10）；调用：`self._init_db`, `self.db_path.parent.mkdir`
  - `_connect(self) -> sqlite3.Connection` （L15）；调用：`sqlite3.connect`
  - `_init_db(self) -> None` （L18）；调用：`conn.execute`, `self._connect`
  - `load_all(self) -> dict[str, SkillRecord]` （L62）；调用：`Path`, `SkillRecord`, `conn.execute`, `fetchall`, `self._connect`
  - `upsert(self, record) -> None` （L80）；调用：`conn.execute`, `self._connect`, `str`
  - `delete_missing_sources(self, existing_sources) -> int` （L106）；调用：`conn.execute`, `fetchall`, `self._connect`
  - `delete_missing_tool_names(self, existing_tool_names) -> int` （L116）；调用：`conn.execute`, `fetchall`, `self._connect`
  - `reject(self, source_path, reason, updated_at) -> None` （L126）；调用：`conn.execute`, `self._connect`, `str`
  - `load_references(self) -> dict[str, SkillReferenceRecord]` （L139）；调用：`Path`, `SkillReferenceRecord`, `conn.execute`, `fetchall`, `self._connect`
  - `upsert_reference(self, record) -> None` （L174）；调用：`conn.execute`, `self._connect`, `str`
  - `delete_missing_references(self, existing_ref_ids) -> int` （L206）；调用：`conn.execute`, `fetchall`, `self._connect`
  - `delete_references_for_missing_skills(self, existing_tool_names) -> int` （L216）；调用：`conn.execute`, `fetchall`, `self._connect`
  - `get_reference(self, skill_tool_name, reference_path) -> SkillReferenceRecord | None` （L226）；调用：`get`, `self.load_references`
  - `list_references_for_skill(self, skill_tool_name) -> list[SkillReferenceRecord]` （L230）；调用：`self.load_references`, `sorted`, `values`

### `mycodingagent/skill_runtime/models.py`

- 模块：`mycodingagent.skill_runtime.models`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：无
- 类 `class ReviewResult`（L9）：封装该模块的状态与行为。
- 类 `class SkillRecord`（L15）：封装该模块的状态与行为。
- 类 `class SkillReferenceRecord`（L27）：封装该模块的状态与行为。
- 类 `class SearchResult`（L40）：封装该模块的状态与行为。
- 类 `class SkillSyncReport`（L49）：封装该模块的状态与行为。
  - `summary(self) -> str` （L61）；调用：`join`, `len`, `parts.append`

### `mycodingagent/skill_runtime/reviewers.py`

- 模块：`mycodingagent.skill_runtime.reviewers`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.skill_runtime.models`
- 函数 `async review_skill_code(source_path, content) -> ReviewResult` （L8）：Entry point for future malicious-code review.；调用：`ReviewResult`
- 函数 `async review_skill_prompt(source_path, content) -> ReviewResult` （L18）：Entry point for future prompt-injection and instruction-risk review.；调用：`ReviewResult`

### `mycodingagent/skill_runtime/router.py`

- 模块：`mycodingagent.skill_runtime.router`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.relevance.lrfu`, `mycodingagent.skill_runtime.models`
- 类 `class SkillRouterConfig`（L11）：封装该模块的状态与行为。
- 类 `class _RouterCandidate`（L21）：封装该模块的状态与行为。
  - `from_retrieval(self) -> bool` （L31）；调用：无
- 类 `class SkillRouter`（L35）：Fuse retrieval, session, and user Skill candidates into a bounded TopN.
  - `__init__(self, config) -> None` （L38）；调用：无
  - `select(self, records, retrieval_results, user_candidates, session_candidates, pinned_names) -> list[SkillRecord]` （L41）；调用：`_RouterCandidate`, `candidates.setdefault`, `candidates.values`, `list`, `records.get`, `selected.sort`, `self._enforce_retrieval_floor`, `self._merge_lrfu`, `self._merge_retrieval`, `self._score_candidates`, `sorted`
  - `_merge_retrieval(self, candidates, records, retrieval_results) -> None` （L73）；调用：`_RouterCandidate`, `candidates.setdefault`, `records.get`, `seen.add`, `set`
  - `_merge_lrfu(self, candidates, records, source, source_name) -> None` （L95）；调用：`_RouterCandidate`, `candidates.setdefault`, `max`, `records.get`
  - `_score_candidates(self, candidates) -> None` （L115）；调用：无
  - `_enforce_retrieval_floor(self, selected, candidates) -> list[_RouterCandidate]` （L125）；调用：`candidates.values`, `ceil`, `len`, `max`, `min`, `selected.append`, `selected.remove`, `selected_by_name.pop`, `sorted`, `sum`
  - `_sort_key(self, candidate) -> tuple[float, int, float, float, str]` （L168）；调用：`int`

### `mycodingagent/skill_runtime/runtime.py`

- 模块：`mycodingagent.skill_runtime.runtime`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.skill_runtime.contracts`, `mycodingagent.skill_runtime.discovery`, `mycodingagent.skill_runtime.embeddings`, `mycodingagent.skill_runtime.index`, `mycodingagent.skill_runtime.models`, `mycodingagent.skill_runtime.reviewers`, `mycodingagent.skill_runtime.router`, `mycodingagent.skill_runtime.session_skill_cache`, `mycodingagent.skill_runtime.user_skill_cache`, `mycodingagent.skill_runtime.vector_store`, `mycodingagent.skill_runtime.watcher`, `mycodingagent.tool_runtime.skill_tools`
- 类 `class SkillRuntime`（L86）：封装该模块的状态与行为。
  - `__init__(self, skills_root, skill_roots, registry) -> None` （L87）；调用：`EmbeddingCache`, `GetAllTool`, `GetSkillReferenceTool`, `GetToolByNameTool`, `MultiSkillDirectoryWatcher`, `SearchSkillReferencesTool`, `SearchSkillTool`, `SessionSkillCache`, `SkillRouter`, `SkillRouterConfig`, `SkillSqlStore`, `UserSkillCache`
  - `async initialize(self) -> SkillSyncReport` （L148）；调用：`self._ensure_vector_index_complete`, `self._watcher.start`, `self.ensure_synced`, `self.registry.register`
  - `search_records_for_capability(self, query, top_k) -> list[SearchResult]` （L159）；调用：`self._search_records`
  - `close(self) -> None` （L162）；调用：`self._watcher.stop`, `self.user_skill_cache.commit_session`
  - `async ensure_synced(self) -> SkillSyncReport` （L168）；调用：`SkillSyncReport`, `self._watcher.consume_dirty`, `self.sync`
  - `_ensure_vector_index_complete(self, report) -> None` （L173）；调用：`_progress_bar`, `getattr`, `len`, `max`, `print`, `range`, `self._upsert_vector_batch_with_retry`, `self.vector_store.stale_records`
  - `_upsert_vector_batch_with_retry(self, batch, batch_label) -> tuple[bool, Exception | None]` （L226）；调用：`max`, `min`, `print`, `range`, `self.vector_store.upsert`, `time.sleep`
  - `async sync(self) -> SkillSyncReport` （L246）；调用：`SkillSyncReport`, `any`, `changed_records.append`, `current_records.values`, `discover_skill_records`, `getattr`, `list`, `report.rejected.append`, `self._activate_default_skill_tools`, `self._register_available_skill_tools`, `self._review`, `self._sync_references`
  - `get_record(self, tool_name) -> SkillRecord | None` （L314）；调用：`self.records.get`
  - `list_references_for_skill(self, tool_name) -> list[dict[str, Any]]` （L317）；调用：`self.references.values`, `sorted`, `str`
  - `build_tools_for_prompt(self, prompt, core_tool_schemas) -> list[dict[str, Any]]` （L333）；调用：`_dedupe_schemas`, `_format_recall_names`, `print`, `self._search_records`, `self._skill_management_schemas`, `self.router.select`, `self.session_skill_cache.top_candidates`, `self.user_skill_cache.top_candidates`, `set`, `skill_schema_from_record`
  - `async build_tools_for_prompt_async(self, prompt, core_tool_schemas) -> list[dict[str, Any]]` （L367）；调用：`self.build_tools_for_prompt`, `self.ensure_synced`
  - `async search_skill_schemas(self, query, max_results, tool_names) -> dict[str, Any]` （L375）；调用：`len`, `max`, `min`, `result.metadata.get`, `round`, `self._pin_skill`, `self._search_records`, `self.ensure_synced`, `skill_schema_from_record`, `str`, `zip`
  - `async list_skill_tools(self) -> dict[str, Any]` （L402）；调用：`len`, `self._source_kind`, `self.ensure_synced`, `self.records.values`, `sorted`, `str`
  - `async get_tool_schema_by_name(self, tool_name) -> dict[str, Any]` （L419）；调用：`len`, `record.name.lower`, `record.tool_name.lower`, `self._pin_skill`, `self._source_kind`, `self.ensure_synced`, `self.records.get`, `self.records.values`, `self.session_skill_cache.touch`, `skill_schema_from_record`, `str`, `tool_name.lower`
  - `async search_skill_references(self, query, skill_name, max_results) -> dict[str, Any]` （L449）；调用：`_rank_references`, `_reference_snippet`, `len`, `max`, `min`, `query.strip`, `round`, `self._resolve_skill_tool_name`, `self.ensure_synced`, `self.references.values`, `sorted`, `str`
  - `async get_skill_reference(self, skill_name, reference_path) -> dict[str, Any]` （L502）；调用：`_normalize_reference_path`, `self._resolve_skill_tool_name`, `self.ensure_synced`, `self.references.get`, `str`
  - `system_hint(self) -> str` （L532）；调用：无
  - `default_skill_hint(self) -> str` （L535）；调用：`join`, `parts.append`, `self._source_kind`
  - `_skill_management_schemas(self) -> list[dict[str, Any]]` （L556）；调用：`self.get_all_tool_instance.get_schema`, `self.get_reference_tool_instance.get_schema`, `self.get_tool_by_name_instance.get_schema`, `self.search_references_tool_instance.get_schema`, `self.search_tool_instance.get_schema`
  - `_register_available_skill_tools(self) -> None` （L565）；调用：`SkillTool`, `self._registered_skill_tools.add`, `self.registry.register`
  - `_activate_default_skill_tools(self) -> None` （L572）；调用：`self._pin_skill`
  - `begin_turn(self) -> None` （L576）；调用：`self._turn_pinned_tool_names.clear`
  - `end_turn(self) -> None` （L579）；调用：`self._turn_pinned_tool_names.clear`
  - `_pin_skill(self, tool_name, scope) -> None` （L582）；调用：`iter`, `len`, `max`, `next`, `pinned.pop`
  - `record_skill_invocation(self, tool_name) -> None` （L592）；调用：`self._pin_skill`, `self.session_skill_cache.touch`, `self.user_skill_cache.record_skill_call`
  - `_search_records(self, query, top_k, preferred_names) -> list[SearchResult]` （L609）；调用：`_local_keyword_search`, `_merge_search_results`, `self.vector_store.search`
  - `_source_kind(self, source_path) -> str` （L633）；调用：`_is_relative_to`, `root.resolve`, `self._builtin_root.resolve`, `self.skills_root.resolve`, `source_path.resolve`
  - `_sync_references(self, current_records) -> tuple[int, int, int]` （L646）；调用：`discover_reference_records`, `previous.get`, `self.store.delete_missing_references`, `self.store.delete_references_for_missing_skills`, `self.store.load_references`, `self.store.upsert_reference`, `set`, `str`
  - `_resolve_skill_tool_name(self, name) -> str` （L669）；调用：`candidate.lower`, `len`, `name.strip`, `normalize_tool_name`, `record.name.lower`, `record.tool_name.lower`, `self.records.values`
  - `async _review(self, record) -> str` （L689）；调用：`review_skill_code`, `review_skill_prompt`
- 函数 `_dedupe_schemas(schemas) -> list[dict[str, Any]]` （L699）：执行模块级业务逻辑。；调用：`result.append`, `schema.get`, `seen.add`, `set`
- 函数 `_format_recall_names(names) -> str` （L711）：执行模块级业务逻辑。；调用：`join`, `str`
- 函数 `_progress_bar(done, total, width) -> str` （L716）：执行模块级业务逻辑。；调用：`int`, `max`, `min`, `round`
- 函数 `_merge_search_results(primary, fallback, top_k) -> list[SearchResult]` （L724）：执行模块级业务逻辑。；调用：`max`, `merged.get`, `merged.values`, `sorted`
- 函数 `_local_keyword_search(query, records, top_k, preferred_names) -> list[SearchResult]` （L744）：执行模块级业务逻辑。；调用：`SearchResult`, `_local_keyword_score`, `_tokenize_for_local_search`, `any`, `name.lower`, `record.name.lower`, `record.tool_name.lower`, `records.values`, `results.append`, `sorted`
- 函数 `_local_keyword_score(query_tokens, record) -> float` （L778）：执行模块级业务逻辑。；调用：`join`, `lower`, `record.content.lower`, `record.description.lower`, `record.name.lower`, `record.tool_name.lower`
- 函数 `_tokenize_for_local_search(query) -> list[str]` （L796）：执行模块级业务逻辑。；调用：`TOKEN_RE.findall`, `dict.fromkeys`, `list`, `query.lower`, `strip`, `token.strip`, `tokens.append`
- 函数 `_is_relative_to(path, root) -> bool` （L804）：执行模块级业务逻辑。；调用：`path.relative_to`
- 函数 `_normalize_reference_path(reference_path) -> str | None` （L812）：执行模块级业务逻辑。；调用：`any`, `join`, `lstrip`, `normalized.split`, `parts.insert`, `reference_path.strip`, `replace`
- 函数 `_rank_references(query, references, skill_tool_name, limit) -> list[tuple[SkillReferenceRecord, float]]` （L826）：执行模块级业务逻辑。；调用：`_overlap`, `_tokens`, `join`, `scored.append`, `scored.sort`
- 函数 `_tokens(text) -> set[str]` （L859）：执行模块级业务逻辑。；调用：`TOKEN_RE.findall`, `token.lower`
- 函数 `_overlap(left, right) -> float` （L863）：执行模块级业务逻辑。；调用：`len`
- 函数 `_reference_snippet(content, query, limit) -> str` （L869）：执行模块级业务逻辑。；调用：`_tokens`, `compact.lower`, `content.split`, `join`, `len`, `lower.find`, `max`, `sorted`, `token.lower`

### `mycodingagent/skill_runtime/session_skill_cache.py`

- 模块：`mycodingagent.skill_runtime.session_skill_cache`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.relevance.lrfu`
- 类 `class SessionSkillCache`（L6）：Session-scoped LRFU cache used for immediate in-conversation routing.
  - `__init__(self, decay, max_entries) -> None` （L9）；调用：`LRFUCache`
  - `touch(self, skill_name, current_round, reward) -> float` （L12）；调用：`self._cache.touch`
  - `top_candidates(self, limit, current_round) -> list[LRFUCandidate]` （L15）；调用：`self._cache.top_candidates`
  - `to_dict(self) -> dict` （L18）；调用：`self._cache.to_dict`
  - `load_dict(self, data) -> None` （L21）；调用：`self._cache.load_dict`

### `mycodingagent/skill_runtime/user_skill_cache.py`

- 模块：`mycodingagent.skill_runtime.user_skill_cache`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.relevance.lrfu`
- 类 `class UserSkillCache`（L10）：Persistent user LRFU cache with deferred session commits.
  - `__init__(self, db_path, decay, reward, max_entries) -> None` （L18）；调用：`max`, `self._init_db`, `self.db_path.parent.mkdir`
  - `start_session(self, user_id, session_id) -> None` （L33）；调用：`conn.execute`, `self._connect`, `self.get_user_skill_call_round`, `self.recover_uncommitted`, `time.time`
  - `get_user_skill_call_round(self, user_id) -> int` （L49）；调用：`self._connect`, `self._get_user_skill_call_round`
  - `record_skill_call(self, user_id, session_id, skill_name, session_skill_call_round) -> None` （L53）；调用：`LRFUCache.decayed_score`, `conn.execute`, `fetchone`, `float`, `int`, `self._connect`, `self._get_user_skill_call_round`, `time.time`
  - `commit_session(self, user_id, session_id) -> None` （L144）；调用：`self._commit_session`, `self._connect`
  - `recover_uncommitted(self, user_id) -> None` （L148）；调用：`conn.execute`, `fetchall`, `self._commit_session`, `self._connect`, `str`
  - `top_candidates(self, user_id, limit) -> list[LRFUCandidate]` （L162）；调用：`LRFUCache.decayed_score`, `LRFUCandidate`, `candidates.append`, `candidates.sort`, `conn.execute`, `fetchall`, `float`, `int`, `max`, `rows_by_name.values`, `self._connect`, `self.get_user_skill_call_round`
  - `_commit_session(self, conn, user_id, session_id) -> None` （L214）；调用：`LRFUCache.decayed_score`, `conn.execute`, `fetchall`, `fetchone`, `float`, `int`, `max`, `self._get_user_skill_call_round`, `self._mark_session_committed`, `self._prune`, `time.time`
  - `_mark_session_committed(self, conn, user_id, session_id, updated_at) -> None` （L291）；调用：`conn.execute`
  - `_prune(self, conn, user_id) -> None` （L316）；调用：`conn.execute`, `conn.executemany`, `fetchall`, `str`
  - `_connect(self) -> sqlite3.Connection` （L334）；调用：`sqlite3.connect`
  - `_get_user_skill_call_round(self, conn, user_id) -> int` （L337）；调用：`conn.execute`, `fetchone`, `int`
  - `_init_db(self) -> None` （L350）；调用：`conn.execute`, `self._connect`

### `mycodingagent/skill_runtime/vector_store.py`

- 模块：`mycodingagent.skill_runtime.vector_store`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.skill_runtime.embeddings`, `mycodingagent.skill_runtime.models`
- 类 `class SkillVectorStore`（L22）：封装该模块的状态与行为。
  - `upsert(self, records) -> None` （L26）；调用：无
  - `delete_missing(self, existing_tool_names) -> None` （L29）；调用：无
  - `stale_records(self, records) -> list[SkillRecord]` （L32）；调用：无
  - `search(self, query, records, top_k, preferred_names) -> list[SearchResult] | None` （L35）；调用：无
- 类 `class MilvusVectorStore`（L46）：Milvus-backed hybrid retrieval for SKILL search.
  - `__init__(self, embedding_service, embedding_cache) -> None` （L58）；调用：`embedding_service.signature`, `self._connect`, `self._detect_dim`
  - `upsert(self, records) -> None` （L69）；调用：`_search_text`, `_truncate_text`, `float`, `self._client.upsert`, `self._ensure_ready`, `self._flush`, `self._vectors_for_records`, `str`, `zip`
  - `delete_missing(self, existing_tool_names) -> None` （L92）；调用：`_quoted_list`, `self._client.delete`, `self._ensure_ready`, `self._flush`
  - `stale_records(self, records) -> list[SkillRecord]` （L101）；调用：`indexed_hashes.get`, `len`, `list`, `max`, `records.items`, `records.values`, `row.get`, `self._client.query`, `self._ensure_ready`, `str`
  - `search(self, query, records, top_k, preferred_names) -> list[SearchResult] | None` （L127）；调用：`_boost_preferred`, `query.strip`, `self._ensure_ready`, `self._hybrid_search`
  - `_connect(self) -> None` （L143）；调用：`MilvusClient`, `RuntimeError`, `self._client.drop_collection`, `self._client.has_collection`, `self._client.load_collection`, `self._create_collection`, `self._schema_is_compatible`
  - `_create_collection(self, DataType, Function, FunctionType) -> None` （L178）；调用：`Function`, `index_params.add_index`, `schema.add_field`, `schema.add_function`, `self._client.create_collection`, `self._client.create_schema`, `self._client.prepare_index_params`
  - `_schema_is_compatible(self) -> bool` （L237）；调用：`dense_field.get`, `dense_params.get`, `description.get`, `field.get`, `int`, `next`, `self._client.describe_collection`
  - `_hybrid_search(self, query, records, top_k) -> list[SearchResult]` （L266）；调用：`AnnSearchRequest`, `SearchResult`, `_hit_entity`, `_hit_id`, `_hit_score`, `_record_from_entity`, `_rrf_ranker`, `entity.get`, `float`, `max`, `records.get`, `results.append`
  - `_detect_dim(self) -> int` （L330）；调用：`embedding_text_hash`, `len`, `self.embedding_cache.get`, `self.embedding_cache.put`, `self.embedding_service.embed_documents`
  - `_vectors_for_records(self, records) -> list[list[float]]` （L357）；调用：`_semantic_document`, `embedding_text_hash`, `len`, `missed_hashes.append`, `missed_records.append`, `missed_texts.append`, `self.embedding_cache.get`, `self.embedding_cache.put`, `self.embedding_service.embed_documents`, `zip`
  - `_ensure_ready(self) -> None` （L401）；调用：`RuntimeError`
  - `_flush(self) -> None` （L408）；调用：`self._client.flush`
- 函数 `create_vector_store(embedding_service, embedding_cache) -> SkillVectorStore` （L419）：执行模块级业务逻辑。；调用：`MilvusVectorStore`, `RuntimeError`
- 函数 `_record_from_entity(entity, tool_name) -> SkillRecord | None` （L428）：执行模块级业务逻辑。；调用：`Path`, `SkillRecord`, `entity.get`, `float`, `str`
- 函数 `_hit_entity(hit) -> dict[str, Any]` （L442）：执行模块级业务逻辑。；调用：`entity.get`, `entity.to_dict`, `getattr`, `hasattr`, `hit.get`, `isinstance`
- 函数 `_hit_id(hit) -> Any` （L474）：执行模块级业务逻辑。；调用：`getattr`, `hit.get`, `isinstance`
- 函数 `_hit_score(hit) -> float` （L480）：执行模块级业务逻辑。；调用：`getattr`, `hit.get`, `isinstance`
- 函数 `_rrf_ranker(无) -> Any` （L486）：执行模块级业务逻辑。；调用：`RRFRanker`
- 函数 `_boost_preferred(results, preferred_names) -> list[SearchResult]` （L495）：执行模块级业务逻辑。；调用：`any`, `name.lower`, `result.record.name.lower`, `result.record.tool_name.lower`, `results.sort`
- 函数 `_quoted_list(values) -> str` （L507）：执行模块级业务逻辑。；调用：`join`, `sorted`
- 函数 `_semantic_document(record) -> str` （L511）：执行模块级业务逻辑。；调用：`join`
- 函数 `_search_text(record) -> str` （L515）：执行模块级业务逻辑。；调用：`join`
- 函数 `_truncate_text(text, max_bytes) -> str` （L519）：执行模块级业务逻辑。；调用：`decode`, `len`, `text.encode`

### `mycodingagent/skill_runtime/watcher.py`

- 模块：`mycodingagent.skill_runtime.watcher`
- 职责：Skill 发现、索引、检索、路由、缓存与运行时生命周期。
- 内部依赖：`mycodingagent.configuration`
- 类 `class SkillDirectoryWatcher`（L44）：封装该模块的状态与行为。
  - `__init__(self, root) -> None` （L45）；调用：`Event`, `Lock`
  - `start(self) -> None` （L53）；调用：`Thread`, `_create_backend`, `self._thread.start`, `self.root.mkdir`
  - `stop(self) -> None` （L61）；调用：`self._backend.close`, `self._stop_event.set`, `self._thread.join`
  - `mark_dirty(self) -> None` （L68）；调用：无
  - `consume_dirty(self) -> bool` （L72）；调用：无
  - `async wait_for_change(self, timeout) -> bool` （L78）；调用：`asyncio.get_running_loop`, `asyncio.sleep`, `min`, `self.consume_dirty`, `time`
  - `_run(self) -> None` （L91）；调用：`self._backend.poll`, `self._stop_event.is_set`, `self.mark_dirty`
- 类 `class MultiSkillDirectoryWatcher`（L100）：封装该模块的状态与行为。
  - `__init__(self, roots) -> None` （L101）；调用：`SkillDirectoryWatcher`
  - `start(self) -> None` （L104）；调用：`watcher.start`
  - `stop(self) -> None` （L108）；调用：`watcher.stop`
  - `consume_dirty(self) -> bool` （L112）；调用：`any`, `watcher.consume_dirty`
  - `async wait_for_change(self, timeout) -> bool` （L115）；调用：`asyncio.get_running_loop`, `asyncio.sleep`, `min`, `self.consume_dirty`, `time`
- 类 `class _WatcherBackend`（L129）：封装该模块的状态与行为。
  - `poll(self, stop_event) -> bool` （L130）；调用：无
  - `close(self) -> None` （L133）；调用：无
- 类 `class _InotifyBackend`（L137）：封装该模块的状态与行为。
  - `__init__(self, root) -> None` （L138）；调用：`OSError`, `ctypes.CDLL`, `ctypes.get_errno`, `os.strerror`, `self._add_tree`, `self._libc.inotify_init1`
  - `poll(self, stop_event) -> bool` （L147）；调用：`os.read`, `select.select`, `self._consume_events`, `stop_event.is_set`
  - `close(self) -> None` （L163）；调用：`os.close`
  - `_consume_events(self, data) -> bool` （L169）；调用：`EVENT_STRUCT.unpack_from`, `len`, `raw_name.decode`, `rstrip`, `self._add_tree`, `self._watch_descriptors.get`, `self._watch_descriptors.pop`
  - `_add_tree(self, root) -> None` （L190）；调用：`_iter_directories`, `self._add_watch`
  - `_add_watch(self, directory) -> None` （L194）；调用：`os.fsencode`, `self._libc.inotify_add_watch`, `str`
- 类 `class _PollingBackend`（L202）：封装该模块的状态与行为。
  - `__init__(self, root) -> None` （L203）；调用：`_snapshot`
  - `poll(self, stop_event) -> bool` （L207）；调用：`_snapshot`, `stop_event.wait`
- 函数 `_create_backend(root) -> _WatcherBackend` （L216）：执行模块级业务逻辑。；调用：`_InotifyBackend`, `_PollingBackend`
- 函数 `_iter_directories(root) -> list[Path]` （L223）：执行模块级业务逻辑。；调用：`_should_skip`, `directories.append`, `path.is_dir`, `root.exists`, `root.rglob`
- 函数 `_snapshot(root) -> dict[str, tuple[int, int]]` （L233）：执行模块级业务逻辑。；调用：`_should_skip`, `path.stat`, `root.exists`, `root.rglob`, `str`
- 函数 `_should_skip(path) -> bool` （L248）：执行模块级业务逻辑。；调用：`any`

### `mycodingagent/terminal_ui/__init__.py`

- 模块：`mycodingagent.terminal_ui`
- 职责：Terminal input, rendering, history, selection, and confirmation.
- 内部依赖：无
- 定义：无公开类或函数。

### `mycodingagent/terminal_ui/confirm.py`

- 模块：`mycodingagent.terminal_ui.confirm`
- 职责：终端输入、历史展示、会话选择与确认交互。
- 内部依赖：`mycodingagent.memory`, `mycodingagent.terminal_ui.session_selector`
- 函数 `confirm_cross_workspace_restore(source_workspace, current_workspace) -> bool` （L7）：执行模块级业务逻辑。；调用：`confirm_cross_workspace_action`
- 函数 `confirm_delete_sessions(sessions, include_all) -> bool` （L11）：执行模块级业务逻辑。；调用：`input`, `len`, `lower`, `print`, `print_session_options`, `strip`
- 函数 `confirm_cross_workspace_action(action, source_workspace, current_workspace) -> bool` （L21）：执行模块级业务逻辑。；调用：`input`, `lower`, `print`, `strip`

### `mycodingagent/terminal_ui/history.py`

- 模块：`mycodingagent.terminal_ui.history`
- 职责：终端输入、历史展示、会话选择与确认交互。
- 内部依赖：无
- 函数 `render_conversation_history(messages, max_chars_per_message) -> None` （L6）：执行模块级业务逻辑。；调用：`format_history_message`, `join`, `print`
- 函数 `format_history_message(message, max_chars_per_message) -> str` （L20）：执行模块级业务逻辑。；调用：`call.get`, `get`, `join`, `message.get`, `message_content_to_text`, `truncate_history_text`
- 函数 `message_content_to_text(content) -> str` （L44）：执行模块级业务逻辑。；调用：`isinstance`, `json.dumps`
- 函数 `truncate_history_text(text, max_chars) -> str` （L50）：执行模块级业务逻辑。；调用：`len`

### `mycodingagent/terminal_ui/input.py`

- 模块：`mycodingagent.terminal_ui.input`
- 职责：终端输入、历史展示、会话选择与确认交互。
- 内部依赖：`mycodingagent.commands`
- 函数 `read_user_prompt(prompt, command_registry) -> str` （L27）：执行模块级业务逻辑。；调用：`InteractivePrompt`, `input`, `reader.read`, `sys.stdin.isatty`
- 类 `class InteractivePrompt`（L34）：封装该模块的状态与行为。
  - `__init__(self, prompt, command_registry) -> None` （L35）；调用：`codecs.getincrementaldecoder`, `strip_readline_markers`, `visible_width`
  - `read(self) -> str` （L47）；调用：`char.isprintable`, `self._decoder.reset`, `self._finish`, `self._handle_escape_sequence`, `self._read_char`, `self._render`, `self.accept_selected_suggestion`, `sys.stdin.fileno`, `termios.tcgetattr`, `termios.tcsetattr`, `tty.setraw`
  - `_finish(self) -> str` （L82）；调用：`self._clear_render`, `sys.stdout.flush`, `sys.stdout.write`
  - `_suggestions(self) -> list[CommandSpec]` （L89）；调用：`self.command_registry.suggestions`
  - `_render(self) -> None` （L94）；调用：`clamp_selection`, `join`, `len`, `render_screen`, `safe_render_columns`, `self._clear_render`, `self._hint_lines`, `self._move_cursor_to_input_end`, `self._suggestions`, `sys.stdout.flush`, `sys.stdout.write`
  - `_hint_lines(self, suggestions) -> list[str]` （L109）；调用：`enumerate`, `format_command_argument_usage_panel`, `format_command_suggestion`, `format_command_usage_panel`, `self.command_registry.exact_command`
  - `_clear_render(self) -> None` （L122）；调用：`len`, `range`, `sys.stdout.flush`, `sys.stdout.write`
  - `_move_cursor_to_input_end(self) -> None` （L141）；调用：`len`, `sys.stdout.flush`, `sys.stdout.write`
  - `_handle_escape_sequence(self) -> None` （L152）；调用：`self._drain_escape_sequence`, `self._read_escape_sequence`, `self.move_selection`
  - `_read_escape_sequence(self) -> str` （L164）；调用：`self._read_pending_char`
  - `_read_pending_char(self, timeout) -> str` （L173）；调用：`select.select`, `self._read_char`
  - `_read_char(self) -> str` （L180）；调用：`read_char_from_fd`, `sys.stdin.read`
  - `_drain_escape_sequence(self) -> None` （L185）；调用：`range`, `select.select`, `self._read_char`
  - `move_selection(self, delta) -> None` （L193）；调用：`len`, `self._render`, `self._suggestions`
  - `accept_selected_suggestion(self) -> bool` （L200）；调用：`self._render`, `self._suggestions`, `self.command_registry.exact_command`
- 函数 `format_command_suggestion(spec, selected) -> str` （L216）：执行模块级业务逻辑。；调用：无
- 函数 `format_command_usage_panel(spec) -> list[str]` （L222）：执行模块级业务逻辑。；调用：`join`, `lines.append`, `lines.extend`
- 函数 `format_command_argument_usage_panel(spec, buffer) -> list[str]` （L236）：执行模块级业务逻辑。；调用：`command_argument_prefix`, `command_usage_matches_prefix`, `lines.extend`
- 函数 `command_argument_prefix(spec, buffer) -> str` （L252）：执行模块级业务逻辑。；调用：`buffer.startswith`, `len`, `strip`
- 函数 `command_usage_matches_prefix(usage, prefix) -> bool` （L260）：执行模块级业务逻辑。；调用：`bool`, `usage.strip`, `usage_text.startswith`
- 函数 `clamp_selection(index, suggestion_count) -> int` （L267）：执行模块级业务逻辑。；调用：无
- 函数 `strip_readline_markers(text) -> str` （L277）：执行模块级业务逻辑。；调用：`READLINE_MARKER_RE.sub`
- 函数 `visible_width(text) -> int` （L281）：执行模块级业务逻辑。；调用：`ANSI_ESCAPE_RE.sub`, `character_width`, `strip_readline_markers`, `sum`, `wcswidth`
- 函数 `terminal_width(无) -> int` （L292）：执行模块级业务逻辑。；调用：`max`, `shutil.get_terminal_size`
- 函数 `read_char_from_fd(input_fd, decoder) -> str` （L296）：执行模块级业务逻辑。；调用：`decoder.decode`, `os.read`
- 函数 `read_escape_sequence_from_fd(input_fd, decoder, timeout) -> str` （L306）：执行模块级业务逻辑。；调用：`read_char_from_fd`, `select.select`
- 函数 `safe_render_columns(无) -> int` （L324）：执行模块级业务逻辑。；调用：`max`, `terminal_width`
- 类 `class RenderedScreen`（L328）：封装该模块的状态与行为。
  - `__init__(self, lines, cursor_row, cursor_column) -> None` （L329）；调用：无
- 函数 `render_screen(lines, columns) -> RenderedScreen` （L335）：执行模块级业务逻辑。；调用：`RenderedScreen`, `enumerate`, `hard_wrap_ansi`, `len`, `max`, `screen_lines.extend`, `visible_width`
- 函数 `hard_wrap_ansi(text, columns) -> list[str]` （L348）：执行模块级业务逻辑。；调用：`ANSI_ESCAPE_RE.match`, `join`, `len`, `line_parts.append`, `match.end`, `match.group`, `max`, `parts.append`, `visible_width`
- 函数 `character_width(char) -> int` （L376）：执行模块级业务逻辑。；调用：`ord`, `unicodedata.category`, `unicodedata.combining`, `unicodedata.east_asian_width`

### `mycodingagent/terminal_ui/session_selector.py`

- 模块：`mycodingagent.terminal_ui.session_selector`
- 职责：终端输入、历史展示、会话选择与确认交互。
- 内部依赖：`mycodingagent.memory`, `mycodingagent.terminal_ui.input`
- 函数 `select_session_interactively(memory_runtime, limit, include_all, action) -> str` （L17）：执行模块级业务逻辑。；调用：`clear_session_selector`, `codecs.getincrementaldecoder`, `command_for_session_action`, `decoder.reset`, `len`, `locals`, `memory_runtime.list_migrated_workspace_sessions`, `memory_runtime.list_sessions`, `print`, `print_session_options`, `read_char_from_fd`, `read_escape_sequence_from_fd`, `render_session_selector`, `sys.stdin.fileno`, `sys.stdin.isatty`, `sys.stdout.flush`
- 函数 `render_session_selector(sessions, selected, previous_row_count, include_workspace, action) -> int` （L98）：执行模块级业务逻辑。；调用：`clear_session_selector`, `enumerate`, `format_session_option`, `join`, `len`, `logical_lines.extend`, `render_screen`, `safe_render_columns`, `sys.stdout.flush`, `sys.stdout.write`
- 函数 `clear_session_selector(rendered_row_count) -> None` （L123）：执行模块级业务逻辑。；调用：`range`, `sys.stdout.flush`, `sys.stdout.write`
- 函数 `print_session_options(sessions, include_workspace) -> None` （L137）：执行模块级业务逻辑。；调用：`format_session_option`, `print`
- 函数 `command_for_session_action(action) -> str` （L142）：执行模块级业务逻辑。；调用：`get`
- 函数 `format_session_option(session, selected, include_workspace) -> str` （L151）：执行模块级业务逻辑。；调用：无

### `mycodingagent/tool_runtime/__init__.py`

- 模块：`mycodingagent.tool_runtime`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.memory`, `mycodingagent.tool_runtime.ask_user`, `mycodingagent.tool_runtime.base`, `mycodingagent.tool_runtime.bash`, `mycodingagent.tool_runtime.edit_file`, `mycodingagent.tool_runtime.file_state_cache`, `mycodingagent.tool_runtime.glob`, `mycodingagent.tool_runtime.grep`, `mycodingagent.tool_runtime.memory_lookup`, `mycodingagent.tool_runtime.read_file`, `mycodingagent.tool_runtime.write_file`, `mycodingagent.workspace.file_cache`
- 类 `class ToolRegistry`（L12）：封装该模块的状态与行为。
  - `__init__(self) -> None` （L13）；调用：`set`
  - `register(self, tool) -> None` （L17）；调用：无
  - `get(self, name) -> Tool | None` （L20）；调用：`self._tools.get`
  - `is_enabled(self, name) -> bool` （L24）；调用：无
  - `enable(self, name) -> None` （L27）；调用：`self._disabled.discard`
  - `disable(self, name) -> None` （L31）；调用：`self._disabled.add`
  - `enable_all(self) -> None` （L35）；调用：`self._disabled.clear`
  - `list_tools(self) -> list[Tool]` （L39）；调用：`list`, `self._tools.values`
  - `get_all_schemas(self, protocol) -> list[dict[str, Any]]` （L43）；调用：`schemas.append`, `self._tools.items`, `tool.get_schema`
- 函数 `create_default_registry(file_cache, file_history, file_state_cache, workspace_tracker, memory_runtime) -> ToolRegistry` （L61）：执行模块级业务逻辑。；调用：`AskUser`, `Bash`, `EditFile`, `FileStateCache`, `GetRecentConversationTurns`, `GetStoredToolOutput`, `Glob`, `Grep`, `ReadFile`, `RecoverContext`, `RestoreSession`, `SearchRecoverableContext`, `SearchSessionHistory`, `SummarizeCurrentTurnMessage`, `ToolRegistry`, `WriteFile`

### `mycodingagent/tool_runtime/ask_user.py`

- 模块：`mycodingagent.tool_runtime.ask_user`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.tool_runtime.base`
- 类 `class AskUserParams`（L8）：封装该模块的状态与行为。
- 类 `class AskUser`（L14）：封装该模块的状态与行为。
  - `async execute(self, params) -> ToolResult` （L25）；调用：`ToolResult`, `input`, `join`, `line.rstrip`, `params.intent.split`, `params.query.split`, `print`, `splitlines`, `str`, `strip`

### `mycodingagent/tool_runtime/base.py`

- 模块：`mycodingagent.tool_runtime.base`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.configuration`
- 函数 `get_sandbox_root(无) -> Path` （L21）：执行模块级业务逻辑。；调用：`CONFIG.sandbox.root.expanduser`, `resolve`
- 函数 `is_path_in_sandbox(path, sandbox_root) -> bool` （L25）：执行模块级业务逻辑。；调用：`path.relative_to`
- 函数 `resolve_sandbox_path(raw_path, sandbox_root) -> tuple[Path | None, str]` （L33）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `get_sandbox_root`, `is_path_in_sandbox`, `path.is_absolute`, `path.relative_to`, `path.resolve`, `raw_path.strip`, `resolve`
- 类 `class ToolResult`（L57）：封装该模块的状态与行为。
- 类 `class Tool`（L62）：封装该模块的状态与行为。
  - `is_read_only(self) -> bool` （L71）；调用：无
  - `get_schema(self) -> dict[str, Any]` （L75）；调用：`isinstance`, `required.append`, `schema.pop`, `schema.setdefault`, `self.params_model.model_json_schema`
  - `async execute(self, params) -> ToolResult` （L95）；调用：无

### `mycodingagent/tool_runtime/bash.py`

- 模块：`mycodingagent.tool_runtime.bash`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.tool_runtime.base`
- 函数 `get_docker_image(无) -> str` （L29）：执行模块级业务逻辑。；调用：无
- 函数 `get_docker_pull_timeout(无) -> int` （L33）：执行模块级业务逻辑。；调用：无
- 函数 `docker_subprocess_env(无) -> dict[str, str]` （L37）：执行模块级业务逻辑。；调用：`Path`, `docker_config.mkdir`, `env.get`, `get_sandbox_root`, `os.environ.copy`, `str`
- 类 `class Params`（L45）：封装该模块的状态与行为。
- 类 `class Bash`（L53）：封装该模块的状态与行为。
  - `__init__(self, sandbox_root) -> None` （L62）；调用：`get_sandbox_root`
  - `async execute(self, params) -> ToolResult` （L66）；调用：`ToolResult`, `asyncio.create_subprocess_exec`, `asyncio.wait_for`, `docker_subprocess_env`, `get_docker_image`, `join`, `min`, `os.getgid`, `os.getuid`, `parts.append`, `proc.communicate`, `proc.kill`
  - `async ensure_image(self, image) -> ToolResult` （L143）；调用：`ToolResult`, `get_docker_image`, `self._build_image_from_dockerfile`, `self._check_docker_daemon`, `self._check_image_available`, `self._check_image_supports_bash`, `self._find_sandbox_dockerfile`, `self._is_local_sandbox_image`, `self._pull_image`, `shutil.which`
  - `_is_local_sandbox_image(self, image) -> bool` （L185）；调用：`image.startswith`
  - `_find_sandbox_dockerfile(self) -> Path | None` （L188）；调用：`Path`, `candidate.is_file`, `resolve`
  - `async _build_image_from_dockerfile(self, image, dockerfile) -> str` （L198）；调用：`asyncio.create_subprocess_exec`, `asyncio.wait_for`, `docker_subprocess_env`, `get_docker_pull_timeout`, `proc.communicate`, `proc.kill`, `proc.wait`, `self._decode_output`, `str`
  - `async _check_docker_daemon(self) -> str` （L239）；调用：`asyncio.create_subprocess_exec`, `asyncio.wait_for`, `detail.lower`, `docker_subprocess_env`, `proc.communicate`, `proc.kill`, `proc.wait`, `self._decode_output`
  - `async _check_image_available(self, image) -> str` （L271）；调用：`asyncio.create_subprocess_exec`, `asyncio.wait_for`, `docker_subprocess_env`, `proc.communicate`, `proc.kill`, `proc.wait`, `stderr.decode`, `strip`
  - `async _check_image_supports_bash(self, image) -> str` （L300）；调用：`asyncio.create_subprocess_exec`, `asyncio.wait_for`, `docker_subprocess_env`, `proc.communicate`, `proc.kill`, `proc.wait`, `stderr.decode`, `strip`
  - `async _pull_image(self, image) -> str` （L334）；调用：`asyncio.create_subprocess_exec`, `asyncio.wait_for`, `docker_subprocess_env`, `get_docker_pull_timeout`, `proc.communicate`, `proc.kill`, `proc.wait`, `self._decode_output`
  - `_decode_output(self, stdout, stderr) -> str` （L358）；调用：`join`, `parts.append`, `stderr.decode`, `stdout.decode`, `strip`
  - `async _force_remove_container(self, container_name) -> None` （L366）；调用：`asyncio.create_subprocess_exec`, `asyncio.wait_for`, `docker_subprocess_env`, `proc.wait`
- 函数 `async ensure_docker_image(image) -> ToolResult` （L382）：执行模块级业务逻辑。；调用：`Bash`, `ensure_image`

### `mycodingagent/tool_runtime/edit_file.py`

- 模块：`mycodingagent.tool_runtime.edit_file`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.tool_runtime.base`, `mycodingagent.tool_runtime.file_state_cache`, `mycodingagent.workspace.file_cache`
- 类 `class Params`（L15）：封装该模块的状态与行为。
- 类 `class EditFile`（L21）：封装该模块的状态与行为。
  - `__init__(self, file_cache, file_history, file_state_cache, workspace_tracker, sandbox_root) -> None` （L32）；调用：无
  - `async execute(self, params) -> ToolResult` （L47）；调用：`ToolResult`, `content.count`, `content.replace`, `path.exists`, `path.read_text`, `path.write_text`, `resolve_sandbox_path`, `self._cache.invalidate`, `self._state_cache.check`, `self._state_cache.update`, `self._workspace_tracker.mark_agent_write`, `self.file_history.track_edit`

### `mycodingagent/tool_runtime/file_state_cache.py`

- 模块：`mycodingagent.tool_runtime.file_state_cache`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：无
- 类 `class FileStateCache`（L7）：封装该模块的状态与行为。
  - `__init__(self) -> None` （L12）；调用：`Lock`
  - `record(self, path, content, mtime_ns) -> None` （L16）；调用：无
  - `has_read(self, path) -> bool` （L21）；调用：无
  - `get_state(self, path) -> tuple[str, int] | None` （L25）；调用：`self._cache.get`
  - `to_dict(self) -> dict` （L29）；调用：`self._cache.items`
  - `load_dict(self, data) -> None` （L37）；调用：`data.get`, `isinstance`, `item.get`
  - `is_stale(self, path) -> bool` （L52）；调用：`Path`, `self._cache.get`, `stat`
  - `check(self, path) -> tuple[bool, str]` （L64）；调用：`Path`, `self._cache.get`, `stat`
  - `update(self, path) -> None` （L84）；调用：`Path`, `p.read_text`, `p.stat`, `self._cache.pop`
- 函数 `file_state_paths(snapshot) -> list[str]` （L98）：执行模块级业务逻辑。；调用：`isinstance`, `item.get`, `snapshot.get`

### `mycodingagent/tool_runtime/glob.py`

- 模块：`mycodingagent.tool_runtime.glob`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.tool_runtime.base`
- 类 `class Params`（L14）：封装该模块的状态与行为。
- 类 `class Glob`（L19）：封装该模块的状态与行为。
  - `__init__(self, sandbox_root) -> None` （L29）；调用：无
  - `async execute(self, params) -> ToolResult` （L33）；调用：`ToolResult`, `_iter_matching_files`, `base.exists`, `file_path.relative_to`, `join`, `len`, `matches.append`, `matches.sort`, `resolve_sandbox_path`, `str`
- 函数 `_iter_matching_files(base, pattern, sandbox_root) -> 未声明` （L58）：执行模块级业务逻辑。；调用：`Path`, `_matches`, `base.glob`, `os.walk`
- 函数 `_matches(file_path, base, pattern, sandbox_root) -> bool` （L75）：执行模块级业务逻辑。；调用：`any`, `file_path.is_file`, `file_path.relative_to`, `file_path.resolve`, `fnmatch.fnmatch`, `is_path_in_sandbox`, `pattern.startswith`, `str`

### `mycodingagent/tool_runtime/grep.py`

- 模块：`mycodingagent.tool_runtime.grep`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.tool_runtime.base`
- 类 `class Params`（L15）：封装该模块的状态与行为。
- 类 `class Grep`（L21）：封装该模块的状态与行为。
  - `__init__(self, sandbox_root) -> None` （L31）；调用：无
  - `async execute(self, params) -> ToolResult` （L35）；调用：`ToolResult`, `_iter_search_files`, `base.exists`, `enumerate`, `file_path.read_text`, `join`, `len`, `re.compile`, `regex.search`, `resolve_sandbox_path`, `results.append`, `text.splitlines`
- 函数 `_iter_search_files(base, include_pattern, sandbox_root) -> 未声明` （L68）：执行模块级业务逻辑。；调用：`Path`, `_include_matches`, `any`, `file_path.relative_to`, `file_path.resolve`, `is_path_in_sandbox`, `os.walk`, `sorted`, `str`
- 函数 `_include_matches(relative_path, include_pattern) -> bool` （L90）：执行模块级业务逻辑。；调用：`Path`, `fnmatch.fnmatch`, `include_pattern.startswith`

### `mycodingagent/tool_runtime/mcp_discovery.py`

- 模块：`mycodingagent.tool_runtime.mcp_discovery`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.capability_discovery`, `mycodingagent.mcp_integration`, `mycodingagent.tool_runtime.base`
- 类 `class PaginationParams`（L16）：封装该模块的状态与行为。
- 类 `class ServerSearchParams`（L21）：封装该模块的状态与行为。
- 类 `class ServerNameParams`（L25）：封装该模块的状态与行为。
- 类 `class ServerItemSearchParams`（L29）：封装该模块的状态与行为。
- 类 `class _ServerItemsTool`（L33）：封装该模块的状态与行为。
  - `__init__(self, manager, router) -> None` （L41）；调用：无
  - `async execute(self, params) -> ToolResult` （L45）；调用：`_json_result`, `_paginate`, `getattr`, `method`, `result.get`, `self._router.record_mcp_server_use`
- 类 `class _ServerItemSearchTool`（L59）：封装该模块的状态与行为。
  - `async execute(self, params) -> ToolResult` （L62）；调用：`_json_result`, `_paginate`, `_search_items`, `getattr`, `method`, `result.get`, `self._router.record_mcp_server_use`
- 类 `class ListServersTool`（L77）：封装该模块的状态与行为。
  - `__init__(self, manager) -> None` （L90）；调用：无
  - `async execute(self, params) -> ToolResult` （L93）；调用：`_json_result`, `_paginate`, `self._manager.list_servers`, `server.to_payload`
- 类 `class SearchServersTool`（L98）：封装该模块的状态与行为。
  - `__init__(self, router) -> None` （L109）；调用：无
  - `async execute(self, params) -> ToolResult` （L112）；调用：`_json_result`, `_paginate`, `item.to_payload`, `self._router.route`
- 类 `class ListToolsTool`（L128）：封装该模块的状态与行为。
- 类 `class SearchToolsTool`（L135）：封装该模块的状态与行为。
- 类 `class ListResourcesTool`（L142）：封装该模块的状态与行为。
- 类 `class SearchResourcesTool`（L149）：封装该模块的状态与行为。
- 类 `class ListPromptsTool`（L156）：封装该模块的状态与行为。
- 类 `class SearchPromptsTool`（L163）：封装该模块的状态与行为。
- 函数 `register_mcp_discovery_tools(registry, manager, router) -> None` （L170）：执行模块级业务逻辑。；调用：`ListPromptsTool`, `ListResourcesTool`, `ListServersTool`, `ListToolsTool`, `SearchPromptsTool`, `SearchResourcesTool`, `SearchServersTool`, `SearchToolsTool`, `registry.register`
- 函数 `_search_items(query, items) -> list[dict]` （L186）：执行模块级业务逻辑。；调用：`get`, `item.get`, `list`, `lower`, `query.replace`, `scored.append`, `scored.sort`, `split`, `str`, `sum`, `term.lower`, `term.strip`
- 函数 `_paginate(items, offset, limit, item_key) -> dict` （L200）：执行模块级业务逻辑。；调用：`len`, `max`, `min`
- 函数 `_json_result(payload, is_error) -> ToolResult` （L218）：执行模块级业务逻辑。；调用：`ToolResult`, `json.dumps`

### `mycodingagent/tool_runtime/mcp_execution.py`

- 模块：`mycodingagent.tool_runtime.mcp_execution`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.mcp_integration.hooks`, `mycodingagent.mcp_integration.manager`, `mycodingagent.mcp_integration.policy`, `mycodingagent.tool_runtime.base`
- 类 `class CallToolParams`（L16）：封装该模块的状态与行为。
- 类 `class ReadResourceParams`（L23）：封装该模块的状态与行为。
- 类 `class GetPromptParams`（L29）：封装该模块的状态与行为。
- 类 `class CallMCPToolTool`（L36）：封装该模块的状态与行为。
  - `__init__(self, manager, policy, approval_hook) -> None` （L47）；调用：无
  - `async execute(self, params) -> ToolResult` （L57）；调用：`MCPApprovalRequest`, `ToolResult`, `_compact_intent`, `_json_result`, `result.to_payload`, `self._approval_hook.approve`, `self._manager.call_tool`, `self._manager.server_configs.get`, `self._policy.classify`, `self._policy.requires_approval`
- 类 `class ReadMCPResourceTool`（L87）：封装该模块的状态与行为。
  - `__init__(self, manager) -> None` （L95）；调用：无
  - `async execute(self, params) -> ToolResult` （L98）；调用：`ToolResult`, `_compact_intent`, `_json_result`, `result.to_payload`, `self._manager.read_resource`
- 类 `class GetMCPPromptTool`（L112）：封装该模块的状态与行为。
  - `__init__(self, manager) -> None` （L120）；调用：无
  - `async execute(self, params) -> ToolResult` （L123）；调用：`ToolResult`, `_compact_intent`, `_json_result`, `result.to_payload`, `self._manager.get_prompt`
- 函数 `register_mcp_execution_tools(registry, manager, policy, approval_hook) -> None` （L137）：执行模块级业务逻辑。；调用：`CallMCPToolTool`, `GetMCPPromptTool`, `ReadMCPResourceTool`, `registry.register`
- 函数 `_compact_intent(value) -> str` （L149）：执行模块级业务逻辑。；调用：`join`, `len`, `split`, `str`
- 函数 `_json_result(payload, is_error) -> ToolResult` （L156）：执行模块级业务逻辑。；调用：`ToolResult`, `json.dumps`

### `mycodingagent/tool_runtime/memory_lookup.py`

- 模块：`mycodingagent.tool_runtime.memory_lookup`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.memory`, `mycodingagent.tool_runtime.base`
- 类 `class GetStoredToolOutputParams`（L15）：封装该模块的状态与行为。
- 类 `class GetStoredToolOutput`（L21）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime) -> None` （L34）；调用：无
  - `async execute(self, params) -> ToolResult` （L37）；调用：`recover_context_output`, `self._memory_runtime.drain`
- 类 `class RecoverContextParams`（L47）：封装该模块的状态与行为。
- 类 `class RecoverContext`（L53）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime) -> None` （L66）；调用：无
  - `async execute(self, params) -> ToolResult` （L69）；调用：`recover_context_output`, `self._memory_runtime.drain`
- 类 `class SearchRecoverableContextParams`（L79）：封装该模块的状态与行为。
- 类 `class SearchRecoverableContext`（L84）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime) -> None` （L97）；调用：无
  - `async execute(self, params) -> ToolResult` （L100）；调用：`ToolResult`, `context.to_dict`, `json.dumps`, `len`, `self._memory_runtime.drain`, `self._memory_runtime.get_current_session_id`, `self._memory_runtime.search_context_metadata`
- 类 `class SearchSessionHistoryParams`（L115）：封装该模块的状态与行为。
- 类 `class SearchSessionHistory`（L121）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime, preview_chars) -> None` （L133）；调用：无
  - `async execute(self, params) -> ToolResult` （L137）；调用：`ToolResult`, `asdict`, `enumerate`, `join`, `json.dumps`, `len`, `message.get`, `message_to_search_text`, `params.query.split`, `query.lower`, `results.append`, `searchable.lower`
- 类 `class GetRecentConversationTurnsParams`（L201）：封装该模块的状态与行为。
- 类 `class GetRecentConversationTurns`（L205）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime) -> None` （L217）；调用：无
  - `async execute(self, params) -> ToolResult` （L220）；调用：`ToolResult`, `asdict`, `json.dumps`, `len`, `self._memory_runtime.drain`, `self._memory_runtime.get_current_session_id`, `self._memory_runtime.store.load_historical_turns`
- 类 `class SummarizeCurrentTurnMessageParams`（L243）：封装该模块的状态与行为。
- 类 `class SummarizeCurrentTurnMessage`（L251）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime) -> None` （L262）；调用：无
  - `async execute(self, params) -> ToolResult` （L265）；调用：`ToolResult`, `asdict`, `json.dumps`, `self._memory_runtime.summarize_current_turn_message`
- 类 `class RestoreSessionParams`（L284）：封装该模块的状态与行为。
- 类 `class RestoreSession`（L288）：封装该模块的状态与行为。
  - `__init__(self, memory_runtime) -> None` （L298）；调用：无
  - `async execute(self, params) -> ToolResult` （L301）；调用：`ToolResult`, `asdict`, `json.dumps`, `self._memory_runtime.drain`, `self._memory_runtime.restore_historical_session_snapshot`
- 函数 `message_to_search_text(message) -> str` （L317）：执行模块级业务逻辑。；调用：`isinstance`, `json.dumps`, `message.get`
- 函数 `recover_context_output(memory_runtime, context_id, offset, limit) -> ToolResult` （L329）：执行模块级业务逻辑。；调用：`ToolResult`, `json.dumps`, `len`, `memory_runtime.get_context_metadata`, `memory_runtime.get_tool_output`, `memory_runtime.load_partial_context`, `min`
- 函数 `truncate_one_line(text, max_chars) -> str` （L386）：执行模块级业务逻辑。；调用：`join`, `len`, `split`, `text.strip`

### `mycodingagent/tool_runtime/read_file.py`

- 模块：`mycodingagent.tool_runtime.read_file`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.tool_runtime.base`, `mycodingagent.tool_runtime.file_state_cache`, `mycodingagent.workspace.file_cache`
- 类 `class Params`（L15）：封装该模块的状态与行为。
- 类 `class ReadFile`（L21）：封装该模块的状态与行为。
  - `__init__(self, file_cache, file_state_cache, sandbox_root) -> None` （L29）；调用：无
  - `async execute(self, params) -> ToolResult` （L40）；调用：`ToolResult`, `enumerate`, `join`, `path.exists`, `path.is_file`, `path.read_text`, `path.stat`, `resolve_sandbox_path`, `self._cache.get`, `self._cache.put`, `self._state_cache.record`, `str`

### `mycodingagent/tool_runtime/skill_tools.py`

- 模块：`mycodingagent.tool_runtime.skill_tools`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.skill_runtime.contracts`, `mycodingagent.tool_runtime.base`
- 类 `class SearchSkillParams`（L11）：封装该模块的状态与行为。
- 类 `class SearchSkillTool`（L22）：封装该模块的状态与行为。
  - `__init__(self, runtime) -> None` （L37）；调用：无
  - `async execute(self, params) -> ToolResult` （L40）；调用：`ToolResult`, `json.dumps`, `self._runtime.search_skill_schemas`
- 类 `class GetAllToolParams`（L49）：封装该模块的状态与行为。
- 类 `class GetAllTool`（L53）：封装该模块的状态与行为。
  - `__init__(self, runtime) -> None` （L68）；调用：无
  - `async execute(self, params) -> ToolResult` （L71）；调用：`ToolResult`, `json.dumps`, `self._runtime.list_skill_tools`
- 类 `class GetToolByNameParams`（L76）：封装该模块的状态与行为。
- 类 `class GetToolByNameTool`（L80）：封装该模块的状态与行为。
  - `__init__(self, runtime) -> None` （L92）；调用：无
  - `async execute(self, params) -> ToolResult` （L95）；调用：`ToolResult`, `bool`, `json.dumps`, `result.get`, `self._runtime.get_tool_schema_by_name`
- 类 `class SearchSkillReferencesParams`（L100）：封装该模块的状态与行为。
- 类 `class SearchSkillReferencesTool`（L106）：封装该模块的状态与行为。
  - `__init__(self, runtime) -> None` （L118）；调用：无
  - `async execute(self, params) -> ToolResult` （L121）；调用：`ToolResult`, `json.dumps`, `self._runtime.search_skill_references`
- 类 `class GetSkillReferenceParams`（L130）：封装该模块的状态与行为。
- 类 `class GetSkillReferenceTool`（L135）：封装该模块的状态与行为。
  - `__init__(self, runtime) -> None` （L146）；调用：无
  - `async execute(self, params) -> ToolResult` （L149）；调用：`ToolResult`, `bool`, `json.dumps`, `result.get`, `self._runtime.get_skill_reference`
- 类 `class SkillInvocationParams`（L157）：封装该模块的状态与行为。
- 类 `class SkillTool`（L162）：封装该模块的状态与行为。
  - `__init__(self, runtime, tool_name) -> None` （L166）；调用：`self._runtime.get_record`
  - `async execute(self, params) -> ToolResult` （L180）；调用：`ToolResult`, `join`, `json.dumps`, `self._runtime.get_record`, `self._runtime.list_references_for_skill`, `self._runtime.record_skill_invocation`
- 函数 `skill_schema_from_record(record) -> dict` （L214）：执行模块级业务逻辑。；调用：`SkillInvocationParams.model_json_schema`

### `mycodingagent/tool_runtime/workspace_change_tracker.py`

- 模块：`mycodingagent.tool_runtime.workspace_change_tracker`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.configuration`, `mycodingagent.tool_runtime.file_state_cache`
- 类 `class WorkspaceChangeTracker`（L41）：封装该模块的状态与行为。
  - `__init__(self, root, file_state_cache, max_changes) -> None` （L42）；调用：`Event`, `Lock`, `root.resolve`, `set`
  - `start(self) -> None` （L53）；调用：`Thread`, `_InotifyWorkspaceBackend`, `_PollingWorkspaceBackend`, `self._thread.start`, `self.root.mkdir`
  - `close(self) -> None` （L64）；调用：`self._backend.close`, `self._stop_event.set`, `self._thread.join`
  - `mark_agent_write(self, path) -> None` （L71）；调用：`Path`, `_fingerprint`, `self._changed_paths.discard`, `self._normalize_path`
  - `mark_paths_for_recheck(self, paths) -> None` （L80）；调用：`self._agent_writes.pop`, `self._changed_paths.add`, `self._normalize_path`
  - `consume_external_changes(self) -> tuple[list[str], int]` （L87）；调用：`_display_path`, `len`, `max`, `self._changed_paths.clear`, `self._is_agent_write`, `self.file_state_cache.has_read`, `self.file_state_cache.is_stale`, `sorted`, `stale_paths.append`
  - `_run(self) -> None` （L105）；调用：`self._backend.poll`, `self._stop_event.is_set`
  - `_record_change(self, path, is_delete) -> None` （L111）；调用：`path.is_dir`, `self._changed_paths.add`, `self._is_agent_write`, `self._normalize_path`, `self.file_state_cache.has_read`, `str`
  - `_is_agent_write(self, path) -> bool` （L122）；调用：`Path`, `_fingerprint`, `self._agent_writes.get`, `self._agent_writes.pop`
  - `_normalize_path(self, path) -> str` （L134）；调用：`Path`, `resolve`, `str`
- 类 `class _WorkspaceBackend`（L138）：封装该模块的状态与行为。
  - `poll(self, stop_event) -> None` （L139）；调用：无
  - `close(self) -> None` （L142）；调用：无
- 类 `class _InotifyWorkspaceBackend`（L146）：封装该模块的状态与行为。
  - `__init__(self, root, on_change) -> None` （L147）；调用：`OSError`, `ctypes.CDLL`, `ctypes.get_errno`, `os.strerror`, `self._add_tree`, `self._libc.inotify_init1`
  - `poll(self, stop_event) -> None` （L157）；调用：`os.read`, `select.select`, `self._consume_events`, `stop_event.is_set`
  - `close(self) -> None` （L171）；调用：`os.close`
  - `_consume_events(self, data) -> None` （L177）；调用：`EVENT_STRUCT.unpack_from`, `_should_skip`, `bool`, `len`, `raw_name.decode`, `rstrip`, `self._add_tree`, `self._on_change`, `self._watch_descriptors.get`, `self._watch_descriptors.pop`
  - `_add_tree(self, root) -> None` （L200）；调用：`_iter_directories`, `self._add_watch`
  - `_add_watch(self, directory) -> None` （L204）；调用：`os.fsencode`, `self._libc.inotify_add_watch`, `str`
- 类 `class _PollingWorkspaceBackend`（L212）：封装该模块的状态与行为。
  - `__init__(self, root, on_change) -> None` （L213）；调用：`_snapshot`
  - `poll(self, stop_event) -> None` （L218）；调用：`Path`, `_snapshot`, `changed_paths.add`, `self._on_change`, `set`, `stop_event.wait`
- 函数 `_iter_directories(root) -> list[Path]` （L230）：执行模块级业务逻辑。；调用：`_should_skip`, `directories.append`, `path.is_dir`, `root.exists`, `root.rglob`
- 函数 `_should_skip(path) -> bool` （L240）：执行模块级业务逻辑。；调用：`any`
- 函数 `_snapshot(root) -> dict[str, tuple[int, int]]` （L244）：执行模块级业务逻辑。；调用：`_fingerprint`, `_should_skip`, `path.is_dir`, `path.resolve`, `root.exists`, `root.rglob`, `str`
- 函数 `_fingerprint(path) -> tuple[int, int] | None` （L257）：执行模块级业务逻辑。；调用：`path.stat`
- 函数 `_display_path(root, path) -> str` （L265）：执行模块级业务逻辑。；调用：`Path`, `relative_to`, `str`

### `mycodingagent/tool_runtime/write_file.py`

- 模块：`mycodingagent.tool_runtime.write_file`
- 职责：工具契约、注册表以及文件、Shell、记忆、MCP、Skill 工具适配器。
- 内部依赖：`mycodingagent.tool_runtime.base`, `mycodingagent.tool_runtime.file_state_cache`, `mycodingagent.workspace.file_cache`
- 类 `class Params`（L15）：封装该模块的状态与行为。
- 类 `class WriteFile`（L20）：封装该模块的状态与行为。
  - `__init__(self, file_cache, file_history, file_state_cache, workspace_tracker, sandbox_root) -> None` （L31）；调用：无
  - `async execute(self, params) -> ToolResult` （L46）；调用：`ToolResult`, `path.exists`, `path.parent.mkdir`, `path.write_text`, `resolve_sandbox_path`, `self._cache.invalidate`, `self._state_cache.check`, `self._state_cache.update`, `self._workspace_tracker.mark_agent_write`, `self.file_history.track_edit`, `str`

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
  - `__init__(self) -> None` （L9）；调用：`threading.Lock`
  - `get(self, path) -> str | None` （L13）；调用：`self._store.get`
  - `put(self, path, content) -> None` （L18）；调用：无
  - `invalidate(self, path) -> None` （L23）；调用：`self._store.pop`
  - `clear(self) -> None` （L28）；调用：`self._store.clear`
  - `__len__(self) -> int` （L33）；调用：`len`

### `mycodingagent/workspace/identity.py`

- 模块：`mycodingagent.workspace.identity`
- 职责：工作区身份、文件缓存和工作区状态。
- 内部依赖：无
- 函数 `workspace_root_text(root) -> str` （L8）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `resolve`, `str`
- 函数 `workspace_label(root) -> str` （L12）：执行模块级业务逻辑。；调用：`Path`, `expanduser`, `resolve`, `str`
- 函数 `workspace_fingerprint(root) -> str` （L17）：执行模块级业务逻辑。；调用：`Path`, `_git_fingerprint`, `expanduser`, `hashlib.sha256`, `hexdigest`, `join`, `marker.exists`, `marker.is_file`, `marker.read_bytes`, `markers.append`, `raw.encode`, `resolve`, `str`
- 函数 `_git_fingerprint(path) -> str` （L34）：执行模块级业务逻辑。；调用：`hashlib.sha256`, `hexdigest`, `raw.encode`, `str`, `strip`, `subprocess.check_output`

## 6. 验证与维护规则

- `tests/test_architecture_boundaries.py` 检查无循环依赖、根目录薄入口、角色目录和关键依赖方向。
- 每次移动、增加或删除模块、类、函数后，必须同步更新本文件。
- 每次修改多智能体流程后，必须验证 `direct`、`audit_only` 和 `implementation` 三种模式。
- 最终交付前运行：`.venv/bin/python -m compileall -q mycodingagent tests __main__.py`、`.venv/bin/python -m pytest -q` 和 `git diff --check`。
