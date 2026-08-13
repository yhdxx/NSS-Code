# myCodingAgent 配置指南

> 本文件会在每次 `myAgent` 启动时自动复制到 `~/.mycodingagent/README.md`，方便离线查阅。

---

## 1. 配置方式

myCodingAgent 所有运行配置通过以下**两个来源**读取（优先级从高到低）：

| 优先级 | 来源 | 说明 |
|--------|------|------|
| **1（最高）** | `~/.mycodingagent/config.json` | 用户级 JSON 配置文件 |
| **2** | 环境变量 | JSON 字段缺失或为空字符串时生效，包括推理模型厂商 API 和 profile 字段 |

仓库内 `.mycodingagent/config.example.json` 是首次启动时复制到用户目录的全量模板；
`.mycodingagent/config.example.yaml` 仅作字段参考。两者都不参与运行时配置读取。

---

## 2. 快速开始

```bash
# 首次启动会自动创建 ~/.mycodingagent/config.json 全量模板
# 每次启动会同步 ~/.mycodingagent/README.md
myAgent

# 编辑配置文件
nano ~/.mycodingagent/config.json

# 至少需要填入所用厂商的 API Key
# 找到 "model" -> "providers" -> "deepseek" -> "api"，填入你的密钥
myAgent
```

---

## 3. 配置结构总览

`~/.mycodingagent/config.json` 包含以下 15 个顶层模块：

| Key | 说明 |
|-----|------|
| `model` | 推理模型配置（厂商级 API、模型 profile、长期记忆模型选择） |
| `client` | LLM 客户端行为（重试、调试、展示） |
| `approval` | Bash 与 MCP 的进程级审批模式 |
| `multi_agent` | 多智能体并发与轮次限制 |
| `long_term_memory` | 长期记忆存储、检索和候选推荐行为配置 |
| `memory` | 会话持久化、上下文虚拟化、检查点 |
| `sandbox` | Docker 沙箱工作区设置 |
| `docker` | Docker 容器资源限制 |
| `network` | 会话托管网络、上游代理和公网域名策略 |
| `search` | Tavily MCP 搜索凭证 |
| `web_fetch` | 静态网页读取开关与响应限制 |
| `skills` | Skill 发现、索引、路由、LRFU |
| `embedding` | 嵌入模型配置（provider/model/api_key 等） |
| `milvus` | Milvus 向量数据库连接 |
| `mcp` | MCP Server 连接与权限 |

---

## 4. 各模块配置说明

### 4.1 `model` — 推理模型配置

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `model.active` | `MYCODINGAGENT_MODEL_ACTIVE` | `"main"` | 当前主推理模型 profile key |
| `model.providers.<provider>.api` | `MYCODINGAGENT_MODEL_PROVIDER_<PROVIDER>_API` | `""` | **该厂商统一 API Key（必填）**；DeepSeek 也支持 `DEEPSEEK_API_KEY` |
| `model.providers.<provider>.base_url` | `MYCODINGAGENT_MODEL_PROVIDER_<PROVIDER>_BASE_URL` | `""` | 可选自定义 API 地址；DeepSeek 也支持 `DEEPSEEK_BASE_URL` |
| `model.providers.<provider>.timeout` | `MYCODINGAGENT_MODEL_PROVIDER_<PROVIDER>_TIMEOUT` | `null` | 可选请求超时 |
| `model.profiles.<key>.provider` | `MYCODINGAGENT_MODEL_PROFILE_<KEY>_PROVIDER` | `"deepseek"` | **厂商（必填）** |
| `model.profiles.<key>.model` | `MYCODINGAGENT_MODEL_PROFILE_<KEY>_MODEL` | `"deepseek-v4-pro"` | **模型名称（必填）** |
| `model.profiles.<key>.reasoning` | `MYCODINGAGENT_MODEL_PROFILE_<KEY>_REASONING` | `null` | 可选思考强度/模式，支持厂商专属字段 |
| `model.long_term_memory.storage` | `MYCODINGAGENT_MODEL_LONG_TERM_MEMORY_STORAGE` | `"main"` | 长期记忆存储/抽取模型 profile |
| `model.long_term_memory.search` | `MYCODINGAGENT_MODEL_LONG_TERM_MEMORY_SEARCH` | `"memory_search"` | 长期记忆检索模型 profile |
| `model.audio.provider` | `MYCODINGAGENT_MODEL_AUDIO_PROVIDER` | `"qwen"` | 音频转写厂商，仅支持 `zhipu`、`qwen` |
| `model.audio.model` | `MYCODINGAGENT_MODEL_AUDIO_MODEL` | `"qwen3-asr-flash"` | 音频转写模型 |
| `model.vision.provider` | `MYCODINGAGENT_MODEL_VISION_PROVIDER` | `"zhipu"` | 图片分析厂商，仅支持 `zhipu`、`qwen` |
| `model.vision.model` | `MYCODINGAGENT_MODEL_VISION_MODEL` | `"glm-4v-flash"` | 单图分析及多图比较模型 |

```json
{
  "model": {
    "active": "main",
    "providers": {
      "deepseek": {
        "api": "sk-..."
      },
      "zhipu": {
        "api": "sk-..."
      },
      "qwen": {
        "api": "sk-..."
      }
    },
    "profiles": {
      "main": {
        "provider": "deepseek",
        "model": "deepseek-v4-pro"
      },
      "memory_search": {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "reasoning": {
          "thinking": "disabled"
        }
      }
    },
    "long_term_memory": {
      "storage": "main",
      "search": "memory_search"
    },
    "audio": {
      "provider": "qwen",
      "model": "qwen3-asr-flash"
    },
    "vision": {
      "provider": "zhipu",
      "model": "glm-4v-flash"
    }
  }
}
```

`model.profiles.<key>.reasoning` 可以写字符串快捷值，也可以写厂商专属对象。例如 DeepSeek 可写
`{"thinking": "disabled"}`，运行时会转换为 DeepSeek 兼容接口需要的 `thinking` 请求字段；OpenAI/Grok
可写 `{"effort": "high"}` 或 `{"reasoning_effort": "high"}`。

动态字段环境变量统一使用大写 key：`model.providers.qwen.api` 对应
`MYCODINGAGENT_MODEL_PROVIDER_QWEN_API`，`model.profiles.memory_search.reasoning` 对应
`MYCODINGAGENT_MODEL_PROFILE_MEMORY_SEARCH_REASONING`。常见厂商 API 也支持通用别名，例如
`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`QWEN_API_KEY`、`DASHSCOPE_API_KEY`、`GEMINI_API_KEY`。

音频转写与视觉识别复用 `model.providers.<provider>.api`，不单独保存媒体密钥。缺少所选厂商 API 时，
应用仍可启动，只禁用对应媒体工具并打印原因。音频默认使用千问 `qwen3-asr-flash`，视觉默认使用智谱
`glm-4v-flash`；切换为智谱音频可使用 `glm-asr-2512`，切换为千问视觉建议使用 `qwen3-vl-flash`。
视觉工具一次接收 1 到 8 张图片：千问原生在一次请求中比较多图；智谱默认模型逐图提取编号证据，再综合为比较结论。媒体输入支持
工作区文件和无需认证的公网 HTTP/HTTPS URL；音频超过厂商限制时明确失败，不自动切片。

### 4.2 `client` — LLM 客户端

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `client.max_tool_rounds` | `MYCODINGAGENT_MAX_TOOL_ROUNDS` | `100` | 无计划时为单次请求上限；缺失或为空时回落到 100；执行活动计划时，每次成功提交步骤进度后重新获得完整轮次预算 |
| `client.api_max_retries` | `MYCODINGAGENT_API_MAX_RETRIES` | `3` | API 调用失败重试次数 |
| `client.api_retry_base_delay` | `MYCODINGAGENT_API_RETRY_BASE_DELAY` | `1.0` | 重试退避基础延迟（秒） |
| `client.debug` | `MYCODINGAGENT_DEBUG` | `false` | 调试模式 |
| `client.step_token` | `MYCODINGAGENT_STEP_TOKEN` | `true` | 显示步骤 token 计数 |
| `client.round_token` | `MYCODINGAGENT_ROUND_TOKEN` | `true` | 显示轮次 token 计数 |
| `client.conversation_token` | `MYCODINGAGENT_CONVERSATION_TOKEN` | `true` | 显示会话 token 计数 |

### 4.3 `approval` — Bash/MCP 审批模式

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `approval.mode` | `MYCODINGAGENT_APPROVAL_MODE` | `"default"` | `default` 按现有风险策略审批；`auto` 自动放行全部 Bash、MCP 工具和 MCP Server 启动 |

`/approval` 可以在当前 myAgent 进程内临时切换模式，重启后重新使用配置默认值。`auto` 不会关闭风险分类和风险颜色，但会自动放行包括高危操作在内的全部审批请求。

### 4.4 `multi_agent` — 多智能体

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `multi_agent.max_agent_rounds` | `MYCODINGAGENT_MULTI_AGENT_MAX_AGENT_ROUNDS` | `50` | 多智能体最大轮次 |
| `multi_agent.max_parallel_tasks` | `MYCODINGAGENT_MULTI_AGENT_MAX_PARALLEL_TASKS` | `5` | 最大并发任务数 |

### 4.5 `long_term_memory` — 长期记忆

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `long_term_memory.enabled` | `MYCODINGAGENT_LONG_TERM_MEMORY_ENABLED` | `true` | 是否启用长期记忆 |
| `long_term_memory.query_recent_turns` | `MYCODINGAGENT_LONG_TERM_MEMORY_QUERY_RECENT_TURNS` | `10` | 查询时携带的最近对话轮数 |
| `long_term_memory.max_memories` | `MYCODINGAGENT_LONG_TERM_MEMORY_MAX_MEMORIES` | `50` | 上下文注入最多记忆条数 |
| `long_term_memory.max_workflow_candidates` | `MYCODINGAGENT_LONG_TERM_MEMORY_MAX_WORKFLOW_CANDIDATES` | `5` | 工作流候选最多条数 |
| `long_term_memory.max_skill_candidates` | `MYCODINGAGENT_LONG_TERM_MEMORY_MAX_SKILL_CANDIDATES` | `3` | Skill 候选最多条数 |
| `long_term_memory.startup_backfill_enabled` | `MYCODINGAGENT_LONG_TERM_MEMORY_STARTUP_BACKFILL_ENABLED` | `true` | 启动时异步回填未完成抽取 |

### 4.6 `memory` — 会话与上下文管理

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `memory.enabled` | `MYCODINGAGENT_MEMORY_ENABLED` | `true` | 启用会话持久化 |
| `memory.state_dir` | `MYCODINGAGENT_STATE_DIR` | `~/.mycodingagent/state` | 用户全局配置/跨项目记忆的默认目录；当前工作区的运行状态使用工作区 `.mycodingagent/state/` |
| `memory.db_path` | `MYCODINGAGENT_MEMORY_DB_PATH` | `~/.mycodingagent/state/sessions.sqlite3` | 用户全局长期记忆库；会话、项目事实、代码索引、项目图谱、MCP cache 和多智能体状态落在 `<workspace>/.mycodingagent/state/` |
| `memory.default_work_mode` | `MYCODINGAGENT_DEFAULT_WORK_MODE` | `"general"` | 默认工作模式（`general` / `code`） |
| `memory.default_context_window` | `MYCODINGAGENT_MODEL_CONTEXT_WINDOW` | `1000000` | 默认上下文窗口大小；未单独配置的模型均按 1M 计算 |
| `memory.session_ttl_days` | `MYCODINGAGENT_MEMORY_SESSION_TTL_DAYS` | `90` | 会话保留天数 |
| `memory.workspace_snapshot_ttl_days` | `MYCODINGAGENT_MEMORY_WORKSPACE_SNAPSHOT_TTL_DAYS` | `30` | 工作区快照保留天数 |
| `memory.budget_soft_ratio` | `MYCODINGAGENT_BUDGET_SOFT_RATIO` | `0.60` | 上下文软预算比例 |
| `memory.budget_working_ratio` | `MYCODINGAGENT_BUDGET_WORKING_RATIO` | `0.80` | 工作区预算比例 |
| `memory.budget_emergency_ratio` | `MYCODINGAGENT_BUDGET_EMERGENCY_RATIO` | `0.90` | 紧急压缩比例 |
| `memory.hot_context_force_ratio` | `MYCODINGAGENT_HOT_CONTEXT_FORCE_RATIO` | `0.40` | 热上下文强制提交比例 |
| `memory.checkpoint_enabled` | `MYCODINGAGENT_CHECKPOINT_ENABLED` | `true` | 启用工作区检查点 |
| `memory.reserved_reasoning_tokens` | `MYCODINGAGENT_RESERVED_REASONING_TOKENS` | `8000` | 为推理保留的 token 数 |
| `memory.reserved_output_tokens` | `MYCODINGAGENT_RESERVED_OUTPUT_TOKENS` | `4000` | 为输出保留的 token 数 |
| `memory.reserved_tool_tokens` | `MYCODINGAGENT_RESERVED_TOOL_TOKENS` | `12000` | 为工具调用保留的 token 数 |
| `memory.model_context_windows` | `MYCODINGAGENT_MODEL_CONTEXT_WINDOWS` | `{}` | 按模型覆盖默认上下文窗口的映射（JSON 字典） |

### 4.7 `sandbox` — 沙箱配置

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `sandbox.root` | `MYCODINGAGENT_SANDBOX_ROOT` | 当前工作目录 | 沙箱根目录 |
| `sandbox.max_output_chars` | `MYCODINGAGENT_MAX_OUTPUT_CHARS` | `10000` | 单次命令输出最大字符数 |
| `sandbox.workspace_lease_enabled` | `MYCODINGAGENT_WORKSPACE_LEASE_ENABLED` | `true` | 启用工作区租约锁 |

### 4.8 `docker` — Docker 容器配置

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `docker.image` | `MYCODINGAGENT_DOCKER_IMAGE` | `"mycodingagent-sandbox:py312"` | 沙箱镜像名称 |
| `docker.cpus` | `MYCODINGAGENT_DOCKER_CPUS` | `"2"` | CPU 限制 |
| `docker.memory` | `MYCODINGAGENT_DOCKER_MEMORY` | `"1g"` | 内存限制 |
| `docker.pids_limit` | `MYCODINGAGENT_DOCKER_PIDS_LIMIT` | `"256"` | 进程数限制 |
| `docker.default_timeout` | `MYCODINGAGENT_DOCKER_DEFAULT_TIMEOUT` | `120` | 默认命令超时（秒） |
| `docker.max_timeout` | `MYCODINGAGENT_DOCKER_MAX_TIMEOUT` | `600` | 最大命令超时（秒） |
| `docker.pull_timeout` | `MYCODINGAGENT_DOCKER_PULL_TIMEOUT` | `1800` | Docker pull/构建超时（秒） |

### 4.9 `network` — Runtime 托管网络

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `network.enabled` | `MYCODINGAGENT_NETWORK_ENABLED` | `true` | Agent 工具公网权限的启动默认值 |
| `network.upstream_proxy` | `MYCODINGAGENT_NETWORK_UPSTREAM_PROXY` | `"auto"` | 上游代理；`auto` 读取宿主 HTTP/HTTPS/ALL proxy，也可写 HTTP、HTTPS 或 SOCKS5 URL |
| `network.allow_domains` | `MYCODINGAGENT_NETWORK_ALLOW_DOMAINS` | `["*"]` | 允许访问的公网域名模式，环境变量使用 JSON 数组 |
| `network.deny_domains` | `MYCODINGAGENT_NETWORK_DENY_DOMAINS` | `[]` | 拒绝域名模式，优先级高于 allow |
| `network.connect_timeout` | `MYCODINGAGENT_NETWORK_CONNECT_TIMEOUT` | `10` | 建立目标或上游代理连接的超时秒数 |
| `network.idle_timeout` | `MYCODINGAGENT_NETWORK_IDLE_TIMEOUT` | `300` | 空闲隧道超时秒数 |
| `network.ca_bundle` | `MYCODINGAGENT_NETWORK_CA_BUNDLE` | `""` | HTTPS 上游代理使用的自定义 CA bundle 路径 |

每个 CLI 会话都会创建独立的 Docker internal 网络。Bash、Playwright 和联网 stdio MCP 不能直接访问
公网，只能连接绑定在当前网络网关上的 Runtime forward proxy。代理始终执行 allow/deny 规则并拒绝非公网 IP
字面量；direct 模式还会使用宿主 DNS 校验解析结果，配置上游代理时由上游负责域名解析，避免宿主 DNS 污染误判。
私网、链路本地、回环和云元数据地址默认拒绝，唯一的回环例外是当前会话工作区容器中的开发服务。

`upstream_proxy=auto` 可以复用只监听宿主 `127.0.0.1` 的代理，用户无需开启 Allow LAN。上游不可达时请求
fail closed，不会偷偷回退到直连。LLM、音频/视觉 API、镜像拉取和安装属于控制面，不受 `/network` 开关影响。

### 4.10 `search` — Tavily 网络搜索

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `search.tavily_api_key` | `MYCODINGAGENT_TAVILY_API_KEY`、`TAVILY_API_KEY` | `""` | Tavily API Key；JSON 值优先，其次两个环境变量 |

Tavily 使用 `.mycodingagent/mcp.json` 中的官方远程 Streamable HTTP Server。模板保留
`Authorization: Bearer ${TAVILY_API_KEY}`，真实 Key 只在首次连接时注入，不进入 MCP metadata cache、Runtime
Context、启动审批或日志。缺少 Key 时 Tavily Server 会在加载阶段被过滤，不进入能力推荐或工具发现。

启动过程不会连接或发现 Tavily 工具。用户请求与网络检索相关时，Capability Router 推荐该 Server，模型再通过
MCP discovery 获取 `tavily-search`、`tavily-extract`，随后按现有 discovery gate 调用。

### 4.11 `web_fetch` — 静态网页读取

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `web_fetch.enabled` | `MYCODINGAGENT_WEB_FETCH_ENABLED` | `true` | 是否向主模型注册 `FetchUrl` |
| `web_fetch.timeout` | `MYCODINGAGENT_WEB_FETCH_TIMEOUT` | `20` | 单次静态网页请求超时秒数 |
| `web_fetch.max_bytes` | `MYCODINGAGENT_WEB_FETCH_MAX_BYTES` | `2000000` | 最大流式下载字节数 |
| `web_fetch.max_chars` | `MYCODINGAGENT_WEB_FETCH_MAX_CHARS` | `50000` | 最大返回字符数 |
| `web_fetch.max_redirects` | `MYCODINGAGENT_WEB_FETCH_MAX_REDIRECTS` | `5` | 最大重定向次数；每跳重新校验目标地址 |

`FetchUrl` 不依赖 Tavily API Key，可读取明确 URL 的静态 HTML、JSON 和文本。动态页面、交互、截图或 UI 验证使用
Playwright。终端右下角显示 `网络访问（开启/关闭）`；`/network off` 关闭 Bash、FetchUrl、Playwright 和联网 MCP
的公网权限，但保留当前会话的 localhost 开发服务。`/network on|off <server>` 或无参数 `/network` 权限表可为单个
MCP Server 设置会话级覆盖，权限关闭时活动连接会立即断开。

### 4.12 `skills` — Skill 路由与检索

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `skills.builtin_root` | `MYCODINGAGENT_BUILTIN_SKILLS_ROOT` | 仓库 `skills/` | 内置 Skill 基础根目录；其下必须使用 `fixed/` 和 `Dynamic/` |
| `skills.user_root` | `MYCODINGAGENT_USER_SKILLS_ROOT` | `~/.mycodingagent/skills` | 用户 Skill 基础根目录；长期记忆批准的 Skill 写入其 `Dynamic/` |
| `skills.extra_roots` | `MYCODINGAGENT_EXTRA_SKILLS_ROOTS` | `[]` | 额外 Skill 基础根目录列表；每项同样使用 `fixed/` 和 `Dynamic/` |
| `skills.fixed_prompt_max_tokens` | `MYCODINGAGENT_FIXED_SKILL_PROMPT_MAX_TOKENS` | `2000` | 初始 system prompt 中 fixed Skill 卡片的近似 token 上限 |
| `skills.router_top_n` | `MYCODINGAGENT_SKILL_ROUTER_TOP_N` | `10` | Skill Router 推荐 Top-N |
| `skills.router_retrieval_top_k` | `MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_TOP_K` | `40` | 向量检索 Top-K |
| `skills.router_cache_top_k` | `MYCODINGAGENT_SKILL_ROUTER_CACHE_TOP_K` | `40` | 每级 LRFU 缓存参与路由的候选上限 |
| `skills.router_retrieval_min_ratio` | `MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_MIN_RATIO` | `0.4` | Dynamic Skill 推荐结果的最低检索候选比例 |
| `skills.router_user_weight` | `MYCODINGAGENT_SKILL_ROUTER_USER_WEIGHT` | `0.15` | 用户习惯权重 |
| `skills.router_session_weight` | `MYCODINGAGENT_SKILL_ROUTER_SESSION_WEIGHT` | `0.45` | 会话内权重 |
| `skills.router_retrieval_weight` | `MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_WEIGHT` | `0.40` | 语义检索权重 |
| `skills.lrfu_decay` | `MYCODINGAGENT_SKILL_LRFU_DECAY` | `0.95` | LRFU 衰减系数 |
| `skills.skill_call_reward` | `MYCODINGAGENT_SKILL_CALL_REWARD` | `10.0` | Skill 调用后的 LRFU 奖励 |
| `skills.session_activation_reward` | `MYCODINGAGENT_SKILL_SESSION_ACTIVATION_REWARD` | `0.3` | 会话内查看/激活 Skill 的 LRFU 奖励 |
| `skills.user_skill_cache_max_entries` | `MYCODINGAGENT_USER_SKILL_CACHE_MAX_ENTRIES` | `1000` | 用户级 Skill LRFU 缓存容量 |
| `skills.session_skill_cache_max_entries` | `MYCODINGAGENT_SESSION_SKILL_CACHE_MAX_ENTRIES` | `200` | 会话级 Skill LRFU 缓存容量 |
| `skills.vector_sync_batch_size` | `MYCODINGAGENT_SKILL_VECTOR_SYNC_BATCH_SIZE` | `2` | 向量同步批大小 |
| `skills.vector_sync_max_retries` | `MYCODINGAGENT_SKILL_VECTOR_SYNC_MAX_RETRIES` | `3` | 向量同步最大重试 |

Skill 根目录不兼容旧的平铺结构。`fixed/` 中的 Skill 仅以 `skill_name + name + description` 卡片进入初始
system prompt，不参与检索或 LRFU；`Dynamic/` 中的 Skill 参与检索、向量索引和 LRFU。启动时会比较 Dynamic
目录的 `name + description` 指纹，只有发生变化才调用总结模型并更新本地摘要缓存。摘要仅描述能力覆盖范围，
用于让主模型在需求完全不属于这些类别时跳过无效 Skill 检索。

### 4.13 `embedding` — 嵌入模型

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `embedding.provider` | `MYCODINGAGENT_EMBEDDING_PROVIDER` | `"http"` | 嵌入服务类型（`http` / `local` / `hash`） |
| `embedding.model` | `MYCODINGAGENT_EMBEDDING_MODEL` | `"bge-m3"` | 嵌入模型名称 |
| `embedding.endpoint` | `MYCODINGAGENT_EMBEDDING_ENDPOINT` | `"http://127.0.0.1:11434/api/embed"` | 嵌入服务端点 |
| `embedding.api_format` | `MYCODINGAGENT_EMBEDDING_API_FORMAT` | `"ollama"` | HTTP API 格式（`ollama` / `openai` / `dashscope`） |
| **`embedding.api_key`** | **`MYCODINGAGENT_EMBEDDING_API_KEY`** | `""` | **嵌入服务 API 密钥（隐私字段）** |
| `embedding.timeout` | `MYCODINGAGENT_EMBEDDING_TIMEOUT` | `300.0` | 单批嵌入服务请求超时（秒） |
| `embedding.dimension` | `MYCODINGAGENT_EMBEDDING_DIMENSION` | `1024` | 向量维度 |
| `embedding.batch_size` | `MYCODINGAGENT_EMBEDDING_BATCH_SIZE` | `16` | 嵌入批大小 |
| `embedding.download_timeout` | `MYCODINGAGENT_EMBEDDING_DOWNLOAD_TIMEOUT` | `900.0` | 本地 BGE 模型下载超时（秒） |
| `embedding.fallback_to_hash` | `MYCODINGAGENT_EMBEDDING_FALLBACK_TO_HASH` | `false` | 本地嵌入不可用时回退到哈希 |

### 4.14 `milvus` — Milvus 向量库

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `milvus.enabled` | `MYCODINGAGENT_MILVUS_ENABLED` | `true` | 是否启用 Milvus |
| `milvus.host` | `MYCODINGAGENT_MILVUS_HOST` | `"127.0.0.1"` | Milvus 主机地址 |
| `milvus.port` | `MYCODINGAGENT_MILVUS_PORT` | `"19530"` | Milvus 端口 |
| **`milvus.token`** | **`MYCODINGAGENT_MILVUS_TOKEN`** | `""` | **Milvus 认证令牌（隐私字段）** |
| `milvus.collection` | `MYCODINGAGENT_MILVUS_COLLECTION` | `"mycodingagent_skills"` | 集合名称 |
| `milvus.dense_index_type` | `MYCODINGAGENT_MILVUS_DENSE_INDEX_TYPE` | `"HNSW"` | dense 向量索引类型 |
| `milvus.dense_metric_type` | `MYCODINGAGENT_MILVUS_DENSE_METRIC_TYPE` | `"COSINE"` | dense 向量距离度量 |
| `milvus.hnsw_m` | `MYCODINGAGENT_MILVUS_HNSW_M` | `16` | HNSW 建索引连接数 |
| `milvus.hnsw_ef_construction` | `MYCODINGAGENT_MILVUS_HNSW_EF_CONSTRUCTION` | `200` | HNSW 建索引搜索宽度 |
| `milvus.hnsw_ef` | `MYCODINGAGENT_MILVUS_HNSW_EF` | `64` | HNSW 查询搜索宽度 |
| `milvus.sparse_index_type` | `MYCODINGAGENT_MILVUS_SPARSE_INDEX_TYPE` | `"SPARSE_INVERTED_INDEX"` | BM25 稀疏向量索引类型 |
| `milvus.sparse_metric_type` | `MYCODINGAGENT_MILVUS_SPARSE_METRIC_TYPE` | `"BM25"` | BM25 稀疏向量度量 |
| `milvus.sparse_inverted_index_algo` | `MYCODINGAGENT_MILVUS_SPARSE_ALGO` | `"DAAT_MAXSCORE"` | BM25 稀疏倒排索引算法 |
| `milvus.rrf_k` | `MYCODINGAGENT_MILVUS_RRF_K` | `60` | RRF 融合 K 值 |

### 4.15 `mcp` — MCP Server

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `mcp.enabled` | `MYCODINGAGENT_MCP_ENABLED` | `true` | 是否启用 MCP |
| `mcp.project_config_path` | `MYCODINGAGENT_MCP_PROJECT_CONFIG` | `.mycodingagent/mcp.json` | 项目级 MCP 配置路径，默认相对当前工作目录 |
| `mcp.user_config_path` | `MYCODINGAGENT_MCP_USER_CONFIG` | `~/.mycodingagent/mcp.json` | 用户级 MCP 配置路径 |
| `mcp.reconnect_server_step` | `MYCODINGAGENT_RECONNECT_MCP_SERVER_STEP` | `10` | 后台重连间隔（秒） |

---

## 5. 完整配置示例

完整 JSON 模板见仓库中 `.mycodingagent/config.example.json`，首次启动时会复制为 `~/.mycodingagent/config.json`。
首次启动会自动把 `.mycodingagent/mcp.example.json` 复制为用户级 `~/.mycodingagent/mcp.json`，并同步说明到 `~/.mycodingagent/MCP.md`。项目级覆盖配置仍可放在当前工作目录的 `.mycodingagent/mcp.json`。

---

## 6. 环境变量速查表

以下列出所有环境变量及其对应 JSON 路径（环境变量在 JSON 文件未设置时生效）：

| 环境变量 | JSON 路径 | 类型 |
|----------|-----------|------|
| `MYCODINGAGENT_MAX_TOOL_ROUNDS` | `client.max_tool_rounds` | int |
| `MYCODINGAGENT_APPROVAL_MODE` | `approval.mode` | string |
| `MYCODINGAGENT_API_MAX_RETRIES` | `client.api_max_retries` | int |
| `MYCODINGAGENT_MODEL_PROVIDER_DEEPSEEK_API` / `DEEPSEEK_API_KEY` | `model.providers.deepseek.api` | string |
| `MYCODINGAGENT_MODEL_PROVIDER_DEEPSEEK_BASE_URL` / `DEEPSEEK_BASE_URL` | `model.providers.deepseek.base_url` | string |
| `MYCODINGAGENT_MODEL_ACTIVE` | `model.active` | string |
| `MYCODINGAGENT_MODEL_AUDIO_PROVIDER` | `model.audio.provider` | string |
| `MYCODINGAGENT_MODEL_AUDIO_MODEL` | `model.audio.model` | string |
| `MYCODINGAGENT_MODEL_VISION_PROVIDER` | `model.vision.provider` | string |
| `MYCODINGAGENT_MODEL_VISION_MODEL` | `model.vision.model` | string |
| `MYCODINGAGENT_DEBUG` | `client.debug` | bool |
| `MYCODINGAGENT_MULTI_AGENT_MAX_AGENT_ROUNDS` | `multi_agent.max_agent_rounds` | int |
| `MYCODINGAGENT_MULTI_AGENT_MAX_PARALLEL_TASKS` | `multi_agent.max_parallel_tasks` | int |
| `MYCODINGAGENT_LONG_TERM_MEMORY_ENABLED` | `long_term_memory.enabled` | bool |
| `MYCODINGAGENT_MEMORY_ENABLED` | `memory.enabled` | bool |
| `MYCODINGAGENT_STATE_DIR` | `memory.state_dir` | path |
| `MYCODINGAGENT_MEMORY_DB_PATH` | `memory.db_path` | path |
| `MYCODINGAGENT_DEFAULT_WORK_MODE` | `memory.default_work_mode` | string |
| `MYCODINGAGENT_CHECKPOINT_ENABLED` | `memory.checkpoint_enabled` | bool |
| `MYCODINGAGENT_SANDBOX_ROOT` | `sandbox.root` | path |
| `MYCODINGAGENT_DOCKER_IMAGE` | `docker.image` | string |
| `MYCODINGAGENT_DOCKER_CPUS` | `docker.cpus` | string |
| `MYCODINGAGENT_DOCKER_MEMORY` | `docker.memory` | string |
| `MYCODINGAGENT_NETWORK_ENABLED` | `network.enabled` | bool |
| `MYCODINGAGENT_NETWORK_UPSTREAM_PROXY` | `network.upstream_proxy` | string |
| `MYCODINGAGENT_NETWORK_ALLOW_DOMAINS` | `network.allow_domains` | JSON array |
| `MYCODINGAGENT_NETWORK_DENY_DOMAINS` | `network.deny_domains` | JSON array |
| `MYCODINGAGENT_NETWORK_CONNECT_TIMEOUT` | `network.connect_timeout` | float |
| `MYCODINGAGENT_NETWORK_IDLE_TIMEOUT` | `network.idle_timeout` | float |
| `MYCODINGAGENT_NETWORK_CA_BUNDLE` | `network.ca_bundle` | path |
| `MYCODINGAGENT_TAVILY_API_KEY` | `search.tavily_api_key` | secret string |
| `TAVILY_API_KEY` | `search.tavily_api_key` | secret string |
| `MYCODINGAGENT_WEB_FETCH_ENABLED` | `web_fetch.enabled` | bool |
| `MYCODINGAGENT_WEB_FETCH_TIMEOUT` | `web_fetch.timeout` | float |
| `MYCODINGAGENT_WEB_FETCH_MAX_BYTES` | `web_fetch.max_bytes` | int |
| `MYCODINGAGENT_WEB_FETCH_MAX_CHARS` | `web_fetch.max_chars` | int |
| `MYCODINGAGENT_WEB_FETCH_MAX_REDIRECTS` | `web_fetch.max_redirects` | int |
| `MYCODINGAGENT_EMBEDDING_PROVIDER` | `embedding.provider` | string |
| `MYCODINGAGENT_EMBEDDING_MODEL` | `embedding.model` | string |
| `MYCODINGAGENT_EMBEDDING_API_KEY` | `embedding.api_key` | string |
| `MYCODINGAGENT_MILVUS_ENABLED` | `milvus.enabled` | bool |
| `MYCODINGAGENT_MILVUS_HOST` | `milvus.host` | string |
| `MYCODINGAGENT_MILVUS_TOKEN` | `milvus.token` | string |
| `MYCODINGAGENT_MILVUS_DENSE_INDEX_TYPE` | `milvus.dense_index_type` | string |
| `MYCODINGAGENT_MILVUS_DENSE_METRIC_TYPE` | `milvus.dense_metric_type` | string |
| `MYCODINGAGENT_MILVUS_HNSW_M` | `milvus.hnsw_m` | int |
| `MYCODINGAGENT_MILVUS_HNSW_EF_CONSTRUCTION` | `milvus.hnsw_ef_construction` | int |
| `MYCODINGAGENT_MILVUS_HNSW_EF` | `milvus.hnsw_ef` | int |
| `MYCODINGAGENT_MILVUS_SPARSE_INDEX_TYPE` | `milvus.sparse_index_type` | string |
| `MYCODINGAGENT_MILVUS_SPARSE_METRIC_TYPE` | `milvus.sparse_metric_type` | string |
| `MYCODINGAGENT_MILVUS_SPARSE_ALGO` | `milvus.sparse_inverted_index_algo` | string |
| `MYCODINGAGENT_MCP_ENABLED` | `mcp.enabled` | bool |
| `MYCODINGAGENT_MCP_USER_CONFIG` | `mcp.user_config_path` | path |

项目专属状态不再写入用户目录：会话、检查点、项目事实、代码索引、项目图谱、MCP metadata cache 和多智能体状态位于 `<workspace>/.mycodingagent/state/`，删除项目目录会一并删除这些数据。用户画像、偏好、工作流/Skill 候选仍保留在 `memory.db_path` 指向的全局库；用户批准沉淀后的正式 Skill 位于 `skills.user_root/Dynamic/`。启动过程不会迁移旧目录或修补旧 SQLite schema；不兼容时请删除对应数据库后由当前版本重建。

---

## 7. 典型场景配置

### 7.1 仅需改 API 密钥（最小改动）

编辑 `~/.mycodingagent/config.json`：
```json
{
  "model": {
    "active": "main",
    "providers": {
      "deepseek": {"api": "sk-..."}
    }
  }
}
```
其他字段全部使用默认值。

### 7.2 使用本地 Ollama Embedding

```json
{
  "model": {
    "active": "main",
    "providers": {
      "deepseek": {"api": "sk-..."}
    },
    "profiles": {
      "main": {"provider": "deepseek", "model": "deepseek-v4-pro"}
    }
  },
  "embedding": {
    "provider": "http",
    "model": "bge-m3",
    "endpoint": "http://127.0.0.1:11434/api/embed",
    "api_format": "ollama",
    "dimension": 1024
  }
}
```

### 7.3 使用 OpenAI 兼容 Embedding 服务

```json
{
  "model": {
    "active": "main",
    "providers": {
      "openai": {"api": "sk-..."}
    },
    "profiles": {
      "main": {"provider": "openai", "model": "gpt-5"}
    }
  },
  "embedding": {
    "provider": "openai",
    "model": "text-embedding-3-small",
    "endpoint": "https://api.openai.com/v1/embeddings",
    "api_format": "openai",
    "api_key": "sk-...",
    "dimension": 1536
  }
}
```

### 7.4 自建 Milvus 向量库

```bash
docker compose -f Milvus/docker-compose.yml up -d
```

根目录的 `Milvus/docker-compose.yml` 启动一个单机 Milvus，`config.json` 的默认 `milvus` 配置已指向 `127.0.0.1:19530`，无需额外配置。

### 7.5 自由组合模型

```json
{
  "model": {
    "active": "main",
    "providers": {
      "deepseek": {"api": "sk-..."}
    },
    "profiles": {
      "main": {"provider": "deepseek", "model": "deepseek-v4-pro"},
      "memory_search": {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "reasoning": {"thinking": "disabled"}
      }
    },
    "long_term_memory": {
      "storage": "main",
      "search": "memory_search"
    }
  }
}
```

- `model.active`：Agent 对话主模型 profile
- `model.providers.<provider>.api`：同一厂商下所有 profile 共用的 API Key
- `model.long_term_memory.storage`：长期记忆存储模型 profile
- `model.long_term_memory.search`：长期记忆检索模型 profile
- `embedding.model`：向量嵌入模型（独立于对话模型）

### 7.6 启用网页搜索与浏览器自动化

```bash
bash scripts/install.sh --with-web-tools
```

安装脚本只预拉取 Playwright MCP 镜像。Tavily 是远程 MCP，不需要本地镜像或会话搜索容器。启用搜索时填写：

```json
{
  "network": {
    "enabled": true,
    "upstream_proxy": "auto",
    "allow_domains": ["*"],
    "deny_domains": []
  },
  "search": {
    "tavily_api_key": "tvly-..."
  }
}
```

真实 Key 只写入 `~/.mycodingagent/config.json`，不要提交到项目配置。未提供 Key 时 Tavily 不会出现在 Agent 的 MCP
能力中，`FetchUrl` 和 Playwright 仍按各自配置提供。

Playwright 是默认启用的内置浏览器工具；首次使用自动拉取镜像，后续复用 Docker 本地缓存，不请求 MCP Server
启动审批。完整 Playwright MCP 权限和容器字段见 `docs/mcp.md`。

Runtime 在项目加载阶段自动创建 Bash 工作区容器和专用 internal Docker network，Playwright 自动加入同一网络。
项目服务需监听 `0.0.0.0`，浏览器可通过 `http://localhost:<port>` 访问，Runtime 自动映射到本会话容器且不暴露
宿主机端口；`http://mycodingagent-devserver:<port>` 仍可显式使用。Bash 参数
`is_persistent_command=true` 用于开发服务器和 watcher：Runtime 将命令放入独立进程组，确认短时间内未退出后返回，
日志写入 `.mycodingagent/artifacts/services/<runtime-id>/`。普通命令保持 `false` 并等待退出。Esc 和普通命令超时只清理
当前前台命令。Agent 退出时先同步保存最终消息、停止文件监听并释放工作区租约；持久进程、工作区容器、
Playwright/MCP 容器和专用网络由按 runtime label 隔离的后台进程清理，CLI 不等待 Docker 删除，也不向模型提供容器
管理工具。本地连接和可取消任务并行关闭且有 2 秒总上限；超时信息只在 `client.debug=true` 时显示。

---

## 8. LSP 配置

语言服务器命令通过环境变量覆盖，格式为：

```bash
export MYCODINGAGENT_LSP_<LANGUAGE>_COMMAND="启动命令"
```

示例：

```bash
export MYCODINGAGENT_LSP_PYTHON_COMMAND="pyright-langserver --stdio"
```

LSP 进程运行在宿主机上，需在 `PATH` 中可找到对应可执行程序。

---

## 9. 常见问题

**Q: 启动时提示"未检测到必要推理模型配置"？**

A: 编辑 `~/.mycodingagent/config.json`，确认 `model.active` 指向存在的 profile，并在该 profile 的 `provider`、`model` 以及对应 `model.providers.<provider>.api` 中填入有效值。

**Q: 配置文件格式错误怎么办？**

A: 启动时会自动检测 JSON 格式，如果格式错误会先备份为 `config.json.broken.<timestamp>`，再重建模板。你也可以手动删除 `~/.mycodingagent/config.json`，下次启动会自动重建。

**Q: 如何查看当前生效的配置？**

A: 所有配置项、默认值和环境变量名详见本文档。你编辑 `~/.mycodingagent/config.json` 的内容即为生效配置；环境变量只在 JSON 字段缺失或为空字符串时生效。

**Q: 旧版本的 YAML 配置还能用吗？**

A: 不能。v2 起统一使用 `~/.mycodingagent/config.json`。如果你有旧的 YAML 配置，请对照本文档手动迁移到 JSON 格式。
