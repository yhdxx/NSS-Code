# myCodingAgent 配置指南

> 本文件会在每次 `myAgent` 启动时自动复制到 `~/.mycodingagent/README.md`，方便离线查阅。

---

## 1. 配置方式

myCodingAgent 所有运行配置通过以下**两个来源**读取（优先级从高到低）：

| 优先级 | 来源 | 说明 |
|--------|------|------|
| **1（最高）** | `~/.mycodingagent/config.json` | 用户级 JSON 配置文件 |
| **2** | 环境变量 | JSON 字段缺失或为空字符串时生效，与旧版本兼容 |

仓库内 `.mycodingagent/config.example.json` 是首次启动时复制到用户目录的全量模板；
`.mycodingagent/config.example.yaml` 仅供旧配置迁移参考。两者都不参与运行时配置读取。

---

## 2. 快速开始

```bash
# 首次启动会自动创建 ~/.mycodingagent/config.json 全量模板
# 每次启动会同步 ~/.mycodingagent/README.md
myAgent

# 编辑配置文件
nano ~/.mycodingagent/config.json

# 至少需要填入 API 密钥
# 找到 "api" -> "deepseek_api_key"，填入你的密钥

# 或者通过环境变量配置（JSON 优先）
export DEEPSEEK_API_KEY="sk-..."
myAgent
```

---

## 3. 配置结构总览

`~/.mycodingagent/config.json` 包含以下 11 个顶层模块：

| Key | 说明 |
|-----|------|
| `api` | 主模型 API 配置（密钥、地址、模型名称） |
| `client` | LLM 客户端行为（重试、调试、展示） |
| `multi_agent` | 多智能体并发与轮次限制 |
| `long_term_memory` | 长期记忆存储与查询模型配置 |
| `memory` | 会话持久化、上下文虚拟化、检查点 |
| `sandbox` | Docker 沙箱工作区设置 |
| `docker` | Docker 容器资源限制 |
| `skills` | Skill 发现、索引、路由、LRFU |
| `embedding` | 嵌入模型配置（provider/model/api_key 等） |
| `milvus` | Milvus 向量数据库连接 |
| `mcp` | MCP Server 连接与权限 |

---

## 4. 各模块配置说明

### 4.1 `api` — 主模型配置

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `api.deepseek_api_key` | `DEEPSEEK_API_KEY` | `""` | **API 密钥（必填）** |
| `api.base_url` | `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API 服务地址 |
| `api.model` | `DEEPSEEK_MODEL` | `deepseek-v4-pro` | 对话模型名称 |

```json
{
  "api": {
    "deepseek_api_key": "sk-...",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-pro"
  }
}
```

### 4.2 `client` — LLM 客户端

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `client.max_tool_rounds` | `MYCODINGAGENT_MAX_TOOL_ROUNDS` | `50` | 单次请求最多工具调用轮数 |
| `client.api_max_retries` | `MYCODINGAGENT_API_MAX_RETRIES` | `3` | API 调用失败重试次数 |
| `client.api_retry_base_delay` | `MYCODINGAGENT_API_RETRY_BASE_DELAY` | `1.0` | 重试退避基础延迟（秒） |
| `client.debug` | `DEBUG` / `MYCODINGAGENT_DEBUG` | `false` | 调试模式 |
| `client.legacy_system_prompt` | `MYCODINGAGENT_LEGACY_SYSTEM_PROMPT` | `false` | 使用旧版系统提示词 |
| `client.step_token` | `STEP_TOKEN` | `true` | 显示步骤 token 计数 |
| `client.round_token` | `ROUND_TOKEN` | `true` | 显示轮次 token 计数 |
| `client.conversation_token` | `CONVERSATION_TOKEN` | `true` | 显示会话 token 计数 |

### 4.3 `multi_agent` — 多智能体

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `multi_agent.max_agent_rounds` | `MYCODINGAGENT_MULTI_AGENT_MAX_AGENT_ROUNDS` | `50` | 多智能体最大轮次 |
| `multi_agent.max_parallel_tasks` | `MYCODINGAGENT_MULTI_AGENT_MAX_PARALLEL_TASKS` | `5` | 最大并发任务数 |

### 4.4 `long_term_memory` — 长期记忆

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `long_term_memory.enabled` | `MYCODINGAGENT_LONG_TERM_MEMORY_ENABLED` | `true` | 是否启用长期记忆 |
| `long_term_memory.storage_model` | `MYCODINGAGENT_LONG_TERM_MEMORY_STORAGE_MODEL` | `""` | 记忆存储模型（空则跟随 `api.model`） |
| `long_term_memory.query_model` | `MYCODINGAGENT_LONG_TERM_MEMORY_QUERY_MODEL` | `""` | 记忆检索模型（空则用 `deepseek-v4-flash`） |
| `long_term_memory.query_recent_turns` | `MYCODINGAGENT_LONG_TERM_MEMORY_QUERY_RECENT_TURNS` | `10` | 查询时携带的最近对话轮数 |
| `long_term_memory.max_memories` | `MYCODINGAGENT_LONG_TERM_MEMORY_MAX_MEMORIES` | `50` | 上下文注入最多记忆条数 |
| `long_term_memory.max_workflow_candidates` | `MYCODINGAGENT_LONG_TERM_MEMORY_MAX_WORKFLOW_CANDIDATES` | `5` | 工作流候选最多条数 |
| `long_term_memory.max_skill_candidates` | `MYCODINGAGENT_LONG_TERM_MEMORY_MAX_SKILL_CANDIDATES` | `3` | Skill 候选最多条数 |
| `long_term_memory.startup_backfill_enabled` | `MYCODINGAGENT_LONG_TERM_MEMORY_STARTUP_BACKFILL_ENABLED` | `true` | 启动时异步回填未完成抽取 |

### 4.5 `memory` — 会话与上下文管理

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `memory.enabled` | `MYCODINGAGENT_MEMORY_ENABLED` | `true` | 启用会话持久化 |
| `memory.default_work_mode` | `MYCODINGAGENT_DEFAULT_WORK_MODE` | `"general"` | 默认工作模式（`general` / `code`） |
| `memory.default_context_window` | `MYCODINGAGENT_MODEL_CONTEXT_WINDOW` | `128000` | 默认上下文窗口大小 |
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
| `memory.model_context_windows` | `MYCODINGAGENT_MODEL_CONTEXT_WINDOWS` | `{"deepseek-v4-flash": 1000000}` | 各模型上下文窗口映射（JSON 字典） |

### 4.6 `sandbox` — 沙箱配置

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `sandbox.root` | `MYCODINGAGENT_SANDBOX_ROOT` | 当前工作目录 | 沙箱根目录 |
| `sandbox.max_output_chars` | `MYCODINGAGENT_MAX_OUTPUT_CHARS` | `10000` | 单次命令输出最大字符数 |
| `sandbox.workspace_lease_enabled` | `MYCODINGAGENT_WORKSPACE_LEASE_ENABLED` | `true` | 启用工作区租约锁 |

### 4.7 `docker` — Docker 容器配置

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `docker.image` | `MYCODINGAGENT_DOCKER_IMAGE` | `"mycodingagent-sandbox:py312"` | 沙箱镜像名称 |
| `docker.network` | `MYCODINGAGENT_DOCKER_NETWORK` | `"bridge"` | Docker 网络模式 |
| `docker.cpus` | `MYCODINGAGENT_DOCKER_CPUS` | `"2"` | CPU 限制 |
| `docker.memory` | `MYCODINGAGENT_DOCKER_MEMORY` | `"1g"` | 内存限制 |
| `docker.pids_limit` | `MYCODINGAGENT_DOCKER_PIDS_LIMIT` | `"256"` | 进程数限制 |
| `docker.default_timeout` | `MYCODINGAGENT_DOCKER_DEFAULT_TIMEOUT` | `120` | 默认命令超时（秒） |
| `docker.max_timeout` | `MYCODINGAGENT_DOCKER_MAX_TIMEOUT` | `600` | 最大命令超时（秒） |
| `docker.pull_timeout` | `MYCODINGAGENT_DOCKER_PULL_TIMEOUT` | `300` | Docker pull 超时（秒） |

### 4.8 `skills` — Skill 路由与检索

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `skills.default_tool_names` | `MYCODINGAGENT_DEFAULT_SKILLS` | `["coding-standards"]` | 默认启用的 Skill |
| `skills.router_top_n` | `MYCODINGAGENT_SKILL_ROUTER_TOP_N` | `10` | Skill Router 推荐 Top-N |
| `skills.router_retrieval_top_k` | `MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_TOP_K` | `40` | 向量检索 Top-K |
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

### 4.9 `embedding` — 嵌入模型

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `embedding.provider` | `MYCODINGAGENT_EMBEDDING_PROVIDER` | `"bge_http"` | 嵌入服务类型（`bge_http` / `openai` / `dashscope`） |
| `embedding.model` | `MYCODINGAGENT_EMBEDDING_MODEL` | `"bge-m3"` | 嵌入模型名称 |
| `embedding.endpoint` | `MYCODINGAGENT_EMBEDDING_ENDPOINT` | `"http://127.0.0.1:11434/api/embed"` | 嵌入服务端点 |
| `embedding.api_format` | `MYCODINGAGENT_EMBEDDING_API_FORMAT` | `"ollama"` | API 格式（自动根据 provider 推断） |
| **`embedding.api_key`** | **`MYCODINGAGENT_EMBEDDING_API_KEY`** | `""` | **嵌入服务 API 密钥（隐私字段）** |
| `embedding.dimension` | `MYCODINGAGENT_EMBEDDING_DIMENSION` | `1024` | 向量维度 |
| `embedding.batch_size` | `MYCODINGAGENT_EMBEDDING_BATCH_SIZE` | `16` | 嵌入批大小 |
| `embedding.fallback_to_hash` | `MYCODINGAGENT_BGE_FALLBACK_TO_HASH` | `false` | 嵌入不可用时回退到哈希 |

### 4.10 `milvus` — Milvus 向量库

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `milvus.enabled` | `MYCODINGAGENT_MILVUS_ENABLED` | `true` | 是否启用 Milvus |
| `milvus.host` | `MYCODINGAGENT_MILVUS_HOST` | `"127.0.0.1"` | Milvus 主机地址 |
| `milvus.port` | `MYCODINGAGENT_MILVUS_PORT` | `"19530"` | Milvus 端口 |
| **`milvus.token`** | **`MYCODINGAGENT_MILVUS_TOKEN`** | `""` | **Milvus 认证令牌（隐私字段）** |
| `milvus.collection` | `MYCODINGAGENT_MILVUS_COLLECTION` | `"mycodingagent_skills"` | 集合名称 |
| `milvus.rrf_k` | `MYCODINGAGENT_MILVUS_RRF_K` | `60` | RRF 融合 K 值 |

### 4.11 `mcp` — MCP Server

| JSON 路径 | 环境变量 | 默认值 | 说明 |
|-----------|----------|--------|------|
| `mcp.enabled` | `MYCODINGAGENT_MCP_ENABLED` | `true` | 是否启用 MCP |
| `mcp.project_config_path` | `MYCODINGAGENT_MCP_PROJECT_CONFIG` | `.mycodingagent/mcp.json` | 项目级 MCP 配置路径，默认相对当前工作目录 |
| `mcp.user_config_path` | `MYCODINGAGENT_MCP_USER_CONFIG` | `~/.config/myCodingAgent/mcp.json` | 用户级 MCP 配置路径 |
| `mcp.reconnect_server_step` | `MYCODINGAGENT_RECONNECT_MCP_SERVER_STEP` | `10` | 后台重连间隔（秒） |

---

## 5. 完整配置示例

完整 JSON 模板见仓库中 `.mycodingagent/config.example.json`，首次启动时会复制为 `~/.mycodingagent/config.json`。
仓库内 MCP 配置只保留 `.mycodingagent/mcp.example.json` 模板；如需启用 MCP，请复制到当前工作目录的 `.mycodingagent/mcp.json` 或用户级 `~/.config/myCodingAgent/mcp.json`。

---

## 6. 环境变量速查表

以下列出所有环境变量及其对应 JSON 路径（环境变量在 JSON 文件未设置时生效）：

| 环境变量 | JSON 路径 | 类型 |
|----------|-----------|------|
| `DEEPSEEK_API_KEY` | `api.deepseek_api_key` | string |
| `DEEPSEEK_BASE_URL` | `api.base_url` | string |
| `DEEPSEEK_MODEL` | `api.model` | string |
| `MYCODINGAGENT_MAX_TOOL_ROUNDS` | `client.max_tool_rounds` | int |
| `MYCODINGAGENT_API_MAX_RETRIES` | `client.api_max_retries` | int |
| `DEBUG` | `client.debug` | bool |
| `MYCODINGAGENT_LEGACY_SYSTEM_PROMPT` | `client.legacy_system_prompt` | bool |
| `MYCODINGAGENT_MULTI_AGENT_MAX_AGENT_ROUNDS` | `multi_agent.max_agent_rounds` | int |
| `MYCODINGAGENT_MULTI_AGENT_MAX_PARALLEL_TASKS` | `multi_agent.max_parallel_tasks` | int |
| `MYCODINGAGENT_LONG_TERM_MEMORY_ENABLED` | `long_term_memory.enabled` | bool |
| `MYCODINGAGENT_LONG_TERM_MEMORY_STORAGE_MODEL` | `long_term_memory.storage_model` | string |
| `MYCODINGAGENT_LONG_TERM_MEMORY_QUERY_MODEL` | `long_term_memory.query_model` | string |
| `MYCODINGAGENT_MEMORY_ENABLED` | `memory.enabled` | bool |
| `MYCODINGAGENT_DEFAULT_WORK_MODE` | `memory.default_work_mode` | string |
| `MYCODINGAGENT_CHECKPOINT_ENABLED` | `memory.checkpoint_enabled` | bool |
| `MYCODINGAGENT_SANDBOX_ROOT` | `sandbox.root` | path |
| `MYCODINGAGENT_DOCKER_IMAGE` | `docker.image` | string |
| `MYCODINGAGENT_DOCKER_CPUS` | `docker.cpus` | string |
| `MYCODINGAGENT_DOCKER_MEMORY` | `docker.memory` | string |
| `MYCODINGAGENT_EMBEDDING_PROVIDER` | `embedding.provider` | string |
| `MYCODINGAGENT_EMBEDDING_MODEL` | `embedding.model` | string |
| `MYCODINGAGENT_EMBEDDING_API_KEY` | `embedding.api_key` | string |
| `MYCODINGAGENT_MILVUS_ENABLED` | `milvus.enabled` | bool |
| `MYCODINGAGENT_MILVUS_HOST` | `milvus.host` | string |
| `MYCODINGAGENT_MILVUS_TOKEN` | `milvus.token` | string |
| `MYCODINGAGENT_MCP_ENABLED` | `mcp.enabled` | bool |

---

## 7. 典型场景配置

### 7.1 仅需改 API 密钥（最小改动）

编辑 `~/.mycodingagent/config.json`：
```json
{
  "api": {
    "deepseek_api_key": "sk-..."
  }
}
```
其他字段全部使用默认值。

### 7.2 使用本地 Ollama Embedding

```json
{
  "api": {
    "deepseek_api_key": "sk-..."
  },
  "embedding": {
    "provider": "bge_http",
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
  "api": {
    "deepseek_api_key": "sk-..."
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
  "api": {
    "deepseek_api_key": "sk-...",
    "model": "deepseek-v4-pro"
  },
  "long_term_memory": {
    "storage_model": "deepseek-v4-pro",
    "query_model": "deepseek-v4-flash"
  }
}
```

- `api.model`：Agent 对话主模型
- `long_term_memory.storage_model`：长期记忆存储模型（空则跟随 `api.model`）
- `long_term_memory.query_model`：长期记忆检索模型（空则用 `deepseek-v4-flash`）
- `embedding.model`：向量嵌入模型（独立于对话模型）

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

**Q: 启动时提示"未检测到 API 密钥"？**

A: 编辑 `~/.mycodingagent/config.json`，在 `api.deepseek_api_key` 填入密钥，或设置环境变量 `export DEEPSEEK_API_KEY="sk-..."`。

**Q: 配置文件格式错误怎么办？**

A: 启动时会自动检测 JSON 格式，如果格式错误会先备份为 `config.json.broken.<timestamp>`，再重建模板。你也可以手动删除 `~/.mycodingagent/config.json`，下次启动会自动重建。

**Q: 如何查看当前生效的配置？**

A: 所有配置项、默认值和环境变量名详见本文档。你编辑 `~/.mycodingagent/config.json` 的内容即为生效配置；环境变量只在 JSON 字段缺失或为空字符串时生效。

**Q: 旧版本的 YAML 配置还能用吗？**

A: 不能。v2 起统一使用 `~/.mycodingagent/config.json`。如果你有旧的 YAML 配置，请对照本文档手动迁移到 JSON 格式。
