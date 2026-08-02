# myCodingAgent 项目流程框架

> 本文档按项目主流程组织，用于说明一次用户请求从终端输入到模型调用、工具执行、上下文管理、长期记忆、多智能体和退出持久化的完整链路。模块级函数清单不再作为本文主体；需要函数细节时以源码和测试为准。

---

## 1. 总体主流程

```text
启动 myAgent
  -> 加载配置
  -> 初始化运行资源
  -> 进入终端主循环
  -> 读取用户输入
  -> 命令分流
     ├─ CLI 命令：由 commands handler 直接处理
     └─ 普通请求：进入 LLM Runtime
  -> 组装 Runtime Context
  -> 构造本轮 tool schema
  -> 调用模型
  -> 执行工具调用
  -> 保存工具结果和会话状态
  -> 循环直到模型输出最终回答
  -> 轮次收尾：检查点、上下文提交、LRFU、文件状态
  -> 用户退出：保存会话并调度长期记忆抽取
```

核心模块职责：

| 流程阶段 | 主模块 | 职责 |
|---|---|---|
| 启动组装 | `mycodingagent/app/main.py` | 创建配置、工具、记忆、MCP、Skill、多智能体存储 |
| 输入与命令 | `terminal_ui/`, `commands/` | 读取终端输入、命令匹配、会话切换 |
| 模型循环 | `llm_runtime/client.py` | 构造消息、调用模型、执行工具循环 |
| 工具系统 | `tool_runtime/` | 文件、Bash、MCP、Skill、记忆恢复工具 |
| 会话上下文 | `memory/` | 消息持久化、上下文虚拟化、检查点、恢复 |
| 长期记忆 | `long_term_memory/` | 跨会话记忆抽取、查询、作用域管理 |
| 能力路由 | `capability_discovery/`, `skill_runtime/`, `mcp_integration/` | Skill/MCP 能力发现与推荐 |
| 多智能体 | `mycodingagent/multi_agent/` | 显式 `/multiAgent` 任务编排 |

---

## 2. 启动流程

### 2.1 加载配置

```text
程序入口 __main__.py
  -> mycodingagent.app.main.main()
  -> configuration/settings.py 生成 CONFIG
  -> 读取环境变量覆盖默认值
```

配置覆盖范围包括：

- 模型 API：base URL、API key、模型名。
- 工具循环：最大轮次、输出截断、token 显示。
- Docker：镜像名、CPU、内存、超时。
- Memory：上下文窗口、RAW/虚拟化阈值、热工作区阈值。
- LongTermMemory：存储模型、查询模型、抽取超时、启动回填。
- Skill：Skill 根目录、Embedding、Milvus、LRFU 权重。
- MCP：配置文件路径、重连频率、风险策略。
- MultiAgent：子智能体最大轮次、并行任务数。

### 2.2 初始化基础资源

启动阶段按依赖顺序执行：

```text
检查 Docker 沙箱镜像
  -> 创建 FileStateCache
  -> 启动 WorkspaceChangeTracker
  -> 创建 MemoryRuntime
  -> 创建 ToolRegistry 并注册核心工具
  -> 初始化 MCPClientManager
  -> 注册 MCP discovery/execution tools
  -> 初始化 SkillRuntime
  -> 创建 CapabilityRouter
  -> 创建 LongTermMemoryRuntime
  -> 创建 MultiAgentStore
  -> 构造 CommandRegistry
```

关键原则：

- `app/main.py` 是组合根，负责创建具体实现。
- 业务模块尽量依赖 Protocol 或抽象接口。
- 资源关闭顺序与初始化顺序相反，避免未保存消息或未关闭连接。

### 2.3 启动后台任务

启动后会触发：

1. Skill 文件监听，用于热加载 Skill 变化。
2. Workspace 文件监听，用于发现用户外部修改。
3. Memory async writer，用于异步保存会话和快照。
4. Long-term memory startup backfill，用于重新处理异常中断或超时未完成的 extraction。
5. MCP 不可用 server 的后续异步重连。

---

## 3. 用户输入流程

### 3.1 终端读取

```text
read_user_prompt()
  -> 交互式终端：InteractivePrompt raw TTY
  -> 非交互终端：input()
```

交互式输入支持：

- 光标左右移动。
- Home/End。
- Backspace/Delete。
- 多行 bracketed paste。
- `/` 命令候选。
- 上下方向键选择命令或多行移动。

### 3.2 命令分流

用户输入后先交给 `CommandRegistry`：

```text
prompt.strip()
  -> command_registry.execute()
     ├─ 匹配命令：执行 handler，返回 CommandResult
     └─ 未匹配：进入普通 LLM 请求
```

主要命令：

| 命令 | 流程 |
|---|---|
| `/resume` | 保存当前会话 -> 选择历史会话 -> 加载消息/LRFU/文件状态 |
| `/fork` | 保存当前会话 -> 选择源会话 -> 创建新 session |
| `/clear` | 保存当前会话 -> 标记长期记忆 pending -> 开启新 session |
| `/delete` | 删除指定会话、多个会话或过期会话 |
| `/multiAgent` | 创建/恢复/查看多智能体任务 |

命令切换前会调用会话保存逻辑，避免当前对话丢失。

---

## 4. 普通请求执行流程

普通请求进入 `llm_runtime/client.py::ask_deepseek()`。

### 4.1 轮次开始

```text
start_session()
  -> begin Skill turn
  -> messages.append(user prompt)
  -> save_messages()
  -> save_lrfu_snapshot()
  -> save_file_state_snapshot()
```

此时用户原始输入已经进入持久化消息历史。

### 4.2 能力与记忆准备

Runtime 并行准备当前轮上下文需要的信息：

1. `CapabilityRouter.route(prompt)`：召回 Skill/MCP 能力。
2. `LongTermMemoryRuntime.retrieve_for_turn(...)`：查询长期记忆。
3. `MemoryRuntime.context_mode(session_id)`：判断 RAW 或虚拟化模式。
4. `WorkspaceChangeTracker`：提供外部文件变更通知。

### 4.3 Runtime Context 构造

```text
RuntimeContextBuilder.build()
  -> workspace notice
  -> context mode
  -> capability recommendations
  -> long_term_memory.memory 文本
  -> budget state
```

随后由 `PromptRenderer.render_current_user_message()` 包装成：

```text
<RUNTIME_CONTEXT>
...
</RUNTIME_CONTEXT>

<USER_REQUEST>
用户当前请求
</USER_REQUEST>
```

模型必须把 `<USER_REQUEST>` 当作真实用户请求，把 `<RUNTIME_CONTEXT>` 当作环境状态。

---

## 5. Tool schema 构造流程

### 5.1 核心工具来源

```text
ToolRegistry
  -> ReadFile / WriteFile / EditFile / Glob / Grep / Bash / ask_user
  -> Memory lookup tools
  -> MCP discovery/execution tools
  -> Skill management tools
```

核心工具长期注册在 `ToolRegistry`。

### 5.2 本轮工具来源

每轮请求调用 `build_round_tools(default_tools, core_tool_schemas)`，返回的是**固定**的核心 schema：

```text
核心工具 schemas（含 Skill 固定入口和 MCP 固定 discovery/execution tools）
  -> 本轮 OpenAI tool schema
```

Skill **不再**逐个注册动态 function schema，统一通过 `invoke_skill` 按名称调用；
Capability Router 的推荐只作为文本进入 Runtime Context，不参与 tool schema 构造。
因此本轮 schema 在整轮工具循环内保持同一对象，既避免膨胀也利于 prompt 缓存。

多智能体委托工具不再注册给主模型。多智能体只能通过用户显式 `/multiAgent` 命令启动。

### 5.3 Tool schema 设计约束

- 工具参数必须尽量短。
- 工具调用应包含 `intent`，便于冷历史虚拟化。
- 大输出必须可恢复，而不是长期塞进上下文。
- MCP server 新增不应导致主模型 tool schema 膨胀。
- 子智能体工具按角色隔离，不能把写工具暴露给只读角色。

---

## 6. 模型调用与工具循环

### 6.1 单轮模型调用

```text
stream_one_round()
  -> 发送 messages + tools
  -> 终端显示 H-Agent:分析中. / .. / ... 状态动画
  -> 收集 assistant 文本和 tool_call delta
  -> 有工具调用时交给 terminal_ui/output.py 分组和彩色展示
  -> 无工具调用时将最终回答交给 terminal_ui/output.py，经 terminal_ui/highlighters 识别后按 Markdown 渲染
  -> 失败且可重试：清空本次累积分片，指数退避后重发
  -> 返回 assistant_text, tool_calls, usage
```

重试覆盖请求创建**和**流式迭代两个阶段：

| 失败类型 | 处理 |
|---|---|
| 连接失败 / 超时 | 重试（默认 3 次，退避 1s/2s/4s） |
| 429、5xx | 重试 |
| 4xx（鉴权、参数错误） | 立即失败，重试无意义 |

重试次数与退避基准由 `MYCODINGAGENT_API_MAX_RETRIES` 和 `MYCODINGAGENT_API_RETRY_BASE_DELAY` 控制。

重试耗尽后按本轮是否已有工具结果分流：

```text
已执行过工具
  -> 保留用户消息和全部工具结果 + 追加中断说明（用户可说"继续"）
没有任何进展
  -> 回滚 messages[turn_start:]
```

### 6.2 有工具调用时

```text
assistant tool_calls
  -> 追加 assistant message
  -> 遍历 tool_calls
  -> execute_local_tool()
  -> 得到 (output, is_error)
  -> 保存完整工具输出
  -> 生成模型可见 tool message（metadata 含 is_error）
  -> 再次调用模型
```

工具输出处理规则：

- 短输出直接返回。
- 长输出存 SQLite，返回首尾预览和 `context_id`。
- 虚拟化后历史工具输出只保留 metadata。
- 需要完整内容时调用 `BatchRecoverContext`。

失败判定只依据 `ToolResult.is_error`，并写入 metadata 的 `is_error` 字段，
使冷历史虚拟化后仍保留错误状态。不再用输出文本中是否含 `error` 字样猜测失败。
同一工具 + 同一参数在一轮内重复失败时，才追加“不要重复重试”提示。

### 6.3 无工具调用时

模型输出最终文本后：

1. 追加 assistant message。
2. 保存会话状态。
3. 更新 Skill LRFU。
4. 记录长期记忆 workflow/skill 使用情况。
5. 执行上下文检查点和 epoch 收尾。
6. 输出 token 统计。

---

## 7. 工具执行安全流程

### 7.1 文件工具

```text
ReadFile
  -> 路径归一化和越界检查
  -> 读取内容
  -> FileStateCache 记录 snapshot

WriteFile/EditFile
  -> 路径归一化和越界检查
  -> 检查是否已读取
  -> 检查 mtime/size 是否变化
  -> 写入
  -> WorkspaceChangeTracker 记录模型写入
```

安全目标：

- 防止越界写入。
- 防止未读文件被覆盖。
- 防止覆盖用户在外部刚刚修改的文件。

### 7.2 Bash 工具

```text
Bash(command)
  -> 映射工作区到 Docker /workspace
  -> 一次性容器执行
  -> 限制 CPU/内存/超时
  -> 返回 stdout/stderr/exit code
```

在多智能体 execute 中，Bash 额外需要 `declared_write_files`，Runtime 会用前后快照发现未声明写入并回滚。

命令在进入容器前先经过 Bash AST 风险分析（`tool_runtime/command_policy.py`）：

```text
BashPolicyEvaluator(command)
  -> low：直接执行
  -> approval/unknown：CommandApprovalHook 请求确认
  -> high：拒绝执行
     -> 允许：正常执行
     -> 拒绝：返回"用户拒绝执行该命令"（is_error=True）
```

判定范围限定为难以撤销或越界的操作（`rm -rf`、`git push --force`、`git reset --hard`、
`sudo`、`chmod -R`、管道执行下载脚本、裸设备写入、工作区外绝对路径操作）。
审批钩子仅在交互式终端由 `app/main.py` 注入；`approval_hook=None` 时不拦截，
保证非交互场景和既有测试行为不变。核心文件工具 `WriteFile` / `EditFile` 默认不注入交互式审批钩子。

### 7.3 MCP 工具

```text
call_mcp_tool(server, tool)
  -> 实时刷新 schema/annotation
  -> 按显式配置、annotation 和工具名分类风险
  -> discovery gate 通过后调用工具
  -> CLI 默认只对 MCP Server 启动/连接审批，不对单次 MCP 工具调用弹审批
```

---

## 8. Skill 能力路由流程

### 8.1 Skill 同步

```text
扫描 skills/
  -> 解析 SKILL.md / .skill.json
  -> 解析 references/
  -> 计算 hash
  -> 与 SQLite 记录对比
  -> 新增/更新进入审查
```

### 8.2 Skill 审查

```text
新增或更新 Skill
  -> review_skill_code
  -> review_skill_prompt
  -> 通过后写入 SQLite
  -> 更新向量索引
```

### 8.3 Skill 检索

```text
用户请求
  -> BGE-M3 embedding
  -> Milvus 向量检索
  -> BM25 关键词检索
  -> RRF 融合排序
  -> 本地关键词回退
```

### 8.4 Skill 路由评分

最终排序融合：

1. 向量/关键词检索相关性。
2. 用户级 LRFU。
3. 会话级 LRFU。
4. 默认 Skill。
5. Pin Skill。

结果 Top-N 以动态 tool schema 暴露给模型。

---

## 9. MCP 能力发现流程

### 9.1 配置加载

```text
~/.config/myCodingAgent/mcp.json
  -> .mycodingagent/mcp.json
  -> MYCODINGAGENT_MCP_CONFIG
```

后加载配置覆盖同名 server。

### 9.2 Server discovery

```text
MCPClientManager.initialize()
  -> 按需建立 stdio / Streamable HTTP 连接
  -> tools/list
  -> resources/list
  -> prompts/list
  -> 写入指纹校验的 SQLite metadata cache
```

### 9.3 Runtime 可用性

```text
server 初始 available=true
  -> discovery/execution 失败：available=false + error
  -> 主动探测成功：available=true
  -> 每 N 个用户轮后台重连不可用 server
```

### 9.4 模型可见 MCP 工具

固定 discovery 工具：

- `list_mcp_servers` / `search_mcp_servers`
- `list_mcp_tools` / `search_mcp_tools`
- `list_mcp_resources` / `search_mcp_resources`
- `list_mcp_prompts` / `search_mcp_prompts`

固定 execution 工具：

- `call_mcp_tool`
- `read_mcp_resource`
- `get_mcp_prompt`

---

## 10. 上下文管理流程

### 10.1 RAW 模式

```text
新会话开始
  -> RAW mode
  -> 用户/assistant 文本完整保留
  -> 短工具输出完整保留
  -> 长工具输出首尾预览 + context_id
```

### 10.2 热工作区

```text
ContextEpochManager.ensure()
  -> 当前任务建立热工作阶段
  -> 相关后续轮次继续复用
  -> 热区超过 warning ratio：提示模型压缩或提交
  -> 热区超过 force ratio：Runtime 安全边界强制提交
```

热工作区保存当前任务仍需要的文件内容、工具结果和推理上下文。

### 10.3 冷历史虚拟化

```text
ContextEpoch finalize
  -> 旧阶段进入冷历史
  -> user query 完整保留
  -> assistant answer 完整保留
  -> tool output 替换为 metadata
```

工具 metadata 包含：

- tool name
- intent
- call summary
- context_id
- output length
- error status
- recovery method

### 10.4 恢复流程

当模型需要冷历史细节：

```text
SearchRecoverableContext(query)
  -> 找 context_id
BatchRecoverContext(items)
  -> 按 offset/limit 读取完整内容片段
```

会话级恢复工具包括：

- `SearchSessionHistory`
- `GetRecentConversationTurns`
- `RestoreSession`

### 10.5 Rollover

当整体上下文压力过高：

```text
CheckpointManager
  -> 生成 conversation snapshot
  -> mark old session historical
  -> 创建新 session
  -> 新 session 首条消息包含归档摘要和恢复入口
```

---

## 11. 长期记忆流程

### 11.1 抽取触发

```text
会话中
  -> 不同步调用存储模型
exit / clear / resume / fork
  -> mark_session_pending
退出时
  -> extract_session_now(timeout)
超时或中断
  -> 下次启动 schedule_startup_backfill
```

### 11.2 存储模型输入

`session_serializer.py` 生成存储 payload：

- session id、workspace root、workspace label、workspace fingerprint。
- 用户和 assistant 消息全文。
- assistant tool_calls 参数和 `intent`。
- tool message 的状态、大小、错误标记和 metadata。
- tool catalog 的 name/description。
- existing global memories。
- existing workflow staging memories。
- existing workspace memories。

不提供原始工具输出，避免把代码、日志和临时结果沉淀为长期记忆。

### 11.3 存储模型输出

存储模型只能调用 `SubmitLongTermMemoryPatch`。

新建记忆使用 typed buckets：

- `user_profiles`
- `user_preferences`
- `project_facts`
- `workflows`
- `skill_candidates`

Runtime 根据 bucket 推导：

| Bucket | Memory Type | Namespace |
|---|---|---|
| `user_profiles` | `user_profile` | global user |
| `user_preferences` | `user_preference` | global user |
| `project_facts` | `project_fact` | current workspace |
| `workflows` | `workflow_candidate` | workflow staging |
| `skill_candidates` | `skill_candidate` | global user |

`workflows` 与 `skill_candidates` 使用新的强结构 schema：

- `name`：稳定短名称，用于识别和审计。
- `description`：说明该 workflow 解决什么问题。
- `when_to_use`：查询模型判断是否注入的正向适用条件。
- `when_not_use`：误用反例边界，初始可为空，最多 3 条，只能由后续失败、用户纠正或复盘补充。
- `content`：具体执行流程。

Store 层会拒绝缺少结构化 workflow 字段的 workflow_candidate / skill_candidate。

### 11.4 写入与并发

```text
claim extraction
  -> 获取 global / workflow / workspace 三层写锁
  -> 读取三层 latest committed version
  -> storage model 生成 patch
  -> 按 namespace 拆分 patch
  -> staging version 写入
  -> committed
  -> 释放写锁
```

查询模型始终读取 committed version。写入未完成时，查询不会看到半成品。

### 11.5 查询与注入

```text
每轮用户请求前
  -> 读取 global items
  -> 读取 workflow staging items
  -> 读取 current workspace items
  -> query model 选择相关记忆
  -> Runtime 拼接用户画像/用户偏好/项目事实/可能相关工作流
  -> 注入 Runtime Context 的 long_term_memory.memory
```

当用户明确提到其他项目、路径或历史 workspace 时，查询模型可调用 `SearchWorkspaceProjectFacts` 读取其他 workspace 的抽象项目事实。

若四类内容均为空，`long_term_memory.memory` 固定为 `未查询到相关记忆`。workflow 和 skill candidate 会在文本中保留 `uses_memory_uid=<memory_uid>`，以便轮次结束后判断该候选是否被实际使用。

### 11.6 Workflow 生命周期

```text
workflow_candidate 暂存
  -> 被其他三个不同项目查询但未使用
     -> 降级为 origin workspace 专属
  -> 被其他三个不同项目查询并成功使用
     -> 升级为 global skill_candidate
  -> skill_candidate 成功复用达到阈值
     -> Runtime 询问用户是否沉淀为正式 Skill
```

---

## 12. 多智能体流程

多智能体只由用户显式 `/multiAgent` 命令启动。

### 12.1 主状态机

```text
create run
  -> PLANNING
  -> PLAN_REVIEW
  -> SCHEDULING
  -> TASK EXECUTION
  -> FINAL_TESTING
  -> COMPLETED / FAILED
```

### 12.2 Plan 阶段

```text
plan subagent
  -> 查看 task + 最近主对话
  -> 可用只读工具理解项目
  -> 调用 SubmitPlan
```

计划必须结构化，包含步骤、目标、依赖、验收标准。

### 12.3 Plan Review 阶段

```text
plan_review subagent
  -> 审查 submitted_plan
  -> 合格：ApprovePlan
  -> 不合格：RejectPlan(feedback)
```

RejectPlan 会写入 feedback event，下一次 plan 继续上次上下文修正。

### 12.4 Scheduling 阶段

```text
scheduling subagent
  -> 查看 approved_plan 和已完成任务
  -> DispatchTasks 批量派发
  -> Runtime 阻塞推进批次
  -> 返回 passed/failed/blocked
  -> 全部完成后 SubmitFinalTest
```

scheduling 不直接修改文件。

### 12.5 Execute/Test 任务阶段

每个 task 绑定一个 execute 和一个 task_test：

```text
execute
  -> 只看 assigned task / test instruction / approved_plan
  -> 用读写工具修改代码
  -> SubmitTaskExecution

task_test
  -> 看 paired task 和 execute submission
  -> 运行验证
  -> ApproveTaskTest 或 ReportTaskFailure
```

失败反馈会续接回 execute，而不是重置上下文。

### 12.6 Final Test 阶段

```text
final_test
  -> 查看 approved_plan
  -> 查看所有 task submissions
  -> 执行全局验证
  -> ApproveFinalTest / ReportFinalTestFailure
```

最终失败反馈回 scheduling，由 scheduling 派发修复任务。

### 12.7 文件协调

`FileCoordinator` 管理并发写冲突：

1. `ReadFile` 记录 task 对文件的读取 revision。
2. `WriteFile/EditFile` 写入前申请文件级写锁。
3. 写入时校验读取 revision 是否仍是当前 revision。
4. stale file 拒绝并要求重读。
5. Bash 必须声明 `declared_write_files`。
6. Bash 前后做文件快照。
7. 未声明写入回滚。
8. 文件变化通知写入等待 task 的 runtime notices。

execute 提示词中要求冲突避让四步：

```text
读取变化
  -> 选择分支/新函数等避让方式
  -> 修改代码
  -> 复查修改后的文件
```

---

## 13. 退出与持久化流程

用户输入 `exit` 或 Ctrl+D 后：

```text
保存当前 session messages
  -> 保存 LRFU snapshot
  -> 保存 file state snapshot
  -> await pending rollover
  -> 标记长期记忆 pending
  -> 在超时窗口内抽取长期记忆
  -> 关闭 LongTermMemoryRuntime
  -> 关闭 MemoryRuntime
  -> 关闭 MCP manager
  -> 关闭 Skill watcher
  -> 关闭 WorkspaceChangeTracker
  -> 关闭 API client
```

如果长期记忆抽取超时，不阻塞退出；下一次启动会异步重新处理。

---

## 14. 数据持久化

### 14.1 Memory SQLite

`CONFIG.memory.db_path` 对应主记忆数据库，保存：

- sessions
- session_messages
- session_tool_outputs
- context_epochs
- recoverable_contexts
- historical_turns
- tool_invocation_metadata
- conversation_snapshots
- token usage
- LRFU snapshots
- file state snapshots
- long-term memory versions/items/extractions/usage/locks

### 14.2 MultiAgent SQLite

默认路径为 memory db 同目录的 `multi_agent.sqlite3`，保存：

- run id
- run status
- structured plan
- scheduled tasks
- subagent messages
- task submissions
- feedback events
- file coordination state
- runtime notices
- final answers

### 14.3 Skill/Milvus

Skill 元数据和 LRFU 保存在 SQLite；向量索引保存在 Milvus。Milvus 不可用时，Skill 检索回退本地关键词匹配。

---

## 15. 架构边界

```text
app -> 组合根，可依赖所有运行模块
llm_runtime -> 不直接依赖具体 Skill/MCP 实现，只通过 registry/runtime 参数协作
memory -> 不依赖 tool_runtime 具体工具实现
tool_runtime -> 适配 MCP/Skill/Memory，但基础工具保持独立
multi_agent -> 使用自身 store/context/tools/file_coordination，与主模型 tool schema 解耦
skill_runtime -> 依赖 relevance，不依赖 llm_runtime
capability_discovery -> 依赖抽象 capability source，不执行真实 MCP 调用
```

验证重点：

- 核心模块无 import cycle。
- 只读子智能体不拥有写工具。
- 主模型看不到多智能体委托工具。
- 长期记忆写入必须经过 typed bucket 和 namespace 校验。
- 冷历史工具输出必须可恢复但不直接塞全文。

---

## 16. 推荐验证命令

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_long_term_memory.py tests/test_memory_runtime.py tests/test_multi_agent.py
```

改动主循环、工具执行或命令审批时补跑：

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_llm_runtime_client.py tests/test_command_policy.py
```

更完整回归可继续运行：

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
```

当前基线：`257 passed`。
