# myCodingAgent

## 项目定位

myCodingAgent 是一个基于大语言模型（LLM）的命令行编码智能体。它在隔离的 Docker 沙箱中运行，能够理解用户的中文自然语言编程需求，自动调用文件读写、搜索、Shell 命令等工具完成编码任务。项目以"先读后改、按需调用、安全可控"为设计原则，既提供基础编码工具，也通过开放式的 Skill 系统支持开发者定义领域专家工作流，覆盖从代码开发、审查、面试到内容创作、视频生成等多种场景。

## 项目框架

项目采用分层架构，由以下核心子系统协同工作：

- **入口层**：`__main__.py` 负责启动全流程——打印欢迎界面、检查 Docker 镜像、初始化各子系统、进入交互循环并协调模型对话。
- **配置层**：`config.py` 将项目所有可配置项统一为数据类，通过环境变量驱动，涵盖 API、客户端行为、记忆管理、沙箱、Docker、Skill 和向量检索等维度。
- **模型交互层**：`client.py` 封装与 DeepSeek API 的通信，包括系统提示词注入、流式响应解析、工具调用的循环执行和结果回传。
- **工具层**：`tools/` 提供六大核心基础工具（文件读写、内容搜索、通配符匹配、Shell 命令执行）以及记忆相关工具，所有文件操作限定在沙箱工作区内。
- **Skill 系统层**：`skills/` 实现开发者 Skill 的发现、注册、向量检索、路由选择和调用执行，让模型能按需动态获取领域专家工作流。
- **记忆管理层**：`memory/` 实现上下文预算控制、检查点快照、会话回滚和可恢复上下文，保证长对话中的状态一致性和 token 高效利用。
- **命令系统层**：`commands/` 提供 `/resume`、`/delete` 等会话管理命令，支持交互式选择和跨工作目录操作。
- **终端交互层**：`cli_input.py` 实现带 ANSI 转义序列处理、退格删除、方向键选择补全的交互式输入体验。
- **基础设施层**：`cache.py` 提供线程安全的文件内容缓存，`workspace_identity.py` 实现工作区指纹识别，`session_switch.py` 协调会话保存与切换。

## 模块实现

### 入口模块（`__main__.py`）

启动时首先清理代理环境变量以避免干扰 API 连接，随后打印 ASCII 艺术欢迎界面，检查并确保 Docker 沙箱镜像可用。然后依次初始化文件状态缓存、工作区变更追踪器、记忆运行时、核心工具注册表和 Skill 运行时，并打印 Skill 索引同步报告。

主循环中读取用户输入，支持输入 `exit` 退出、空输入跳过、Ctrl+C/D 安全退出。输入首先经过命令系统匹配，若命中 `/resume` 或 `/delete` 则执行会话管理逻辑；否则将用户需求交由模型交互循环处理。每轮对话结束后触发记忆模块的会话保存和检查点评估。退出时依次关闭记忆运行时、Skill 文件监听、工作区变更追踪和 API 连接。

### 配置模块（`config.py`）

将所有配置抽象为不可变数据类，按功能域划分为八个子配置：`ApiConfig`（API 密钥、基础地址、模型名）、`ClientConfig`（工具循环上限、输出截断长度）、`MemoryConfig`（上下文预算比例、会话过期天数、检查点参数）、`SandboxConfig`（沙箱根目录、跳过目录）、`DockerConfig`（镜像名、资源限制、超时）、`SkillConfig`（Skill 根目录、检索参数、路由权重、LRFU 缓存参数）、`EmbeddingConfig`（BGE 模型、向量维度）和 `MilvusConfig`（连接参数、索引类型、RRF 融合参数）。所有配置值均支持通过环境变量覆盖，在模块加载时生成全局单例 `CONFIG`。

### 模型交互模块（`client.py`）

实现 H-Agent 的完整对话循环。`ask_deepseek` 函数是核心，首次调用时注入详尽的系统提示词，涵盖角色定义、行为准则、操作安全规范、工具使用指南、Git 安全协议和输出风格要求。若 Skill 运行时存在，还会追加能力选择策略和 Skill 检索指引。

每轮对话中，首先调用 `build_round_tools` 动态构造本轮的 tools schema——在核心工具基础上，通过 Skill 运行时的多源融合路由（向量检索 + 用户 LRFU 缓存 + 会话 LRFU 缓存 + 固定 Pin 列表）选出 Top-N Skill，动态暴露给模型。然后调用 `stream_one_round` 向 DeepSeek API 发起流式请求，实时打印模型输出文本，同时聚合流式工具调用分片。模型返回工具调用后，逐个执行本地工具并将结果写回消息历史；纯文本回答则视为本轮任务结束。

工具执行时对错误进行去重检测，重复失败会附加提示避免死循环。Skill 相关工具调用不持久化到长期记忆，以减少上下文膨胀。还实现了工作区文件外部变更通知——当用户修改了模型已读过的文件时，自动在下一轮消息中插入环境通知。

### 核心工具（`tools/`）

工具基类 `Tool` 定义了名称、描述、参数模型和异步执行接口，子类通过实现 `execute` 方法提供具体功能。`ToolRegistry` 管理所有已注册工具，支持启用/禁用和按协议输出 schema。

六个基础工具分别为：`ReadFile` 支持按路径、偏移量和行数限制读取，读取后记录到文件状态缓存；`WriteFile` 创建或覆盖文件，执行前检查是否已读取过目标文件和外部修改状态；`EditFile` 精确字符串替换编辑，同样要求先读后改；`Glob` 通配符文件匹配，排除 `.git` 等跳过目录；`Grep` 正则内容搜索；`Bash` 在 Docker 容器内执行 Shell 命令。

所有文件工具均强制执行沙箱边界检查，将 Docker 容器内的 `/workspace` 路径别名映射到宿主机沙箱根目录，拒绝越界访问。

### 工作区管理（`tools/file_state_cache.py`、`tools/workspace_change_tracker.py`）

`FileStateCache` 记录模型已读取文件的路径、内容和修改时间戳，用于强制"先读后改"规则——`WriteFile` 和 `EditFile` 会检查目标文件是否已被读取，以及自读取后是否被用户外部修改。支持序列化快照以便会话恢复。

`WorkspaceChangeTracker` 监听工作区文件变更，优先使用 Linux inotify 接口（低延迟、低开销），不可用时降级为轮询模式。通过对比文件指纹（mtime + size）区分模型自身写入和用户外部修改，仅将模型已读取且被外部修改的文件通知给模型。

### Skill 系统（`skills/`）

Skill 运行时 `SkillRuntime` 是整个 Skill 系统的中枢，管理 Skill 的完整生命周期。初始化时加载本地 SQLite 索引中的 Skill 记录和引用文件，注册五个 Skill 管理工具（`search_tool`、`Get_all_tool`、`Get_tool_by_name`、`search_skill_references`、`Get_skill_reference`），启动多目录文件监听器。

Skill 发现模块（`discovery.py`）递归扫描 Skill 根目录，从 `SKILL.md` 或 `.skill.json` 文件中提取 Skill 的名称、描述和内容，自动生成 `skill_` 前缀的规范化工具名。同时也扫描每个 Skill 的 `references/` 子目录，索引其下的参考文档。

同步流程（`sync` 方法）将发现的 Skill 与已存储记录比对，检测新增、更新和删除。新增或更新的 Skill 需要经过双重审查——`review_skill_code` 检查 Skill 定义中的代码安全性，`review_skill_prompt` 检查提示词质量——审查通过后才写入 SQLite 并同步到向量存储。

向量检索使用 BGE-M3 模型生成文本嵌入，存储于 Milvus 向量数据库，同时利用 Milvus 内置 BM25 关键词检索和 RRF 融合排序实现混合检索。当向量检索不可用时，自动回退到本地关键词匹配。

Skill 路由模块（`router.py`）融合三个信号源：向量检索结果（recency × 语义相关性）、用户级 LRFU（Least Recently/Frequently Used）缓存（跨会话偏好学习）和会话级 LRFU 缓存（当前会话内的短期记忆），加上默认 Skill 和手动 Pin 的固定信号，通过加权打分选出最终暴露给模型的 Top-N Skill 列表，并强制保证检索结果的最小占比。

Skill 调用后通过 `record_skill_invocation` 更新 LRFU 缓存和 Pin 状态，形成正向反馈闭环。

### 记忆管理（`memory/`）

记忆运行时 `MemoryRuntime` 是对外统一接口，内部协调多个子系统。

**提示词预算管理**（`budget.py`）：将上下文窗口划分为 normal、soft、working、emergency 四个阶段。每个阶段对应不同的使用比例阈值，当 token 用量逼近限制时触发不同级别的压缩或摘要策略，同时预留推理、输出和工具调用的专用 token 配额。

**检查点与快照**（`checkpoint.py`）：当预算进入高水位时生成结构化对话快照，包含总体任务摘要、推理结论、项目状态、未完成任务、用户意图、重要决策和可恢复上下文引用列表。使用增量快照机制——仅在已有快照基础上记录新变化，避免重复存储。快照充当会话回滚的标志点。

**会话回滚**（Session Rollover）：当上下文超出阈值时，基于最新快照创建新会话，将压缩后的消息列表（最近若干轮 + 快照摘要）作为起点继续对话。旧会话保存为历史会话记录，可通过 `/resume` 命令恢复。

**可恢复上下文对象**（`context_objects.py`）：为工具输出建立结构化的可恢复引用，包含摘要、关键词、关联文件、token 数等元数据。模型在对话中看到的是压缩后的元数据引用，需要时通过 `RecoverContext` 工具按需加载完整内容，大幅节省上下文 token。

**上下文压缩器**（`compressor.py`）：根据上下文压力动态选择压缩策略——轻度压力仅截断旧消息，中度压力进行摘要压缩，重度压力执行激进清理。区分可复现工具（如 ReadFile、Glob）和不可复现工具（如 Bash），优先保留前者的引用而压缩后者的内容。

**SQLite 存储**（`stores.py`）：持久化会话消息、历史轮次、工具调用元数据、工具输出记录、检查点记录和对话快照。支持会话过期自动清理、跨工作目录会话隔离和迁移检测。

**工作上下文**（`working_context.py`）：管理当前活跃的可恢复上下文对象池，维护每个对象的三态生命周期（working → external → archived）。

### 命令系统（`commands/`）

`CommandRegistry` 提供命令注册、前缀匹配、精确匹配和参数解析。`InteractivePrompt` 在用户输入 `/` 开头的内容时实时弹出候选命令列表，支持方向键选择、Tab 补全和用法面板展示。

内置 `/resume` 命令列出当前工作目录下的历史会话，支持方向键交互选择、跨工作目录恢复确认和会话 ID 直接恢复。恢复后加载完整消息历史、LRFU 快照和文件状态快照。`/delete` 命令支持交互式选择删除、按会话 ID 删除和 `--expired` 批量清理过期会话。

### 终端交互（`cli_input.py`）

`InteractivePrompt` 在非交互式终端（管道/重定向）下退化为普通 `input()` 调用。在交互式终端中，使用 `tty.setraw` 进入原始模式，逐字符处理键盘输入——支持退格删除、Ctrl+C 中断、Ctrl+D 退出、回车提交，以及 ANSI 转义序列的方向键导航。渲染层处理 ANSI 颜色的可见宽度计算（依赖 `wcwidth`）、多行文本自动换行和光标定位。命令建议下拉菜单支持动态刷新而不会造成终端闪烁。

### 会话管理（`session_switch.py`、`conversation_history.py`）

`session_switch.py` 判断当前对话是否有实际内容，在需要时保存当前会话的消息、LRFU 快照和文件状态快照。`conversation_history.py` 格式化渲染历史对话，区分 user、assistant、tool 等角色，显示工具调用摘要，对超长消息进行截断。

### 工作区标识（`workspace_identity.py`）

通过 Git 仓库信息（根目录、远程 URL）或项目标记文件（`pyproject.toml`、`package.json`、`requirements.txt`）生成工作区指纹，用于识别同一项目在不同路径下的会话关联。同时提供工作区标签（目录名）和根路径文本表示。

### Docker 沙箱（`Dockerfile.sandbox`、`Docker_Image_Configuration.md`）

Bash 工具的执行环境基于一次性 Docker 容器，容器退出后自动删除。基础镜像预装常用 Linux 命令行工具和 Python 包，默认使用 Aliyun 源加速。项目支持通过修改 `Dockerfile.sandbox` 和 `requirements-sandbox.txt` 自定义沙箱环境，`tools/bash.py` 在镜像不存在时自动触发本地构建。

### 缓存（`cache.py`）

`FileCache` 是一个简单的线程安全字典缓存，用于存储模型已读取的文件内容，避免对同一文件的重复磁盘 IO。支持 get、put、invalidate 和 clear 操作，所有操作持有线程锁。
