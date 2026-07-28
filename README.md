# myCodingAgent

## 项目定位

myCodingAgent 是一个基于大语言模型（LLM）的命令行编码智能体。它在隔离的 Docker 沙箱中运行，能够理解用户的中文自然语言编程需求，自动调用文件读写、搜索、Shell 命令等工具完成编码任务。项目以"先读后改、按需调用、安全可控"为设计原则，既提供基础编码工具，也通过开放式的 Skill 系统支持开发者定义领域专家工作流，覆盖从代码开发、审查、面试到内容创作、视频生成等多种场景。

## 项目框架

核心运行时代码统一位于 `mycodingagent/`，根目录 `__main__.py` 仅负责调用应用入口。目录按职责命名，跨模块通过 Protocol 和组合根注入依赖：

- `mycodingagent/app/`：应用启动、依赖组装、资源生命周期和交互主循环。
- `mycodingagent/configuration/`：环境变量和应用配置。
- `mycodingagent/llm_runtime/`：模型请求、流式响应、工具循环、Prompt 上下文和 Token 统计。
- `mycodingagent/terminal_ui/`：终端输入、raw TTY 行编辑、多行粘贴、历史展示、会话选择与确认。
- `mycodingagent/commands/`：命令注册和 `/resume`、`/fork`、`/clear`、`/delete` 处理器。
- `mycodingagent/workspace/`：工作区身份和文件缓存。
- `mycodingagent/tool_runtime/`：工具契约、注册表及文件、Shell、记忆、MCP、Skill 工具适配器。
- `mycodingagent/memory/`：会话、上下文预算、虚拟化、检查点和 SQLite 持久化。
- `mycodingagent/capability_discovery/`：基于抽象 Skill/MCP 能力源的统一推荐。
- `mycodingagent/mcp_integration/`：MCP 配置、连接、发现、执行和审批。
- `mycodingagent/skill_runtime/`：Skill 发现、索引、检索、路由和缓存；`skills/` 仅保存插件资产。
- `multiAgent/`：多智能体编排模块，提供主智能体委托、调度执行、子智能体上下文、工具权限隔离、任务门控、文件协调和运行持久化。

---

## Capability Router 与 MCP Discovery

Capability Router 是模型调用前的统一能力发现入口。它不替代 Skill Router，而是把现有 Skill Runtime 作为一个检索子模块，同时接入 MCP Server Retriever，最终生成轻量的能力推荐并写入当前轮 Runtime Context。推荐结果不是限制：即使某个 MCP Server 没被推荐，模型仍可通过 `list_servers` 和 `search_servers` 主动探索。

MCP Client 与 Capability Router 解耦。`mycodingagent/mcp_integration/` 负责 MCP 协议侧的配置加载、连接管理、metadata discovery 和真实协议调用；`mycodingagent/capability_discovery/` 只负责能力检索、排序、合并和 Runtime Context payload。当前实现支持真实 MCP Server 配置读取、真实 stdio 连接、`tools/list`、`resources/list`、`prompts/list`、metadata cache、`tools/call`、`resources/read` 和 `prompts/get`。

MCP 配置采用多层 JSON：

```json
{
  "servers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "..."},
      "description": "GitHub repository and issue operations",
      "tags": ["git", "github", "repo"],
      "aliases": ["gh"],
      "abbreviations": ["gh"],
      "synonyms": ["repository", "pull request", "issue"],
      "keywords": ["github", "代码仓库", "PR", "issue"]
    }
  }
}
```

配置加载顺序是用户级 `~/.config/myCodingAgent/mcp.json`、项目级 `.mycodingagent/mcp.json`、环境变量 `MYCODINGAGENT_MCP_CONFIG` 指向的文件；后加载的同名 server 覆盖前者。Discovery Tool schema 固定为 `list_servers`、`search_servers`、`list_tools`、`search_tools`、`list_resources`、`search_resources`、`list_prompts`、`search_prompts`，并统一使用 `offset` + `limit` 分页；新增 MCP Server 不会增加新的工具 schema。

`list_servers` 返回的是 server 可用性状态 `available`，不再向模型暴露易误导的 `connected` 字段。初始化时所有已配置 server 都视为可用；当连接、discovery 或执行失败时，runtime 将该 server 标记为 `available=false` 并记录 `error`。模型仍可通过 `list_tools`、`list_resources` 或 `list_prompts` 主动探测不可用 server：探测成功会立即把 `available` 恢复为 `true`，探测失败则保持不可用且不影响后台重连。runtime 每完成 `RECONNECT_MCP_SERVER_STEP` 个用户轮后会异步重连不可用 server，默认值为 `10`，也可用 `MYCODINGAGENT_RECONNECT_MCP_SERVER_STEP` 覆盖。

第二阶段执行接口固定为 `call_tool`、`read_resource`、`get_prompt`。`read_resource` 与 `get_prompt` 按只读能力直接开放；`call_tool` 会先按工具名和配置分类，`search/get/list/read/fetch/query/inspect` 等只读风险默认放行，`create/update/push/merge/delete` 等写入、危险或未知风险才经过 approval hook 请求用户确认，用户拒绝时返回 `用户拒绝你的工具调用`。所有工具 schema 都会暴露短 `intent` 字段，模型每次工具调用都应填写该字段；当上下文切换到虚拟化模式时，历史工具输出 metadata 优先使用该 intent，而不是把完整调用参数拼进摘要。

当模型缺少用户账号、用户名、仓库范围等无法从工具可靠确定的信息时，可以调用 `ask_user` 询问终端用户。`ask_user` 参数为 `query`、可选 `choice` 和 `intent`：`choice` 为空时只展示问题；`choice` 非空时展示 `query` 加换行后的选项文本，并把用户输入原样作为工具结果返回模型。

当前实现已用 GitHub MCP server 做过真实 stdio discovery 验证：在临时配置中通过 `npx -y @modelcontextprotocol/server-github` 启动 server，可成功返回 26 个 GitHub tool summary。由于本地环境没有 `GITHUB_PERSONAL_ACCESS_TOKEN` / `GITHUB_TOKEN` / `GH_TOKEN`，该验证只覆盖 discovery，不覆盖真实 GitHub API 写入调用；真实 MCP execution 路径由测试中的 FastMCP stdio server 覆盖。

---

## 多智能体模块设计

多智能体模块用于处理非局部工程任务。主智能体直接回答或修改的前提是任务范围清晰、局部、低风险，并且不跨模块、状态、接口、数据、安全、运行时或构建边界。只要任务需要先规划再执行、涉及多个相关部分、改变或重组项目结构、要求保持行为兼容、需要测试/审查循环、影响范围不清楚，主智能体必须在代码修改前调用 `DelegateToMultiAgent`。

### 主智能体入口

`DelegateToMultiAgent` 是主智能体可见的委托工具，参数只有 `task` 和 `reason`。`task` 描述要交给多智能体的工程任务；`reason` 是一句审计原因，说明为什么该任务满足委托条件。工具返回精简结果：`status`、`run_id`、`plan_summary`、`test_result`、`scheduling_result`、`scheduled_tasks` 和 `inspect_tool=InspectSubAgentWork`。主智能体默认只看到这些最终结果，不把所有子智能体工具调用直接塞回主上下文，避免污染主智能体窗口。

`InspectSubAgentWork` 是主智能体按需查看子智能体完整工作的只读工具，参数包括 `run_id`、`agent`、可选 `step_id`、`offset` 和 `limit`。它读取持久化的子智能体消息，分页返回 inspection 内容；`has_more_inspection_content` 只表示检查结果还有下一页，不表示模型上下文被截断。

### 工作流

多智能体按照固定状态机运行：

```text
PLANNING
  -> plan 调用 SubmitPlan 提交结构化计划
PLAN_REVIEW
  -> plan_review 调用 ApprovePlan 或 RejectPlan
SCHEDULING
  -> scheduling 调用 DispatchTask / CheckTask / CompleteScheduling
TASK EXECUTION
  -> 每个任务由 execute 调用 SubmitTaskExecution，再由 task_test 调用 ApproveTaskTest 或 ReportTaskFailure
FINAL_TESTING
  -> final_test 调用 ApproveFinalTest 或 ReportFinalTestFailure
COMPLETED / FAILED
```

`RejectPlan`、`ReportTaskFailure` 和 `ReportFinalTestFailure` 不只是改变状态，还会写入 `feedback_events`。当目标子智能体下一次恢复运行时，Runtime 会把这些拒绝/失败反馈模拟为上一轮工具调用结果插入其上下文，实现续接式修正，而不是丢弃上一次子智能体上下文重跑。

`scheduling` 不直接修改代码，而是通过 `DispatchTask` 创建一个或多个可执行任务。每个任务绑定一个 `execute` 和一个 `task_test` 上下文；Runtime 根据 `MYCODINGAGENT_MULTI_AGENT_MAX_PARALLEL_TASKS` 控制同时运行的任务数，默认最多 5 个。`DispatchTask` 可声明 `depends_on`，依赖未通过时任务保持 queued；依赖满足且并发槽位可用时 Runtime 将其推进到 running。`CheckTask` 返回任务三态/多态进度（queued、running、passed、failed/needs_fix），所有任务 passed 后才允许 `CompleteScheduling` 进入 `final_test`。

### 子智能体职责与工具权限

每个子智能体有独立系统提示词，位于 `multiAgent/prompts/{role}/SYSTEM.md`：

| 子智能体 | 职责 | 工具权限 |
|---|---|---|
| `plan` | 理解任务和近期主对话，调用 `SubmitPlan` 提交结构化计划 | 只读工具 + `SubmitPlan` |
| `plan_review` | 审查计划的覆盖、顺序、安全性和可测试性 | 只读工具 + `ApprovePlan` / `RejectPlan` |
| `scheduling` | 拆分和调度任务，检查 queued/running/passed/failed 状态 | 只读工具 + `DispatchTask` / `CheckTask` / `CompleteScheduling` |
| `execute` | 只依据 assigned task 执行当前任务 | 读写工具 + Bash + `SubmitTaskExecution` |
| `test` | 验证对应 execute task | 只读工具 + Bash + `ApproveTaskTest` / `ReportTaskFailure` |
| `final_test` | 对完整任务做最终验证 | 只读工具 + Bash + `ApproveFinalTest` / `ReportFinalTestFailure` |

`execute` 子智能体有额外任务门控：所有普通工具调用都会被 schema 注入 `task_id`，且必须等于当前任务上下文中的 `task_id`。如果 task_id 缺失或不匹配，Runtime 拒绝该工具调用。Bash 在 execute 中还必须声明 `declared_write_files`，Runtime 会用文件级写锁、版本校验、等待通知队列和未声明写入回滚来防止并发覆盖。

文件协调由 `multiAgent/file_coordination.py` 负责。`ReadFile` 会记录 task 对文件的读取 revision；`WriteFile` / `EditFile` 写入前必须持有文件级写锁，并且读到的 revision 必须仍是当前 revision，否则返回 `stale_file` 要求重读。Bash 写入必须通过 `declared_write_files` 声明潜在修改文件；Runtime 在命令前后做工作区快照，只允许声明文件发生变化，未声明源文件变更会被回滚并返回 `undeclared_bash_write`。当文件被其他 task 修改或锁释放时，Runtime 把通知写入目标 task 的 `runtime_file_notices`，由 execute 按"读取变化 -> 避免覆盖 -> 修改 -> 复查文件"策略自行处理。

### 上下文与输出控制

子智能体上下文由 `multiAgent/context.py` 生成。`plan` 能看到任务和最近主对话文本，保证"上一轮让制定计划、下一轮让执行计划"这类场景不会丢失关键要求；`execute` 不直接使用用户原始请求，它只接收 assigned task、approved_plan、runtime file notice、测试反馈和轮次预算，防止重新解释需求。`test` 只看对应 task 与 execute 提交，`final_test` 只看 approved_plan、任务提交摘要和必要结果。

子智能体普通工具输出沿用主运行时的大输出策略：输出全文先保存到 MemoryRuntime，短输出直接返回，超过 `raw_tool_output_preview_chars` 的输出返回首尾预览和 `context_id` 恢复方式。没有 MemoryRuntime 时退化为 500 字符头部 + 500 字符尾部预览。多智能体 run 自身保存在 `multi_agent.sqlite3` 的 `multi_agent_runs` 表中，字段 `payload` 包含计划、状态、步骤提交、子智能体消息、最终回答、反馈事件、轮次统计和错误信息。

### 反重复读取策略

多智能体提示词和审查规则明确约束大型单文件拆分、迁移、模块抽取类任务：应优先"读一次、批量生成、批量验证"，避免每个叶子步骤反复 `ReadFile` / `Grep` 同一个大文件。`plan` 提示词要求这类任务合并为更可靠的批处理步骤；`plan_review` 会拒绝按模块逐步重复读取大文件的计划；`execute` 提示词要求在大文件抽取/重构中优先使用 Bash/Python 批处理脚本并输出精简验证证据。

---

## Skill 管理模块设计

Skill 系统是 myCodingAgent 区别于普通编码助手的核心扩展机制。它将领域专家能力封装为可发现、可检索、可调用的"技能插件"，让模型在对话中按需动态获取并执行领域专家工作流——涵盖前端设计、代码审查、后端面试、产品管理、短视频创作、数字人带货、PPT 生成、合同审查、语音识别等数十种专业场景。整个系统围绕 Skill 的完整生命周期设计：发现 → 同步 → 索引 → 检索 → 路由 → 暴露 → 调用 → 反馈。

### 整体架构

Skill 运行时（`SkillRuntime`）是整个系统的中枢调度器。它在初始化阶段完成三件事：从 SQLite 加载已持久化的 Skill 记录和引用索引；向核心工具注册表注入五个 Skill 管理工具（`search_tool`、`Get_all_tool`、`Get_tool_by_name`、`search_skill_references`、`Get_skill_reference`），使模型能够主动检索和获取 Skill；启动多目录文件系统监听器，实时追踪 Skill 源文件的新增、修改和删除。

运行时的核心职责是桥接"模型的能力需求"和"本地 Skill 资源池"之间的语义鸿沟——当模型在对话中需要某个领域能力时，运行时的路由系统从 Skill 池中选出最匹配的 Top-N Skill，以函数调用 schema 的形式暴露给模型，模型即可直接调用这些 Skill 获取专家工作流指导。

### Skill 发现

发现模块（`discovery.py`）负责从文件系统中提取 Skill 的定义和元数据。它递归扫描配置的一个或多个 Skill 根目录，在每级子目录中查找 `SKILL.md` 文件（Markdown 格式的 Skill 定义）或 `.skill.json` 文件（JSON 格式的元数据描述）。每个 Skill 目录同时支持 `references/` 子目录，用于存放该 Skill 所需的参考文档、模板文件或领域知识库。

从 `SKILL.md` 中，发现模块解析出 Skill 的名称（取 Markdown 的一级标题）、描述（第一段引导文字）和完整指令正文；工具名称则通过将目录名转换为 `skill_` 前缀的蛇形命名自动生成。每个 Skill 和其 `references/` 下的每个参考文件各自生成一个 `SkillRecord` 或 `ReferenceRecord`，携带路径、内容哈希、修改时间等元数据，为后续的增量同步提供比对依据。

### 同步与双重审查

同步流程（`sync` 方法）将文件系统的最新状态与 SQLite 中已持久化的记录进行三方比对：

- **新增**：文件系统中存在但数据库中没有对应哈希的记录；
- **更新**：文件系统中存在且哈希与数据库记录不同的记录；
- **删除**：数据库中存在但文件系统中已不存在的记录。

关键设计在于：新增或更新的 Skill 并不会直接入库，而是必须通过两道审查关卡：

1. **代码审查**（`review_skill_code`）：扫描 Skill 定义全文，检测是否存在潜在的恶意代码注入模式——包括但不限于导入系统模块、执行 Shell 命令、文件系统遍历、网络连接等高风险操作。这确保了第三方 Skill 不会突破沙箱的安全边界。

2. **提示词审查**（`review_skill_prompt`）：评估 Skill 指令的质量和合规性，检查是否存在越权指令、与系统提示词冲突的行为准则、或可能导致模型行为异常的表述。

只有两道审查均通过的 Skill 才会被写入 SQLite 存储并被同步到向量索引。审查失败的 Skill 会被记录失败原因并跳过。对于 `references/` 下的参考文件，同样需要经过安全审查，但审查标准相对宽松，主要检查是否包含可执行代码或越权指令。

### 向量嵌入与混合检索

为了让模型能够通过自然语言描述找到匹配的 Skill，系统需要将 Skill 的语义信息编码为向量并支持高效检索。

**嵌入生成**：使用 BGE-M3 模型将 Skill 的名称和描述拼接后生成 1024 维文本嵌入向量。BGE-M3 支持多语言且对中文语义理解优秀，能够很好地捕捉"前端页面设计""代码审查""数字人带货"等中文能力描述的语义。

**向量存储**：嵌入向量存入 Milvus 向量数据库，Milvus 配置为 IVF_FLAT 索引以在召回率和查询延迟之间取得平衡。同一 Skill 的多个描述变体（如不同语言版本）会生成多个向量记录但关联到同一个 Skill ID。

**混合检索**：检索采用 RRF（Reciprocal Rank Fusion）融合两路信号——一路是 BGE-M3 的密集向量语义检索（捕捉语义相似性），另一路是 Milvus 内置的 BM25 关键词检索（捕捉精确词汇匹配）。RRF 通过倒数排名加权公式融合两路排序结果，确保既不会被纯关键词匹配主导，也不会因语义联想过度泛化。

**回退机制**：当 Milvus 服务不可用或向量检索失败时，系统自动降级为本地关键词匹配模式——将查询词与 Skill 名称和描述做字符串包含匹配，按匹配度排序，保证即使在基础设施故障时，Skill 检索的基本功能依然可用。

### 多源融合路由

路由模块（`router.py`）是决定"本轮对话向模型暴露哪些 Skill"的决策核心。它不是简单地取向量检索 Top-N，而是融合四个独立信号源，通过加权打分产生最终排序：

**信号源一：向量检索得分**

来自 Milvus 混合检索的语义相关性得分，经过 RRF 归一化。这个信号反映"Skill 能力和用户当前需求的语义匹配度"。路由配置中，该信号设有最低占比保障——无论其他信号如何变化，最终 Top-N 中必须保留一定比例的纯向量检索结果，确保新加入的 Skill 或冷门 Skill 不会因缺乏历史反馈而被完全淹没。

**信号源二：用户级 LRFU 缓存**

LRFU（Least Recently / Frequently Used）是一种融合了 LRU（最近最少使用）和 LFU（最不经常使用）双重淘汰策略的缓存算法。每个 Skill 在用户级别维护两个统计量：最近调用时间戳（recency）和累计调用次数（frequency）。打分公式将两者加权组合，recency 权重通过可配置的半衰期参数控制衰减曲线——半衰期越短，越早的调用的权重下降越快；frequency 通过对数压缩避免马太效应，防止少量高频 Skill 永久垄断排序。

用户级 LRFU 是跨会话持久化的，存储在 SQLite 中。这意味着用户在不同时间、不同项目中使用同一 Skill 的偏好会累积学习，形成长期的"用户画像"。

**信号源三：会话级 LRFU 缓存**

与用户级 LRFU 采用相同的算法结构，但统计范围限定在当前会话内，且不跨会话持久化。会话级缓存捕捉的是"当前任务的短期需求模式"——例如在同一个项目中连续多次调用前端设计 Skill，会话级 LRFU 会快速提升该 Skill 的权重，使其在后续轮次中更容易被选中。会话级和用户级 LRFU 的半衰期参数独立配置，会话级的半衰期通常更短，以适应任务切换的快速变化。

**信号源四：固定信号**

包括两类固定信号：默认 Skill（`default_skills`，始终以固定权重参与排序）和手动 Pin 的 Skill（用户通过 `/pin` 命令锁定的 Skill，权重极高）。固定信号确保关键 Skill 始终可被模型访问，不受检索或缓存波动的影响。

**融合与截断**：四个信号源的得分分别归一化后按配置权重线性加权。加权总分排序后取 Top-N（N 可配置），同时强制保证向量检索结果的最低占比。融合后的 Skill 列表以 OpenAI function calling schema 的形式注入当轮对话的工具定义中，模型即可直接调用。

### 调用与反馈闭环

当模型调用了一个 Skill 工具后，运行时的 `record_skill_invocation` 方法被触发，同时更新用户级和会话级 LRFU 缓存（递增频率、刷新时间戳），并检查是否需要自动 Pin（高频调用的 Skill 自动晋升为 Pin 状态）。这个反馈闭环使得 Skill 路由随使用逐渐"学习"用户的偏好，越常用的 Skill 越容易被选中，形成正向增强。

---

## 上下文虚拟化管理系统设计

上下文虚拟化管理是 myCodingAgent 在长对话场景下保持高效运作的底层保障。系统不按单个用户轮次立即清空工作记忆，而是维护一个可跨多轮延续的热工作上下文阶段；阶段之前的冷历史使用 metadata 和恢复指针虚拟化，阶段内部的代码、工具结果和对话保持 RAW，以提高连续任务的 Prompt 前缀缓存命中率。

### 整体架构与运转流程

```
每轮对话开始
  │
  ├─ 1. PromptBudgetManager 计算 token 预算，判断当前所处压力阶段
  │
  ├─ 2. ContextEpochManager 定位当前跨多轮热工作阶段
  │      ├─ 阶段之前的冷历史 → 工具输出 metadata 虚拟化
  │      └─ 阶段内部的连续任务 → 保持 RAW
  │
  ├─ 3. 工具输出先持久化；RAW 下超 1000 字符时只给首尾预览
  │
  ├─ 4. 热工作阶段达到 30% 时提示提交，达到 40% 时安排强制提交
  │      └─ CommitWorkingContext 只登记 hot-to-cold pending，在完整回合结束后生效，不要求模型生成任务摘要
  │
  ├─ 5. RAW 窗口达到 60% 时进入渐进式虚拟化
  │      └─ cold 区保留用户/模型文本，工具输出降为恢复元数据
  │
  └─ 6. cold 区过长时归档旧会话，新会话以 archive tool 结果继续
```

### 跨多轮热工作上下文（`context_epoch.py`）

`ContextEpochManager` 将会话拆成连续的工作阶段。活动阶段通过 `start_message_index` 标记起点；模型在 query1 中读取的文件和工具结果，在相关的 query2、query3 中仍以 RAW 消息保留，不需要立即重新读取或恢复。只有阶段被提交后，该阶段才进入冷历史虚拟化。

提交采用模型与 Runtime 混合控制：

- 模型在任务完成、用户明确切换工作、连续新请求已形成新任务或收到热区提示时调用 `CommitWorkingContext`；该工具只需要轮转原因和可选短备注，不负责生成 checkpoint/rollover 摘要。
- 热区达到模型窗口 30% 时，仅注入提示，不自动提交。
- 热区达到 40% 时，Runtime 创建强制 pending 提交，并保留最近若干轮作为新热区。
- pending 提交不会在 assistant/tool 调用链中途改变消息结构，而是在 `on_turn_completed` 确认当前回合完整后生效。
- 提交后创建新的活动阶段，旧阶段工具输出转为 metadata；需要原文时仍可通过 `BatchRecoverContext` 恢复。

阶段状态持久化在 `context_epochs` 表中。旧数据库首次恢复会话时，以最后一个完整用户轮次作为活动阶段，避免突然把整个长会话重新放回 RAW 上下文。

### 提示词预算管理（`budget.py`）

`PromptBudgetManager` 是整个虚拟化链路的"触发器"。它不直接修改消息内容，而是通过精确计算窗口利用率，告知下游模块"现在应该采取什么级别的压缩动作"。

**计算模型**：每轮对话前，管理器估算当前消息列表、工具定义 schema 和系统提示词的合计 token 数。然后从模型上下文窗口总容量中扣除三项固定预留配额——推理预留（确保模型有足够空间生成回复）、输出预留（确保流式输出不被截断）和工具调用预留（确保模型能发出 function call）——得到"消息可用 token 上限"。当前消息 token 数除以该上限，得到窗口利用率。

**四阶段分级**：根据利用率与三个可配置阈值（soft_ratio、working_ratio、emergency_ratio）的比较，将当前状态划分为四个阶段：

| 阶段 | 触发条件 | 系统行为 |
|------|---------|---------|
| NORMAL | 利用率 < soft_ratio | 无干预，消息完整保留 |
| SOFT | 利用率 ≥ soft_ratio | 开始关注，压缩器进入轻度截断模式 |
| WORKING | 利用率 ≥ working_ratio | 中度压力，指针化可重复工具输出，候选检查点 |
| EMERGENCY | 利用率 ≥ emergency_ratio | 重度压力，强制检查点，可能触发会话翻转 |

每个阶段的值域边界是连续且无重叠的，确保状态之间不会反复横跳。预算管理器还对外暴露 `stage` 属性供 `MemoryRuntime` 在每轮结束后做检查点决策。

### 分级上下文压缩（`compressor.py`）

`ContextCompressor` 负责单条大输出和紧急场景下的压缩能力；会话级冷/热边界由 `ContextEpochManager` 决定。当前实现不会仅因为用户进入下一轮就立即移除上一轮工具输出。

**单条输出处理**：工具执行后，输出全文始终先写入可恢复存储。RAW/热区渲染下，小于 `raw_tool_output_preview_chars` 的输出保持内联；超过阈值时，发送给模型的是前半段 + 省略占位符 + 后半段，并附带 `context_id` 与单一路径恢复方式。默认阈值为 1000 字符，首尾各 500 字符。

引用块包含以下字段：

- `context_id`：全局唯一标识符，用于后续恢复
- `tool_name`：工具名称
- `content_length` / `omitted_chars`：原始输出和省略片段的体积统计
- `preview`：首尾预览文本
- `recover`：恢复指引文本，要求模型通过 `BatchRecoverContext` 和精确 `context_id` 按偏移量分段读取原文

引用对象同时记录 `reproducible`，但无论是否可重复执行，已持久化的原始输出都可以通过精确 `context_id` 分段恢复。

**预算压力处理**：热工作阶段达到 30% 时提醒模型提交，达到 40% 时 Runtime 安排阶段提交；RAW 整体 Prompt 达到 `raw_to_virtualized_ratio`（默认 60%）时进入渐进式虚拟化；虚拟化后 cold 区达到 `archive_cold_context_ratio`（默认 50%）时才进入归档流程。阶段提交和会话翻转都只在安全生命周期边界生效。

这套设计的核心洞察在于区分工具输出的"可复现性"：读文件、搜索文件这类操作是确定性的，重新执行总能得到相同结果，因此只需要存一个指针；而 Shell 命令的输出可能包含时效性信息或副作用，不能简单地用指针替代。

### 可恢复上下文对象与指针化机制（`context_objects.py` + `working_context.py`）

压缩器产生的指针引用并非凭空存在，它们指向的是 `RecoverableContextObject`——一个将工具输出全文与结构化元数据绑定在一起的持久化对象。

**对象结构**：每个可恢复上下文对象包含原始输出全文、内容类型（TEXT / JSON / ERROR）、token 数、关键词列表、关联文件路径、可重复性标记、时间戳和所属会话 ID。对象在创建时自动从输出内容中提取关键词和文件路径引用，为后续的搜索恢复提供索引。

**生命周期状态机**：对象在其生命周期中经历四个状态：

```
WORKING → EXTERNAL → ARCHIVED → DELETED
```

- **WORKING**：当前轮刚创建，尚未进入持久化索引
- **EXTERNAL**：已持久化到 SQLite，可通过 `BatchRecoverContext` 恢复，占用存储空间
- **ARCHIVED**：已归档，元数据仍可搜索但原文可能已被清理
- **DELETED**：已彻底删除

`WorkingContext` 管理当前轮的活跃对象池，支持添加、逐出、归档和清空操作。当对象从 WORKING 迁移到 EXTERNAL 时，同时写入 `recoverable_contexts` 表（存储完整对象）和 `session_tool_outputs` 表（存储原始输出）。

**恢复接口**：模型通过 `BatchRecoverContext(items=[{context_id, offset, limit}])` 工具按需获取被指针化的输出内容。恢复时无需加载全文，可以通过 offset 和 limit 参数分段读取，进一步节省上下文。系统保留 `SearchRecoverableContext` 用于在没有精确 `context_id` 时按关键词搜索可恢复对象。恢复工具只用于当前工作上下文中不可见的历史/虚拟化证据；如果工具结果或事实已经在当前对话中可见，模型应直接基于可见内容回答，不能再调用恢复工具。`context_id` 必须来自可见的恢复引用或搜索结果，禁止根据工具名、参数、offset 或记忆猜测 ID。

### 增量检查点与会话快照（`checkpoint.py`）

`CheckpointManager` 负责在上下文压力累积到阈值时创建对话的结构化快照，为可能的会话翻转做准备。

**快照结构**：`ConversationSnapshot` 是一份高度结构化的对话状态摘要，包含以下字段：

- **总体摘要**：对整个对话任务目标的浓缩描述
- **推理结论列表**：从助手回复中提取的关键结论和发现
- **用户意图列表**：从用户消息中提取的意图描述
- **重要决策列表**：识别包含"采用""选择""决定""确认"等关键词的决策行
- **未完成任务**：待继续的工作项
- **可恢复上下文引用**：关联的 `RecoverableContextObject` ID 列表
- **项目状态**：工作区信息、当前分支、活跃文件等
- **运行时状态**：当前预算阶段、LRFU 缓存快照等

**增量生成**：快照采用增量生成策略。首次快照生成全量内容；后续快照以 `SnapshotDelta` 形式只包含自上次快照以来的新增内容——新的结论、新的意图、新的决策等。`merge_snapshot` 方法将增量与前一个快照合并，避免每次重建整个快照，在大规模对话中显著节省生成成本。

**触发条件**：检查点的触发采用双阈值策略——当预算阶段进入 WORKING 且距上次检查点超过最小轮次间隔时，生成候选检查点（软检查点）；当预算阶段进入 EMERGENCY 时，强制生成检查点（硬检查点）。软检查点可以被跳过（如果快照内容与上次相比变化不大），硬检查点必须执行。

### 会话翻转

会话翻转是检查点系统的终极动作，也是上下文虚拟化管理的"最后手段"。它只在进入虚拟化后 cold 区超过归档阈值时触发，RAW 初始阶段不会直接归档。

翻转流程如下：基于最新快照的摘要和未完成任务创建新会话；将旧会话的所有消息标记为历史并归档；在新会话开头注入 `ArchiveConversationSnapshot` 的 assistant tool call 与 tool result，完整提供快照摘要、未完成任务列表和关键上下文引用；旧会话保存为 `HistoricalSessionRef`，可通过 `/resume` 命令恢复完整历史。

从模型视角看，翻转后的新对话窗口干净且充足，但开头有一组 archive 工具消息告诉它"之前我们在做什么、做了哪些决策、还有哪些事没做完"，使得任务连续性得以跨越会话边界保持。

### 活动工作阶段与冷历史的分层处理策略

上下文虚拟化不再以单个用户轮次作为冷热边界，而是以 `ContextEpochState.start_message_index` 划分活动工作阶段和冷历史。一个活动阶段可以包含多个连续用户请求及其全部工具调用。

#### 活动工作阶段的处理策略

活动阶段内的工具输出经历一条"先存储、保持可见、必要时摘要"的处理链路：

**第一步：输出封装与存储**。每次工具调用完成后，输出立即通过 `save_tool_output` 被封装为 `RecoverableContextObject`（生命周期状态为 WORKING），同时生成 `ToolOutputRecord` 将完整输出文本存入 `session_tool_outputs` 表。存储层仍保留 `output_id` 字段，但模型可见引用统一呈现为 `context_id`，为后续的指针化和恢复建立桥梁。

**第二步：单条输出与阶段预算的实时干预**。`tool_output_prompt_content` 按 RAW 规则保留短输出或生成首尾预览；`ContextEpochManager` 独立计算活动阶段 token，达到 30% 时提示提交，达到 40% 时登记 Runtime 强制提交。

**第三步：模型的主动摘要能力**。模型可以通过 `SummarizeCurrentTurnMessage` 工具主动将当前轮中某条过大的工具输出替换为紧凑摘要。摘要存储在 `_current_turn_summaries` 字典中，由 `apply_current_summaries` 在渲染时注入。这一机制让模型拥有了"自主管理上下文预算"的能力——当它发现某条输出虽然有用但细节不必全部保留时，可以主动压缩它，为后续推理腾出空间。

**关键特征**：当前轮的工具输出即使被预览化，明确的 `context_id` 仍然出现在上下文窗口中，模型可以调用 `BatchRecoverContext` 恢复所需部分，无需额外搜索。若原始工具输出或足够回答的预览已经可见，则模型不应调用恢复工具。

#### 冷历史的处理策略

只有活动阶段提交后，该阶段才进入冷历史。用户发送下一条相关请求本身不会触发历史化。

**结构化解析**：`build_historical_turns` 函数遍历完整消息列表，将扁平的 `role: user/assistant/tool` 消息序列解析为结构化的 `HistoricalTurn` 对象。每个对象包含三个核心字段：

- `user_content`：用户 query 的完整原文，不做任何截断或摘要
- `assistant_content`：模型文本回复的完整原文，不做任何截断
- `tool_metadata`：`ToolInvocationMetadata` 列表——原始记录仍保存完整结构，但冷区渲染只暴露工具名、显式 `intent` 或启发式 `call_summary`、`context_id`、长度统计、错误状态和恢复方式，**不包含任何原始输出文本**

**彻底虚拟化渲染**：当 `render_virtualized_messages` 函数将历史轮转化为模型可消费的上下文格式时，三种角色消息的渲染策略形成鲜明对比：

- **用户 query**：以 `{"role": "user", "content": turn.user_content}` 形式完整原文注入。用户的原始话语是对话的语义锚点，一旦丢失将导致模型无法理解后续对话的来龙去脉。

- **模型 answer**：以 `{"role": "assistant", "content": turn.assistant_content}` 形式完整原文注入。模型的文本回复是推理链条的节点，丢失任何一个节点都会导致推理断裂。

- **工具输出**：保留原 assistant tool_calls / tool 拓扑，但历史 tool content 不再包含原始输出，只替换为简短 JSON 元数据：工具名、显式 `intent` 或启发式 `call_summary`、`context_id`、长度统计、错误状态和恢复方式。只有当这些元数据不足以回答且确实需要原始细节时，才通过 `BatchRecoverContext(items=[{context_id, offset, limit}])` 按需从 SQLite 存储中恢复。

#### 两种策略的设计逻辑

| 维度 | 活动工作阶段 | 冷历史 |
|------|--------|--------|
| 工具输出位置 | 在上下文窗口中（短输出全文，长输出首尾预览） | tool 消息原位保留，但内容替换为元数据 |
| 模型可见内容 | 原始输出或首尾预览 + 恢复方式 | 用户/模型文本完整；工具仅 intent + 恢复方式 |
| 恢复方式 | 直接使用可见 `context_id` 恢复 | 使用冷区 tool 元数据里的 `context_id` 恢复 |
| 用户 query | 已在当前轮消息中 | 完整原文注入 |
| 模型 answer | 已在当前轮消息中 | 完整原文注入 |
| 设计目标 | 保留足够细节支持当前任务推理 | 最大化上下文空间，仅保留语义骨架 |

这种分层的核心理念可以概括为：**同一任务需要的工作证据在多个连续轮次中保持热状态；任务阶段结束后才将重型工具输出降为轻量指针。**

### SQLite 持久化存储（`stores.py`）

`SQLiteMemoryStore` 是上下文虚拟化管理的持久化底座。除原有会话、消息、工具输出、快照和 token 统计表外，还包含：

- `sessions`：会话元信息（ID、标签、工作目录、创建和过期时间）
- `session_messages`：原始消息全文（role + content + tool_calls 的 JSON 序列化）
- `context_epochs`：跨多轮工作阶段、pending 提交、阶段摘要和关键恢复引用
- `session_tool_outputs`：工具输出原始文本
- `historical_turns`：结构化历史轮次（user_content + assistant_content + tool_metadata）
- `tool_invocation_metadata`：工具调用的精简元数据（参数哈希、摘要、关键词、关联文件）
- `recoverable_contexts`：可恢复上下文对象（全文 + 元数据 + 生命周期状态）
- `session_context_snapshots`：压缩上下文快照
- `conversation_snapshots`：对话检查点快照
- `skill_lrfu_cache`：用户级和会话级 LRFU 缓存

存储层支持会话过期自动清理（按 `expires_at` 字段删除过期会话及其级联数据）、跨工作目录会话隔离（每个工作目录对应独立的会话集合）和迁移检测（当工作区指纹变化时自动关联历史会话）。

---

## 其他模块实现

### 入口模块（`__main__.py`）

启动时首先清理代理环境变量以避免干扰 API 连接，随后打印 ASCII 艺术欢迎界面，检查并确保 Docker 沙箱镜像可用。然后依次初始化文件状态缓存、工作区变更追踪器、记忆运行时、核心工具注册表、多智能体运行存储和 Skill 运行时，并打印 Skill 索引同步报告。多智能体启动时会注册 `InspectSubAgentWork` 和 `DelegateToMultiAgent`；后者持有工具注册表、API 客户端、记忆运行时和主消息读取器，用于在需要时启动子智能体编排。

主循环中读取用户输入，支持输入 `exit` 退出、空输入跳过、Ctrl+C/D 安全退出。交互式终端下输入由自定义 raw TTY 输入器处理，支持光标移动、行内编辑和带换行文本粘贴；非交互式终端退化为普通 `input()`。输入首先经过命令系统匹配；普通输入统一进入模型交互循环。每轮对话结束后触发记忆模块的会话保存和检查点评估。退出时依次关闭记忆运行时、MCP、Skill 文件监听、工作区变更追踪和 API 连接。

### 配置模块（`mycodingagent/configuration/settings.py`）

将所有配置抽象为不可变数据类，按功能域划分为九个子配置：`ApiConfig`（API 密钥、基础地址、模型名）、`ClientConfig`（工具循环上限、输出截断长度、`DEBUG`/`MYCODINGAGENT_DEBUG` 调试开关，以及 `STEP_TOKEN` / `ROUND_TOKEN` / `CONVERSATION_TOKEN` 终端 token 输出开关）、`MultiAgentConfig`（子智能体单次运行工具轮次上限，默认 `MYCODINGAGENT_MULTI_AGENT_MAX_AGENT_ROUNDS=50`；任务级并发上限，默认 `MYCODINGAGENT_MULTI_AGENT_MAX_PARALLEL_TASKS=5`）、`MemoryConfig`（上下文预算比例、会话过期天数、检查点参数）、`SandboxConfig`（沙箱根目录、跳过目录）、`DockerConfig`（镜像名、资源限制、超时）、`SkillConfig`（Skill 根目录、检索参数、路由权重、LRFU 缓存参数）、`EmbeddingConfig`（BGE 模型、向量维度）和 `MilvusConfig`（连接参数、索引类型、RRF 融合参数）。所有配置值均支持通过环境变量覆盖，在模块加载时生成全局单例 `CONFIG`。

### 模型交互模块（`mycodingagent/llm_runtime/client.py`）

实现 H-Agent 的完整对话循环。`ask_deepseek` 函数是核心，首次调用时注入详尽的系统提示词，涵盖角色定义、行为准则、操作安全规范、工具使用指南、Git 安全协议和输出风格要求。若 Skill 运行时存在，还会追加能力选择策略和 Skill 检索指引。

每轮对话中，首先调用 `build_round_tools` 动态构造本轮的 tools schema——在核心工具基础上，通过 Skill 运行时的多源融合路由选出 Top-N Skill，动态暴露给模型。然后调用 `stream_one_round` 向 DeepSeek API 发起流式请求，实时打印模型输出文本，同时聚合流式工具调用分片。模型返回工具调用后，逐个执行本地工具并将结果写回消息历史；纯文本回答则视为本轮任务结束。

工具执行时对错误进行去重检测，重复失败会附加提示避免死循环。Skill 相关工具调用不持久化到长期记忆，以减少上下文膨胀。还实现了工作区文件外部变更通知——当用户修改了模型已读过的文件时，自动在下一轮消息中插入环境通知。

### 核心工具（`mycodingagent/tool_runtime/`）

工具基类 `Tool` 定义了名称、描述、参数模型和异步执行接口，子类通过实现 `execute` 方法提供具体功能。`ToolRegistry` 管理所有已注册工具，支持启用/禁用和按协议输出 schema。

六个基础工具分别为：`ReadFile` 支持按路径、偏移量和行数限制读取，读取后记录到文件状态缓存；`WriteFile` 创建或覆盖文件，执行前检查是否已读取过目标文件和外部修改状态；`EditFile` 精确字符串替换编辑，同样要求先读后改；`Glob` 通配符文件匹配，排除 `.git` 等跳过目录；`Grep` 正则内容搜索；`Bash` 在 Docker 容器内执行 Shell 命令。

所有文件工具均强制执行沙箱边界检查，将 Docker 容器内的 `/workspace` 路径别名映射到宿主机沙箱根目录，拒绝越界访问。

### 工作区管理（`tools/file_state_cache.py`、`tools/workspace_change_tracker.py`）

`FileStateCache` 记录模型已读取文件的路径、内容和修改时间戳，用于强制"先读后改"规则——`WriteFile` 和 `EditFile` 会检查目标文件是否已被读取，以及自读取后是否被用户外部修改。支持序列化快照以便会话恢复。

`WorkspaceChangeTracker` 监听工作区文件变更，优先使用 Linux inotify 接口（低延迟、低开销），不可用时降级为轮询模式。通过对比文件指纹（mtime + size）区分模型自身写入和用户外部修改，仅将模型已读取且被外部修改的文件通知给模型。

### 命令系统（`commands/`）

`CommandRegistry` 提供命令注册、前缀匹配、精确匹配和参数解析。`InteractivePrompt` 在用户输入 `/` 开头的内容时实时弹出候选命令列表，支持方向键选择、Enter 接受当前候选和用法面板展示。

内置 `/resume` 命令列出当前工作目录下的历史会话，支持方向键交互选择、跨工作目录恢复确认和会话 ID 直接恢复。恢复后加载完整消息历史、LRFU 快照和文件状态快照。`/delete` 命令支持交互式选择删除、按会话 ID 删除和 `--expired` 批量清理过期会话。

### 终端交互（`mycodingagent/terminal_ui/input.py`）

`InteractivePrompt` 在非交互式终端（管道/重定向）下退化为普通 `input()` 调用。在交互式终端中，使用 `tty.setraw` 进入原始模式并启用 bracketed paste，逐字符处理键盘输入。输入缓冲区维护 `cursor_index`，因此支持左右方向键移动光标、Home/End 跳转到当前行首尾、退格和 Delete 按光标位置删除、Ctrl+C 中断、Ctrl+D 空缓冲退出、回车提交。

粘贴带换行文本时，终端会通过 bracketed paste 序列包裹粘贴内容；输入器将 `\r\n` / `\r` 统一归一化为 `\n` 并作为正文插入，而不会把第一行当作完整用户输入提前提交。多行输入渲染时，首行显示真实提示符，后续行按提示符可见宽度缩进；回显同样使用 CRLF 和等宽缩进，避免 raw mode 下显示错位。命令建议列表仍使用上下方向键选择；当没有可选命令建议时，上下方向键用于在多行输入中垂直移动光标。

渲染层处理 ANSI 颜色的可见宽度计算（依赖 `wcwidth`）、硬换行、提示符宽度缩进和光标定位。命令建议下拉菜单支持动态刷新而不会造成终端闪烁。

### 会话管理（`session_switch.py`、`conversation_history.py`）

`session_switch.py` 判断当前对话是否有实际内容，在需要时保存当前会话的消息、LRFU 快照和文件状态快照。`conversation_history.py` 格式化渲染历史对话，区分 user、assistant、tool 等角色，显示工具调用摘要，对超长消息进行截断。

### 工作区标识（`workspace_identity.py`）

通过 Git 仓库信息（根目录、远程 URL）或项目标记文件（`pyproject.toml`、`package.json`、`requirements.txt`）生成工作区指纹，用于识别同一项目在不同路径下的会话关联。同时提供工作区标签（目录名）和根路径文本表示。

### Docker 沙箱（`Dockerfile.sandbox`、`Docker_Image_Configuration.md`）

Bash 工具的执行环境基于一次性 Docker 容器，容器退出后自动删除。基础镜像预装常用 Linux 命令行工具和 Python 包，默认使用 Aliyun 源加速。项目支持通过修改 `Dockerfile.sandbox` 和 `requirements-sandbox.txt` 自定义沙箱环境，`tools/bash.py` 在镜像不存在时自动触发本地构建。

### 缓存（`cache.py`）

`FileCache` 是一个简单的线程安全字典缓存，用于存储模型已读取的文件内容，避免对同一文件的重复磁盘 IO。支持 get、put、invalidate 和 clear 操作，所有操作持有线程锁。
