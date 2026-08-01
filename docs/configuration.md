# 配置指南

本文集中说明 myCodingAgent 的配置文件、环境变量、Embedding、Milvus 向量库和 MCP Server 配置。所有密钥都建议放在环境变量或用户级配置中，不要提交到仓库。

## 配置加载顺序

运行时先读取代码内置默认值，再依次合并配置文件，最后用环境变量覆盖。后加载的同名字段覆盖前者。

1. `~/.config/myCodingAgent/config.yaml`
2. Agent 安装目录 `.mycodingagent/config.yaml`
3. 设置 `MYCODINGAGENT_LOAD_WORKSPACE_CONFIG=1` 时，当前工作区 `.mycodingagent/config.yaml`
4. `MYCODINGAGENT_CONFIG` 指定的一个或多个 YAML/JSON 文件，多个路径用系统路径分隔符连接
5. 环境变量

推荐做法：

```bash
mkdir -p ~/.config/myCodingAgent
cp .mycodingagent/config.example.yaml ~/.config/myCodingAgent/config.yaml
cp .mycodingagent/mcp.example.json ~/.config/myCodingAgent/mcp.json
```

## 最小可用配置

必须先配置主模型 API 密钥。当前客户端使用 OpenAI-compatible SDK，请用下面三个变量控制主模型：

| 用途 | 环境变量 | 配置文件字段 | 默认值 |
| --- | --- | --- | --- |
| 主模型密钥 | `DEEPSEEK_API_KEY` | `api.deepseek_api_key` | 空 |
| 主模型地址 | `DEEPSEEK_BASE_URL` | `api.base_url` | `https://api.deepseek.com` |
| 主模型名称 | `DEEPSEEK_MODEL` | `api.model` | `deepseek-v4-pro` |

示例：

```bash
export DEEPSEEK_API_KEY="sk-..."
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-v4-pro"
```

也可以写入 `~/.config/myCodingAgent/config.yaml`：

```yaml
api:
  deepseek_api_key: "sk-..."
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-pro"
```

## 按场景直接配置

下面这些场景可以直接复制。没有特别说明时，YAML 放到 `~/.config/myCodingAgent/config.yaml`，JSON 放到 `~/.config/myCodingAgent/mcp.json`。

### 场景一：本地开发，使用 Ollama Embedding 和本机 Milvus

适合日常开发机：主模型走 DeepSeek API，Embedding 走本地 Ollama，Skill 向量索引写入本机 Milvus。

先启动依赖：

```bash
export DEEPSEEK_API_KEY="sk-..."
ollama pull bge-m3
docker compose -f Milvus/docker-compose.yml up -d
```

配置文件：

```yaml
api:
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-pro"

embedding:
  provider: "bge_http"
  api_format: "ollama"
  endpoint: "http://127.0.0.1:11434/api/embed"
  model: "bge-m3"
  dimension: 1024
  batch_size: 16

milvus:
  enabled: true
  uri: "http://127.0.0.1:19530"
  collection: "mycodingagent_skills"
  analyzer_params:
    type: "chinese"
```

### 场景二：快速冒烟或 CI，使用 hash Embedding 和本机 Milvus

适合不想启动额外 Embedding 服务、只验证 Agent 能启动和 Skill 索引能写入的情况。hash Embedding 可用但语义检索效果不如真实模型。

先启动依赖：

```bash
export DEEPSEEK_API_KEY="sk-..."
docker compose -f Milvus/docker-compose.yml up -d
```

配置文件：

```yaml
api:
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-pro"

embedding:
  provider: "hash"
  hash_dimension: 256

milvus:
  enabled: true
  uri: "http://127.0.0.1:19530"
  collection: "mycodingagent_skills_ci"
```

### 场景三：云端 Embedding，使用 DashScope OpenAI 兼容接口

适合不想在本地跑 Embedding 服务，但希望 Skill 检索质量稳定的情况。

先设置密钥：

```bash
export DEEPSEEK_API_KEY="sk-..."
export MYCODINGAGENT_EMBEDDING_API_KEY="sk-..."
docker compose -f Milvus/docker-compose.yml up -d
```

配置文件：

```yaml
api:
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-pro"

embedding:
  provider: "openai_compatible"
  api_format: "openai"
  endpoint: "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
  model: "text-embedding-v4"
  dimension: 1536
  timeout: 30

milvus:
  enabled: true
  uri: "http://127.0.0.1:19530"
  collection: "mycodingagent_skills_dashscope"
```

### 场景四：本地 sentence-transformers 模型

适合已经下载好本地 BGE 或其他 sentence-transformers 模型，并希望完全本地生成向量的情况。

先启动依赖：

```bash
export DEEPSEEK_API_KEY="sk-..."
docker compose -f Milvus/docker-compose.yml up -d
```

配置文件：

```yaml
embedding:
  provider: "local"
  model: "/absolute/path/to/local/bge-m3"
  device: "cpu"
  batch_size: 16
  fallback_to_hash: false

milvus:
  enabled: true
  uri: "http://127.0.0.1:19530"
  collection: "mycodingagent_skills_local"
```

如果本地模型偶尔不可用，但希望开发环境继续启动，可以临时设置：

```yaml
embedding:
  provider: "local"
  model: "/absolute/path/to/local/bge-m3"
  fallback_to_hash: true
```

### 场景五：连接远程 Milvus 或 Zilliz

适合团队共用向量库，或本地机器不运行 Milvus 的情况。`uri` 和 `token` 按服务商控制台提供的值填写。

```bash
export DEEPSEEK_API_KEY="sk-..."
export MYCODINGAGENT_EMBEDDING_API_KEY="sk-..."
export MYCODINGAGENT_MILVUS_TOKEN="user:password-or-token"
```

配置文件：

```yaml
embedding:
  provider: "openai_compatible"
  api_format: "openai"
  endpoint: "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
  model: "text-embedding-v4"
  dimension: 1536

milvus:
  enabled: true
  uri: "https://your-milvus-endpoint.example.com"
  collection: "mycodingagent_skills_team"
  recreate_incompatible: false
```

### 场景六：用户级配置和项目级配置分开管理

适合多人项目：个人密钥放用户级配置，项目只提交非敏感默认值。默认不会加载工作区 `.mycodingagent/config.yaml`，需要显式开启。

用户级 `~/.config/myCodingAgent/config.yaml`：

```yaml
api:
  deepseek_api_key: "sk-..."

embedding:
  api_key: "sk-..."
```

项目级 `.mycodingagent/config.yaml`：

```yaml
embedding:
  provider: "openai_compatible"
  api_format: "openai"
  endpoint: "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
  model: "text-embedding-v4"
  dimension: 1536

milvus:
  uri: "http://127.0.0.1:19530"
  collection: "mycodingagent_project_skills"
```

启动前启用项目级配置：

```bash
export MYCODINGAGENT_LOAD_WORKSPACE_CONFIG=1
```

### 场景七：启用 GitHub MCP，只把 token 放在 shell 环境

适合本地个人使用：JSON 不保存 GitHub token，启动 Agent 前由 shell 注入。

```bash
export GITHUB_PERSONAL_ACCESS_TOKEN="ghp_xxx"
```

MCP 配置：

```json
{
  "servers": {
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "description": "GitHub 仓库、Issue、PR 和代码搜索操作",
      "tags": ["github", "git", "repo"],
      "aliases": ["gh"],
      "keywords": ["GitHub", "代码仓库", "PR", "issue"],
      "permissions": {
        "read_tools": ["search_repositories", "get_file_contents"],
        "write_tools": ["create_issue", "create_pull_request"],
        "dangerous_tools": ["delete_file", "merge_pull_request"],
        "readonly_by_default": false
      }
    }
  }
}
```

### 场景八：启用 GitHub MCP，把 token 写在用户级 MCP 配置

适合没有统一 shell profile 的机器。不要把这个文件提交到仓库。

`~/.config/myCodingAgent/mcp.json`：

```json
{
  "servers": {
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"
      },
      "description": "GitHub 仓库、Issue、PR 和代码搜索操作",
      "tags": ["github", "git", "repo"],
      "aliases": ["gh"],
      "keywords": ["GitHub", "代码仓库", "PR", "issue"]
    }
  }
}
```

### 场景九：只读文件系统 MCP，放在 Docker 沙箱运行

适合让 MCP Server 读取当前工作区，但不允许写文件和联网。

MCP 配置：

```json
{
  "servers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
      "sandbox": true,
      "workspace_access": "read",
      "network": false,
      "description": "只读访问当前工作区文件",
      "tags": ["filesystem", "workspace", "file"],
      "permissions": {
        "readonly_by_default": true
      }
    }
  }
}
```

### 场景十：连接远程 Streamable HTTP MCP

适合连接公司内部或云端 MCP 服务。HTTP 认证头写在 `headers` 中。

MCP 配置：

```json
{
  "servers": {
    "company-tools": {
      "transport": "streamable_http",
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer mcp_xxx"
      },
      "description": "公司内部工具 MCP Server",
      "tags": ["company", "internal", "mcp"],
      "startup_timeout": 20,
      "call_timeout": 60,
      "permissions": {
        "readonly_by_default": false
      }
    }
  }
}
```

## Embedding 配置

Embedding 用于 Skill 检索和能力路由。支持本地 sentence-transformers、Ollama HTTP、OpenAI 兼容接口、DashScope 原生接口和 hash fallback。

| 用途 | 环境变量 | 配置文件字段 | 说明 |
| --- | --- | --- | --- |
| Provider | `MYCODINGAGENT_EMBEDDING_PROVIDER` | `embedding.provider` | 支持 `bge_http`、`http`、`ollama`、`openai_compatible`、`dashscope`、`local`、`bge`、`hash` |
| 模型名 | `MYCODINGAGENT_EMBEDDING_MODEL` | `embedding.model` | 旧变量：`MYCODINGAGENT_BGE_MODEL` |
| 接口地址 | `MYCODINGAGENT_EMBEDDING_ENDPOINT` | `embedding.endpoint` | 旧变量：`MYCODINGAGENT_BGE_ENDPOINT` |
| API 格式 | `MYCODINGAGENT_EMBEDDING_API_FORMAT` | `embedding.api_format` | 支持 `ollama`、`openai`、`dashscope` |
| API 密钥 | `MYCODINGAGENT_EMBEDDING_API_KEY` | `embedding.api_key` | 旧变量：`MYCODINGAGENT_BGE_API_KEY` |
| 向量维度 | `MYCODINGAGENT_EMBEDDING_DIM` | `embedding.dimension` | 必须与实际模型输出一致 |
| 请求超时 | `MYCODINGAGENT_EMBEDDING_TIMEOUT` | `embedding.timeout` | 单位：秒 |
| 查询前缀 | `MYCODINGAGENT_EMBEDDING_QUERY_INSTRUCTION` | `embedding.query_instruction` | 用于 query embedding |
| 本地设备 | `MYCODINGAGENT_EMBEDDING_DEVICE` | `embedding.device` | 如 `cpu`、`cuda` |
| 批大小 | `MYCODINGAGENT_EMBEDDING_BATCH_SIZE` | `embedding.batch_size` | 本地或 HTTP 批量嵌入大小 |
| 额外请求体 | `MYCODINGAGENT_EMBEDDING_REQUEST_EXTRA` | `embedding.request_extra` | 环境变量必须是 JSON 对象 |
| 额外请求头 | `MYCODINGAGENT_EMBEDDING_HEADERS` | `embedding.headers` | 环境变量必须是 JSON 对象 |
| hash 兜底 | `MYCODINGAGENT_EMBEDDING_FALLBACK_TO_HASH` | `embedding.fallback_to_hash` | 本地模型加载失败时是否降级 |
| hash 维度 | `MYCODINGAGENT_HASH_EMBEDDING_DIM` | `embedding.hash_dimension` | provider 为 `hash` 时使用 |

Ollama 示例：

```yaml
embedding:
  provider: "bge_http"
  api_format: "ollama"
  endpoint: "http://127.0.0.1:11434/api/embed"
  model: "bge-m3"
  dimension: 1024
```

DashScope OpenAI 兼容接口示例：

```yaml
embedding:
  provider: "openai_compatible"
  api_format: "openai"
  endpoint: "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
  model: "text-embedding-v4"
  dimension: 1536
```

```bash
export MYCODINGAGENT_EMBEDDING_API_KEY="sk-..."
```

本地模型示例：

```yaml
embedding:
  provider: "local"
  model: "/absolute/path/to/bge-m3"
  device: "cpu"
  batch_size: 16
```

## Milvus 向量库配置

Milvus 用于保存 Skill 向量索引。默认连接本机 `127.0.0.1:19530`，仓库提供 `Milvus/docker-compose.yml` 作为本地启动参考。

| 用途 | 环境变量 | 配置文件字段 | 默认值 |
| --- | --- | --- | --- |
| 是否启用 | `MYCODINGAGENT_MILVUS_ENABLED` | `milvus.enabled` | `true` |
| Host | `MYCODINGAGENT_MILVUS_HOST` | `milvus.host` | `127.0.0.1` |
| Port | `MYCODINGAGENT_MILVUS_PORT` | `milvus.port` | `19530` |
| URI | `MYCODINGAGENT_MILVUS_URI` | `milvus.uri` | `http://{host}:{port}` |
| Collection | `MYCODINGAGENT_MILVUS_COLLECTION` | `milvus.collection` | `mycodingagent_skills` |
| Token | `MYCODINGAGENT_MILVUS_TOKEN` | `milvus.token` | 空 |
| 不兼容时重建 | `MYCODINGAGENT_MILVUS_RECREATE_INCOMPATIBLE` | `milvus.recreate_incompatible` | `true` |
| Dense index | `MYCODINGAGENT_MILVUS_DENSE_INDEX_TYPE` | `milvus.dense_index_type` | `HNSW` |
| Dense metric | `MYCODINGAGENT_MILVUS_DENSE_METRIC_TYPE` | `milvus.dense_metric_type` | `COSINE` |
| HNSW M | `MYCODINGAGENT_MILVUS_HNSW_M` | `milvus.hnsw_m` | `16` |
| HNSW EF 构建 | `MYCODINGAGENT_MILVUS_HNSW_EF_CONSTRUCTION` | `milvus.hnsw_ef_construction` | `256` |
| HNSW EF 查询 | `MYCODINGAGENT_MILVUS_HNSW_EF` | `milvus.hnsw_ef` | `64` |
| Sparse index | `MYCODINGAGENT_MILVUS_SPARSE_INDEX_TYPE` | `milvus.sparse_index_type` | `SPARSE_INVERTED_INDEX` |
| Sparse metric | `MYCODINGAGENT_MILVUS_SPARSE_METRIC_TYPE` | `milvus.sparse_metric_type` | `BM25` |
| Sparse 算法 | `MYCODINGAGENT_MILVUS_SPARSE_ALGO` | `milvus.sparse_inverted_index_algo` | `DAAT_MAXSCORE` |
| RRF K | `MYCODINGAGENT_MILVUS_RRF_K` | `milvus.rrf_k` | `60` |
| 文本最大字节 | `MYCODINGAGENT_MILVUS_TEXT_MAX_BYTES` | `milvus.text_max_bytes` | `65535` |
| Analyzer 参数 | `MYCODINGAGENT_MILVUS_ANALYZER_PARAMS` | `milvus.analyzer_params` | `{"type":"chinese"}` |

## MCP Server 配置

MCP 配置文件加载顺序如下，后加载的同名 server 覆盖前者：

1. `~/.config/myCodingAgent/mcp.json`
2. 当前项目 `.mycodingagent/mcp.json`
3. `MYCODINGAGENT_MCP_CONFIG` 指定的额外 JSON 文件

MCP 总开关和路径变量：

| 用途 | 环境变量 | 配置文件字段 | 默认值 |
| --- | --- | --- | --- |
| MCP 总开关 | `MYCODINGAGENT_MCP_ENABLED` | `mcp.enabled` | `true` |
| 项目 MCP 配置路径 | `MYCODINGAGENT_MCP_PROJECT_CONFIG` | `mcp.project_config_path` | `.mycodingagent/mcp.json` |
| 用户 MCP 配置路径 | `MYCODINGAGENT_MCP_USER_CONFIG` | `mcp.user_config_path` | `~/.config/myCodingAgent/mcp.json` |
| 额外 MCP 配置路径 | `MYCODINGAGENT_MCP_CONFIG` | 无 | 空 |
| 不可用 server 重连步长 | `MYCODINGAGENT_RECONNECT_MCP_SERVER_STEP` | `mcp.reconnect_server_step` | `10` |

每个 server 支持字段：

| 字段 | 说明 |
| --- | --- |
| `disabled` | `true` 时跳过该 server |
| `transport` | `stdio` 或 `streamable_http` |
| `command` | `stdio` server 的启动命令 |
| `args` | `stdio` server 的启动参数 |
| `env` | 追加给 `stdio` server 进程的环境变量；会覆盖当前进程同名变量 |
| `url` | `streamable_http` server 的地址 |
| `headers` | `streamable_http` 请求头 |
| `startup_timeout` | 启动和初始化超时，单位秒 |
| `call_timeout` | 单次 tool/resource/prompt 调用超时，单位秒 |
| `sandbox` | `stdio` server 是否放入 Docker 沙箱运行 |
| `image` | server 使用的 Docker 镜像；为空时使用全局 Docker 镜像 |
| `workspace_access` | 沙箱内工作区挂载权限：`none`、`read`、`write` |
| `network` | 沙箱内是否开启网络 |
| `description`、`tags`、`aliases`、`keywords` | 能力路由检索用的描述信息 |
| `permissions.read_tools` | 明确标为只读的工具名 |
| `permissions.write_tools` | 明确标为写入的工具名 |
| `permissions.dangerous_tools` | 明确标为危险的工具名 |
| `permissions.readonly_by_default` | 未匹配工具是否默认按只读处理 |

GitHub MCP 示例：

```json
{
  "servers": {
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"
      },
      "description": "GitHub 仓库、Issue、PR 和代码搜索操作",
      "tags": ["github", "git", "repo"],
      "aliases": ["gh"],
      "keywords": ["GitHub", "代码仓库", "PR", "issue"]
    }
  }
}
```

如果不想把 GitHub token 写入 JSON，也可以在启动前设置：

```bash
export GITHUB_PERSONAL_ACCESS_TOKEN="ghp_xxx"
```

## Docker 和沙箱配置

| 用途 | 环境变量 | 配置文件字段 | 默认值 |
| --- | --- | --- | --- |
| 工作区根目录 | `MYCODINGAGENT_SANDBOX_ROOT` | `sandbox.root` | 当前目录 |
| 工具输出上限 | `MYCODINGAGENT_MAX_OUTPUT_CHARS` | `sandbox.max_output_chars` | `10000` |
| 工作区租约 | `MYCODINGAGENT_WORKSPACE_LEASE_ENABLED` | `sandbox.workspace_lease_enabled` | `true` |
| Docker 镜像 | `MYCODINGAGENT_DOCKER_IMAGE` | `docker.image` | `mycodingagent-sandbox:py312` |
| Docker 网络 | `MYCODINGAGENT_DOCKER_NETWORK` | `docker.network` | `none` |
| 构建网络 | `MYCODINGAGENT_DOCKER_BUILD_NETWORK` | `docker.build_network` | `host` |
| CPU 限制 | `MYCODINGAGENT_DOCKER_CPUS` | `docker.cpus` | `2` |
| 内存限制 | `MYCODINGAGENT_DOCKER_MEMORY` | `docker.memory` | `1g` |
| 进程数限制 | `MYCODINGAGENT_DOCKER_PIDS_LIMIT` | `docker.pids_limit` | `256` |
| 默认超时 | `MYCODINGAGENT_DOCKER_DEFAULT_TIMEOUT` | `docker.default_timeout` | `120` |
| 最大超时 | `MYCODINGAGENT_DOCKER_MAX_TIMEOUT` | `docker.max_timeout` | `600` |
| 镜像检查超时 | `MYCODINGAGENT_DOCKER_CHECK_TIMEOUT` | `docker.check_timeout` | `10` |
| 镜像拉取超时 | `MYCODINGAGENT_DOCKER_PULL_TIMEOUT` | `docker.pull_timeout` | `1800` |

## Skill 和记忆配置

常用 Skill 变量：

| 用途 | 环境变量 | 配置文件字段 |
| --- | --- | --- |
| 内置 Skill 根目录 | `MYCODINGAGENT_BUILTIN_SKILLS_ROOT` | `skills.builtin_root` |
| 工作区 Skill 根目录 | `MYCODINGAGENT_WORKSPACE_SKILLS_ROOT` 或 `MYCODINGAGENT_SKILLS_ROOT` | `skills.workspace_root` |
| 额外 Skill 根目录 | `MYCODINGAGENT_EXTRA_SKILLS_ROOTS` | `skills.extra_roots` |
| 默认启用 Skill | `MYCODINGAGENT_DEFAULT_SKILLS` | `skills.default_tool_names` |
| Skill 索引目录 | `MYCODINGAGENT_SKILL_INDEX_DIR` | `skills.index_dir` |
| Skill 搜索 Top K | `MYCODINGAGENT_SKILL_SEARCH_TOP_K` | `skills.search_top_k` |
| Skill 最低分 | `MYCODINGAGENT_SKILL_MIN_SCORE` | `skills.min_score` |
| Skill 向量同步批大小 | `MYCODINGAGENT_SKILL_VECTOR_SYNC_BATCH_SIZE` | `skills.vector_sync_batch_size` |
| Skill 向量同步重试次数 | `MYCODINGAGENT_SKILL_VECTOR_SYNC_MAX_RETRIES` | `skills.vector_sync_max_retries` |

常用记忆变量：

| 用途 | 环境变量 | 配置文件字段 | 默认值 |
| --- | --- | --- | --- |
| 短期记忆总开关 | `MYCODINGAGENT_MEMORY_ENABLED` | `memory.enabled` | `true` |
| 状态目录 | `MYCODINGAGENT_STATE_DIR` | `memory.state_dir` | 空 |
| 会话数据库路径 | `MYCODINGAGENT_MEMORY_DB_PATH` | `memory.db_path` | XDG state 或 `~/.local/state/myCodingAgent/sessions.sqlite3` |
| 上下文窗口 | `MYCODINGAGENT_MODEL_CONTEXT_WINDOW` | `memory.default_context_window` | `1000000` |
| 会话保留天数 | `MYCODINGAGENT_MEMORY_SESSION_TTL_DAYS` | `memory.session_ttl_days` | `30` |
| 工作区快照保留天数 | `MYCODINGAGENT_MEMORY_WORKSPACE_SNAPSHOT_TTL_DAYS` | `memory.workspace_snapshot_ttl_days` | `30` |
| 长期记忆总开关 | `MYCODINGAGENT_LONG_TERM_MEMORY_ENABLED` | `long_term_memory.enabled` | `true` |
| 长期记忆存储模型 | `MYCODINGAGENT_LONG_TERM_MEMORY_STORAGE_MODEL` | `long_term_memory.storage_model` | 主模型 |
| 长期记忆查询模型 | `MYCODINGAGENT_LONG_TERM_MEMORY_QUERY_MODEL` | `long_term_memory.query_model` | 主模型 |

## 运行时调试变量

| 用途 | 环境变量 | 配置文件字段 | 默认值 |
| --- | --- | --- | --- |
| Debug 开关 | `DEBUG` 或 `MYCODINGAGENT_DEBUG` | `client.debug` | `false` |
| 单步 token 统计 | `STEP_TOKEN` | `client.step_token` | `true` |
| 单轮 token 统计 | `ROUND_TOKEN` | `client.round_token` | `true` |
| 会话 token 统计 | `CONVERSATION_TOKEN` | `client.conversation_token` | `true` |
| 最大工具轮次 | `MYCODINGAGENT_MAX_TOOL_ROUNDS` | `client.max_tool_rounds` | `50` |
| API 最大重试 | `MYCODINGAGENT_API_MAX_RETRIES` | `client.api_max_retries` | `3` |
| API 重试基础延迟 | `MYCODINGAGENT_API_RETRY_BASE_DELAY` | `client.api_retry_base_delay` | `1.0` |
| 使用旧系统提示词 | `MYCODINGAGENT_LEGACY_SYSTEM_PROMPT` | `client.legacy_system_prompt` | `false` |
| 多智能体最大轮次 | `MYCODINGAGENT_MULTI_AGENT_MAX_AGENT_ROUNDS` | `multi_agent.max_agent_rounds` | `50` |
| 多智能体最大并发 | `MYCODINGAGENT_MULTI_AGENT_MAX_PARALLEL_TASKS` | `multi_agent.max_parallel_tasks` | `5` |

## LSP 配置

语言服务器命令通过环境变量覆盖，格式为：

```bash
export MYCODINGAGENT_LSP_<LANGUAGE>_COMMAND="启动命令"
```

示例：

```bash
export MYCODINGAGENT_LSP_PYTHON_COMMAND="pyright-langserver --stdio"
```
