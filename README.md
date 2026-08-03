# myCodingAgent

myCodingAgent 是一个本地 Coding Agent 运行框架。用户在终端用自然语言提出开发、分析、测试或项目维护需求，Runtime 负责组装上下文、路由能力、调用模型、执行工具、保存状态，并在长会话中通过上下文虚拟化和长期记忆保持可持续工作。

项目核心目标不是提供一个单次问答助手，而是构建可长期运行、可恢复、可扩展、可审计的 Agent Harness。

---

## 1. 项目主流程

```text
启动 CLI
  -> 初始化配置、Docker 沙箱、MemoryRuntime、SkillRuntime、MCP、工具注册表
  -> 读取用户输入
  -> 命令分流：仅当输入完整匹配 /resume、/multiAgent、/clear、/delete 等命令时由 Runtime 处理
  -> 普通用户请求进入模型执行流程
  -> 能力路由与长期记忆检索
  -> 构造 Runtime Context + 当前用户请求
  -> 调用 LLM
  -> 执行模型 tool calls
  -> 工具结果写回消息历史
  -> 循环直到模型停止调用工具并输出最终回答
  -> 保存会话、LRFU、文件状态、上下文检查点
  -> 会话结束后调度长期记忆抽取
```

这个流程由 `mycodingagent/app/main.py` 作为组合根启动，核心执行循环在 `mycodingagent/llm_runtime/client.py`，会话和上下文状态由 `mycodingagent/memory/` 维护。

## 1.1 一键安装

在项目根目录执行：

```bash
bash scripts/install.sh
```

脚本会创建 `.venv`、安装 `requirements.txt`、在 `${XDG_BIN_HOME:-~/.local/bin}` 安装 `myAgent` 命令，
并构建 `mycodingagent-sandbox:py312` Docker 镜像。Docker 输入文件没有变化时不会重复构建。
Python/TypeScript、Go、Rust 等 LSP 属于可选分析工具，脚本会询问是否安装；Java 的 `jdtls` 需要单独下载
Eclipse JDT Language Server。缺少某个外部工具链时，脚本会给出提示，但不会阻止 Python 项目启动。

只安装 Python 依赖、不构建 Docker 或不安装 LSP 时可以使用：

```bash
bash scripts/install.sh --skip-docker
bash scripts/install.sh --skip-lsp
```

脚本支持重复执行。LSP 进程运行在宿主机上，必须让启动 `myAgent` 的 shell 能在 `PATH` 中找到对应
可执行程序；Bash 命令仍然在 Docker 沙箱内执行。

安装完成后可以在任意工作区直接启动：

```bash
myAgent
```

如 shell 中存在旧的 `myAgent` alias，先执行 `unalias myAgent` 并从 shell 配置中删除旧定义。普通启动保持原来的
快速流程；需要更新依赖时追加 `--upgrade`：

```bash
myAgent --upgrade
```

该模式会自动安装必要 Python 依赖并准备 Docker 镜像；Python/TypeScript、Go、Rust 等语言服务器属于可选分析工具，
会在交互终端逐项询问是否安装。非交互终端会跳过可选项并给出提示。

---

## 2. 启动流程

### 2.1 配置加载

启动时先由 `mycodingagent/configuration/bootstrap.py` 确保用户配置目录存在，再读取
`mycodingagent/configuration/settings.py` 的内置默认值、用户 JSON 配置和环境变量。
运行时只读取两个来源，优先级如下：

1. `~/.mycodingagent/config.json`
2. 环境变量（当 JSON 字段缺失或为空字符串时生效）

首次启动会从仓库 `.mycodingagent/config.example.json` 创建 `~/.mycodingagent/config.json`，
并且每次启动都会把 `docs/configuration.md` 复制到 `~/.mycodingagent/README.md`。
仓库内 `.mycodingagent/config.example.json` / `.mycodingagent/config.example.yaml` 仅作为字段参考，
不参与运行时配置读取。所有核心参数都可以放入配置文件，也仍然支持环境变量兜底，包括：

- API 地址、模型名、密钥
- Docker 沙箱镜像、CPU/内存/超时限制
- 上下文窗口、压缩阈值、热工作区阈值
- Skill 检索、Milvus、Embedding、LRFU 参数
- MCP 配置路径和后台重连频率
- `MYCODINGAGENT_MEMORY_WORKSPACE_SNAPSHOT_TTL_DAYS`：workspace checkpoint/blob 保留天数，默认 30 天
- `MYCODINGAGENT_LSP_<LANGUAGE>_COMMAND`：覆盖某语言的 LSP 启动命令，例如 `MYCODINGAGENT_LSP_PYTHON_COMMAND="pyright-langserver --stdio"`
- 多智能体最大轮次和并发任务数
- 长期记忆存储/查询模型、抽取超时和启动回填开关

Embedding 支持本地模型、Ollama HTTP、OpenAI-compatible 在线接口、DashScope 原生接口和 hash fallback。
当当前 embedding provider/model/endpoint/API format/query instruction/request extra 形成的签名与 Milvus 中已索引签名不一致时，
Skill 向量会在启动同步阶段重新嵌入并 upsert，避免不同模型共用旧向量。

Agent 自己生成的系统规则、工具说明、Runtime Context 说明值和本地结果包装统一使用中文。工具名、JSON 字段、状态枚举、代码标识、用户原文、Skill 原文以及外部命令/LSP/MCP 的原始输出保持原样，避免翻译破坏协议或证据。

### 2.2 运行资源初始化

应用入口依次初始化：

1. Docker 沙箱镜像，供 `Bash` 工具隔离执行命令。
2. `FileStateCache`，记录模型已读取文件的内容和版本。
3. `WorkspaceChangeTracker`，监听用户在 Agent 外部修改文件。
4. `MemoryRuntime`，负责会话持久化、上下文虚拟化、检查点和恢复。
5. 核心工具注册表，注册文件、Shell、记忆、MCP、Skill 等工具。
6. `MCPClientManager`，加载 MCP server 配置并进行 discovery。
7. `SkillRuntime`，扫描 Skill、更新索引、启动文件监听和 LRFU 缓存。
8. `LongTermMemoryRuntime`，启动未完成 extraction 的异步回填。
9. `MultiAgentStore`，为 `/multiAgent` 命令提供持久化运行状态。

### 2.3 终端输入准备

交互式终端由 `terminal_ui/application.py` 的 `prompt_toolkit` 应用统一管理：上方是滚动输出区，底部是固定的多行输入区。模型、工具和后台输出只更新上方区域，不会写进正在编辑的输入框。`Esc+Enter` 插入换行，`Ctrl+C` 取消输入或中断当前操作，方向键用于交互选择；非交互环境退化为普通行输入。

### 2.4 General / Code 与项目图谱

General 是安静模式：文件、Skill 缓存和索引变化只在内存中标记图谱 dirty，不初始化静态索引、不创建图谱数据库，也不输出图谱日志。执行 `/mode` 并进入 Code 后，前台等待首次图谱构建完成，再追加并展示一次 bootstrap 摘要。

Code 中的后续文件变化会去抖并异步刷新，刷新过程默认静默。只有普通对话前发现 navigation hash 变化并真正追加新 bootstrap message 时，终端才再次渲染树型摘要。

---

## 3. 用户输入处理流程

### 3.1 命令分流

用户输入先进入 `commands/`：

```text
用户输入
  -> CommandRegistry 匹配命令
  -> 如果是命令：调用对应 handler
  -> 如果不是命令：进入 LLM Runtime
```

内置命令包括：

- `/plan`：进入 Plan 模式；保持固定 system message 和工具 schema，通过 Runtime Context 注入规划要求和工具权限，并在提交计划后显示交互式审批面板。
- `/resume`：恢复历史会话，并加载消息、LRFU 快照、文件状态。
- `/fork`：从历史会话分叉出新会话。
- `/clear`：保存当前会话后开启新会话。
- `/delete`：删除历史会话或过期会话。
- `/multiAgent` / `/multiagent`：显式启动多智能体任务。

命令执行前会保存当前会话，避免切换、恢复、删除时丢失状态。

### 3.2 普通请求进入模型循环

普通用户请求进入统一推理模型循环 `ask_model()`：

1. 确保当前 session 存在。
2. 追加用户消息到会话历史。
3. 保存消息、LRFU 快照和文件状态快照。
4. 触发 Capability Router。
5. 触发长期记忆查询。
6. 构建 Runtime Context。
7. 动态构造本轮 tool schema。
8. 调用模型并处理流式输出。

---

## 4. Runtime Context 组装流程

每轮模型调用前，Runtime 会把多个信息源组装成当前轮上下文：

```text
当前工作区状态
  + Capability Router 推荐
  + 长期记忆查询结果
  + 上下文预算状态
  + 当前用户请求
  -> <RUNTIME_CONTEXT> + <USER_REQUEST>
```

### 4.1 工作区状态

`WorkspaceChangeTracker` 会把模型已读过、但后来被用户外部修改的文件放入当前用户轮次的 Runtime Context，提醒模型重新读取文件。该上下文首次发送后保持不变，后续工具调用只追加消息，以维持模型前缀缓存。Runtime 只通知相关文件变化，不直接替模型决定如何处理。

### 4.2 能力路由结果

Capability Router 统一检索 Skill 与 MCP 能力：

1. Skill Runtime 根据用户请求进行语义检索、关键词检索和 LRFU 排序。
2. MCP Retriever 根据 MCP server 的名称、描述、标签、工具/资源/prompt 元数据召回相关 server。
3. Runtime 将推荐能力以轻量 JSON 注入 Runtime Context。

推荐结果只是提示，不是硬限制。模型仍可通过 MCP discovery tools 主动探索未推荐能力。

### 4.3 长期记忆结果

长期记忆查询模型根据当前 query、最近对话和可用记忆，调用 `SubmitLongTermMemoryQueryResult` 选择相关条目。Runtime 不把选择结果的结构化数组直接暴露给主 Agent，而是拼接成单一字段：

```json
{
  "long_term_memory": {
    "memory": "用户画像：...\n\n用户偏好：...\n\n项目事实：...\n\n可能相关的工作流：..."
  }
}
```

拼接时只保留用户画像、用户偏好、项目事实、可能相关的工作流四段；空段不输出。四段均为空时，`memory` 为 `未查询到相关记忆`。workflow / skill candidate 采用强结构字段 `name`、`description`、`when_to_use`、`when_not_use`、`content`；Runtime 注入时会展开这些字段并保留 `uses_memory_uid=<memory_uid>`，用于统计主 Agent 是否实际使用。

当用户明确提到其他项目或历史 workspace 时，查询模型可调用 `SearchWorkspaceProjectFacts` 读取其他项目的抽象项目事实。

---

## 5. 模型调用与工具执行流程

### 5.1 Tool schema 构造

本轮工具列表是一组**固定**的 schema，不随用户请求动态增减：

```text
核心工具（文件读写、Glob/Grep、Bash、ask_user）
  + MCP 固定 discovery/execution tools
  + Skill 固定入口（search_tool / Get_all_tool / invoke_skill 等）
  + 上下文恢复工具
  -> OpenAI function calling tools
```

Skill **不再**为每个 Skill 注册独立 function schema，而是统一通过 `invoke_skill` 单入口按名称调用；
Capability Router 的推荐结果只作为文本进入 Runtime Context，不改变 tool schema。
这样 Skill 和 MCP server 数量增长都不会让工具列表膨胀，也让整轮的 schema 保持稳定、利于 prompt 缓存命中。

多智能体委托工具不再暴露给主模型。多智能体只能由用户显式输入 `/multiAgent` 触发。

### 5.2 模型流式输出

`stream_one_round()` 负责调用模型 API：

1. 发送 system messages、历史消息、当前 Runtime Context、当前 tool schema。
2. 流式打印 assistant 文本。
3. 聚合 function calling 分片。
4. 返回 assistant 文本、tool_calls 和 token usage。

请求创建和流式迭代整体处于重试保护中：连接失败、超时和 429/5xx 会按指数退避重试
（`MYCODINGAGENT_API_MAX_RETRIES`，默认 3 次；`MYCODINGAGENT_API_RETRY_BASE_DELAY`，默认 1 秒）。
4xx 属于请求本身的问题，不重试。每次重试都会丢弃本次已累积的文本和工具调用分片，
避免拼接出重复正文或半截 JSON 参数。

### 5.3 工具执行

模型返回 tool calls 后，Runtime 逐个执行：

1. 校验工具是否存在。
2. 解析参数。
3. 执行本地工具或 MCP 工具。
4. 将工具结果写成 `role=tool` 消息。
5. 保存完整工具输出到 MemoryRuntime。
6. 对过大的工具输出返回首尾预览和 `context_id`。
7. 再次调用模型，让模型基于工具结果继续推理。

工具调用必须包含短 `intent` 字段。上下文虚拟化后，历史工具输出优先使用 `intent` 作为可读摘要。

工具是否失败以 `ToolResult.is_error` 为唯一依据，并写入 tool metadata 的 `is_error`，
使冷历史在只保留 metadata 后仍能表达调用成败。Runtime 不再根据输出文本里是否出现 `error`
字样猜测失败——否则读取一个含 `error` 字段的正常 JSON 文件会被误判。

### 5.4 API 失败与轮次保护

如果重试耗尽仍然失败：

- 本轮**已经执行过工具**：保留用户消息和全部工具结果，追加一条说明，用户可直接说“继续”接着做。
- 本轮**没有任何进展**：回滚到发起请求前的干净状态。

单轮内部的意外异常由主循环兜底捕获，打印后回到输入提示，不会终止整个 agent 进程。

---

## 6. 工具与安全控制流程

### 6.1 文件工具安全

文件读写工具遵循"先读后改"：

```text
ReadFile
  -> 记录文件内容、mtime、size
WriteFile/EditFile
  -> 检查路径是否在工作区内
  -> 检查目标文件是否已读
  -> 检查文件自读取后是否被外部修改
  -> 保存本回合首次写入前的内容寻址快照
  -> 通过后才写入
```

这样可以避免模型在没有上下文的情况下覆盖用户代码，也能发现用户在 Agent 外部修改了同一文件。

### 6.2 Bash 沙箱

`Bash` 工具在一次性 Docker 容器内执行：

- 工作区挂载到容器 `/workspace`
- 限制 CPU、内存和超时
- 容器执行后自动删除
- 禁止越界访问宿主机路径

沙箱之外还有一层基于 tree-sitter Bash AST 的命令审批（`tool_runtime/command_policy.py`）：

```text
Bash(command)
  -> BashPolicyEvaluator 按命令名和 AST 事件查询三表策略
  -> low：直接执行
  -> approval/unknown：请求用户确认
  -> high：拒绝执行
```

判定标准是“难以撤销”或“影响范围超出工作区”，例如 `rm -rf`、`git push --force`、
`git reset --hard`、`sudo`、`chmod -R`、下载后直接管道执行、写裸设备、指向工作区外的绝对路径操作。
动态命令目标、解析失败和无法静态判断副作用的进程一律 fail-closed。

审批钩子由 `app/main.py` 仅在交互式终端注入；非交互环境（脚本、测试、CI）不拦截，保持既有行为。
核心文件工具 `WriteFile` / `EditFile` 不再弹交互式写入审批，仍保留沙箱路径、先读后改、checkpoint 和文件状态缓存等执行保护。

### 6.3 MCP 权限控制

MCP 工具执行分为 discovery 和 execution：

1. `list_mcp_tools` / `search_mcp_tools` 将本次分页中实际返回给模型的工具名称、描述和参数 schema 记录为已查看。
2. `call_mcp_tool` 首先执行 discovery gate；只知道 Server/工具名称、查看了其他分页或 metadata 已变化都不能通过。
3. 门禁通过后，`call_mcp_tool` 才结合显式配置、实时 annotation 和工具名进行风险分类。
4. CLI 始终保留 MCP Server 启动/连接审批；`read` 工具自动放行，`write`、`destructive`、`network`、`admin`、`unknown` 工具调用执行前请求用户确认。
5. MCP 工具审批支持本次允许和本会话内记住该 Server+Tool+Risk；门禁失败返回 `required_discovery`，不会连接或执行目标工具。

已查看状态在当前 `MCPClientManager` 生命周期内保留；MCP 配置重载、Server discovery 刷新或工具 metadata
指纹变化后失效，模型必须重新查看。`read_mcp_resource` 和 `get_mcp_prompt` 保持各自的只读 discovery/execution 路径。

### 6.4 Rewind 与执行恢复

- 每个用户回合建立工作区 checkpoint；输入精确命令 `/rewind` 后先按 `turn` 选择轮次，再选择恢复 `code`、`conversation` 或 `both`。带其他文本的输入不会触发命令，而会交给模型。
- workspace checkpoint/blob 默认保留 30 天；清理时只删除已过期且不再被任何 checkpoint 引用的 blob。
- 恢复前校验当前文件 hash，外部修改不会被静默覆盖。
- Bash 和远程 MCP 副作用不属于文件 rewind；高自治任务可输入 `/multiAgent`，再在任务提示中使用 `--worktree <task>` 隔离。
- 所有工具执行记录 `running/succeeded/failed/interrupted`，重启时不会自动重放未完成变更。

---

## 7. Skill 路由流程

Skill 系统按"发现 -> 审查 -> 索引 -> 检索 -> 路由 -> 调用 -> 反馈"运行。

### 7.1 Skill 发现

`skill_runtime/discovery.py` 扫描 `skills/` 目录：

1. 查找 `SKILL.md` 或 `.skill.json`。
2. 解析名称、描述、正文、references。
3. 计算内容 hash 和文件元数据。
4. 与 SQLite 中已保存记录对比，找出新增、更新、删除。

### 7.2 安全审查

新增或更新的 Skill 进入两层审查：

1. 代码审查：识别危险代码、系统调用、网络访问、越权模式。
2. Prompt 审查：识别与系统规则冲突、越权或误导模型的描述。

审查通过后才写入 SQLite 并进入索引。

### 7.3 混合检索

Skill 检索融合：

- 可配置 embedding 语义检索（本地 BGE/Ollama/OpenAI-compatible/DashScope 等）
- Milvus 向量索引
- BM25 关键词检索
- RRF 排名融合
- 本地关键词回退

### 7.4 LRFU 反馈

每次 Skill 被调用后更新：

- 用户级 LRFU：跨会话持久化，学习长期偏好。
- 会话级 LRFU：仅当前会话有效，捕捉短期任务上下文。
- Pin / 默认 Skill：作为固定信号参与排序。

最终路由结果以 tool schema 形式暴露给模型。

---

## 8. MCP 能力发现流程

MCP 配置加载顺序：

```text
~/.mycodingagent/mcp.json
  -> 当前工作目录/.mycodingagent/mcp.json
  -> MYCODINGAGENT_MCP_CONFIG
```

后加载的同名 server 覆盖前者。

首次启动会自动生成用户级 `~/.mycodingagent/mcp.json` 和 `~/.mycodingagent/MCP.md`。需要项目级覆盖时，在当前工作目录创建 `.mycodingagent/mcp.json`。完整字段说明和 GitHub token 配置示例见 `docs/mcp.md`。

### 8.1 Discovery

Runtime 对已配置 server 执行：

1. stdio 或 Streamable HTTP 连接。
2. `tools/list`。
3. `resources/list`。
4. `prompts/list`。
5. 写入 SQLite metadata cache，配置指纹变化时失效。

### 8.2 可用性维护

MCP server 暴露 `available` 状态：

- 初始化时视为可用。
- 连接、discovery 或 execution 失败后标记为不可用。
- 用户或模型主动探测成功后恢复可用。
- Runtime 每隔 `MYCODINGAGENT_RECONNECT_MCP_SERVER_STEP` 个用户轮异步重连不可用 server。
- 连接失败进入指数 backoff，调用和启动均有独立超时。
- stdio server 可配置 `sandbox: true` 进入 Docker，工作区读写和网络需显式开放。

### 8.3 代码理解

`code_index` 使用 tree-sitter 为 Python、Go、TypeScript、JavaScript、Rust 和 Java 建立版本化增量索引。索引记录符号、限定调用、import 和语法引用，并提供：

- `overview`：聚合工作区或目录的语言、文件、模块、符号类型和顶层符号，不需要先用 Glob 枚举文件。
- `outline`：读取单个源码文件的符号结构；误传目录时返回可直接执行的 `overview` `suggested_call`。
- `impact`：一次聚合定义、调用方、被调用方、import、引用、相关测试和推荐阅读文件。
- `batch`：在一次索引刷新后执行最多 20 个结构查询。
- 工作区文件事件触发的脏路径刷新；监听事件延迟时使用文件指纹兜底，不重复读取未变化文件。

`lsp` 只在 tree-sitter 定位文件和位置后、任务需要精确定义、引用、类型或诊断时按需启动 language server，
提供 `definition`、`references`、`hover` 和 `diagnostics`。支持的外部可执行程序是
`pyright-langserver`/`pylsp`、`gopls`、`typescript-language-server`、`rust-analyzer` 和 `jdtls`；
未安装或启动失败时返回结构化 `fallback`，本轮相同失败查询不会重复执行。

每轮 Runtime Context 会声明 `/workspace` 路径策略、索引状态、operation guide 和各语言 LSP 可用性。
相同参数的成功 `code_index`/`lsp` 查询以及失败的相同 LSP 查询，在同一用户轮内不会重复执行。

### 8.4 执行接口

固定工具 schema：

- `list_mcp_servers` / `search_mcp_servers`
- `list_mcp_tools` / `search_mcp_tools`
- `list_mcp_resources` / `search_mcp_resources`
- `list_mcp_prompts` / `search_mcp_prompts`
- `call_mcp_tool`
- `read_mcp_resource`
- `get_mcp_prompt`

新增 MCP server 不会增加新的 tool schema，避免工具列表膨胀。

---

## 9. 上下文虚拟化流程

上下文系统的目标是在长任务中保留必要语义，同时避免工具输出无限膨胀。

### 9.1 RAW 模式

会话开始时处于 RAW 模式：

- 用户消息完整保留。
- assistant 文本完整保留。
- 短工具输出完整保留。
- 超过阈值的工具输出保存全文，只向模型返回首尾预览和恢复方式。

### 9.2 热工作区

相关任务连续发生时，Runtime 维护跨多轮 `ContextEpoch`：

```text
用户 query1
  -> 建立热工作阶段
相关 query2/query3
  -> 继续复用同一热工作阶段
工具输出和关键文件内容
  -> 在热区保持 RAW 或预览可恢复
```

当热工作区达到阈值：

- `hot_context_warning_ratio`：注入提示，建议模型主动提交或压缩。
- `hot_context_force_ratio`：Runtime 在安全边界强制提交当前 epoch。

### 9.3 冷历史

ContextEpoch 提交后，旧阶段进入冷历史：

- 用户 query 完整保留。
- assistant answer 完整保留。
- 工具输出替换为 metadata。
- metadata 包含 tool name、intent、context_id、长度、错误状态和恢复方式。

模型需要历史细节时，调用：

- `SearchRecoverableContext`
- `BatchRecoverContext`
- `SearchSessionHistory`
- `GetRecentConversationTurns`
- `RestoreSession`

### 9.4 会话 rollover

当冷区 + 热区接近整体上下文上限时，Runtime 创建会话快照并 rollover 到新 session。新会话首条上下文包含归档摘要，保留恢复入口，避免历史完全丢失。

---

## 10. 长期记忆流程

长期记忆独立于上下文虚拟化，负责跨会话沉淀稳定信息。

### 10.1 记忆抽取时机

```text
会话进行中
  -> 不阻塞主对话调用存储模型
用户 exit / clear / resume / fork
  -> 标记当前 session pending extraction
退出阶段
  -> 在超时窗口内尝试抽取
如果超时或异常中断
  -> 下次启动异步 requeue 未完成 extraction
```

### 10.2 存储模型输入

存储模型看到：

- 完整用户/assistant 消息
- assistant tool_calls 参数
- 每次工具调用的 `intent`
- 工具名和 description
- 工具结果状态、大小、错误标记
- 已有全局记忆
- 已有 workflow staging 记忆
- 当前 workspace 记忆

存储模型看不到原始工具输出，避免把大量代码、日志、临时结果写入长期记忆。

### 10.3 记忆分层

长期记忆分为三层：

1. 全局用户记忆：`user_profile`、`user_preference`、`skill_candidate`
2. Workflow 暂存记忆：`workflow_candidate`
3. 当前 workspace 项目事实：`project_fact`

项目事实只保存抽象架构逻辑，例如项目目的、模块职责、控制流、稳定技术选择和关键设计决策，不保存具体代码片段、行号、diff 或测试日志。

### 10.4 查询与使用

每轮用户请求前，查询模型选择可能有用的长期记忆；Runtime 将结果拼接为 `long_term_memory.memory` 注入 Runtime Context。

如果用户明确提到其他项目，查询模型可调用 `SearchWorkspaceProjectFacts` 读取其他 workspace 的抽象项目事实。

Runtime 会记录 workflow/skill 是否被模型实际使用：

- workflow 被三个不同其他项目查询但未使用：降级为原项目专属。
- workflow 被三个不同其他项目查询并成功使用：升级为全局 `skill_candidate`。
- `skill_candidate` 成功复用达到阈值：询问用户是否沉淀为正式 Skill。

---

## 11. 多智能体流程

多智能体不会自动暴露给主模型，只能由用户显式输入 `/multiAgent` 或 `/multiagent`。

### 11.1 状态机

```text
PLANNING
  -> plan 调用 SubmitPlan
PLAN_REVIEW
  -> plan_review 调用 ApprovePlan / RejectPlan
SCHEDULING
  -> scheduling 调用 DispatchTasks 批量派发任务
TASK EXECUTION
  -> execute 执行任务并 SubmitTaskExecution
  -> task_test 验证并 ApproveTaskTest / ReportTaskFailure
FINAL_TESTING
  -> final_test 全局验证
COMPLETED / FAILED
```

### 11.2 子智能体职责

- `plan`：读取任务和最近主对话，提交结构化计划。
- `plan_review`：审查计划是否完整、顺序合理、可测试。
- `scheduling`：批量派发任务，接收执行结果，决定修复或进入最终测试。
- `execute`：只依据 assigned task 执行代码修改。
- `test`：验证对应 execute task。
- `final_test`：对完整任务做最终验证。

### 11.3 并发与文件协调

`scheduling` 使用 `DispatchTasks` 批量派发任务。Runtime 根据 `MYCODINGAGENT_MULTI_AGENT_MAX_PARALLEL_TASKS` 并行推进，默认 5。

文件协调由 `mycodingagent/multi_agent/file_coordination.py` 管理：

- 文件级写锁
- 文件 revision 校验
- stale file 拒绝
- Bash `declared_write_files` 监督
- 未声明写入回滚
- Runtime Context 中的 `workspace_changes`
- 等待通知队列

`execute` 工具调用必须携带正确 `task_id`。Bash 在 execute 中必须声明潜在写入文件，Runtime 会在命令前后做快照，拒绝未声明源文件变更。

### 11.4 反重复读取策略

大型单文件拆分、模块抽取、迁移任务要求优先：

```text
一次性定位边界
  -> 批量生成变更
  -> 批量验证
```

避免每个叶子任务反复 `ReadFile` / `Grep` 同一个大文件导致上下文膨胀。

---

## 12. 目录结构

```text
mycodingagent/
├── app/                    # 应用启动、依赖组装、资源生命周期
├── capability_discovery/   # Skill/MCP 能力推荐
├── code_intelligence/      # 六语言符号索引与 LSP 进程
├── commands/               # CLI 命令
├── configuration/          # 配置
├── llm_runtime/            # 模型调用和工具循环
├── long_term_memory/       # 长期记忆存储、查询和生命周期
├── mcp_integration/        # MCP 连接、发现、执行和审批
├── memory/                 # 会话、上下文虚拟化、检查点、恢复
├── relevance/              # LRFU 等排序算法
├── skill_runtime/          # Skill 发现、索引、路由和反馈
├── terminal_ui/            # 终端输入和会话选择
├── tool_runtime/           # 工具实现和注册表
└── workspace/              # 工作区身份和文件缓存

mycodingagent/multi_agent/   # 多智能体编排、上下文、工具权限和文件协调
skills/                     # Skill 插件资产
tests/                      # 单元、集成和评测测试
```

---

## 13. 验证

常用测试命令：

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_long_term_memory.py tests/test_memory_runtime.py tests/test_multi_agent.py
```

主循环、API 重试和命令审批：

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_llm_runtime_client.py tests/test_command_policy.py
```
