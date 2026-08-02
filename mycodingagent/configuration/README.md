# 配置

集中解析配置文件和环境变量并提供不可变配置对象，不包含业务逻辑。

加载优先级：

1. `~/.mycodingagent/config.json`
2. 环境变量（JSON 字段缺失或为空字符串时生效）
3. 代码内置默认值

`bootstrap.py` 在 `CONFIG` 导入前负责创建 `~/.mycodingagent/config.json`，并把
`docs/configuration.md` 同步到 `~/.mycodingagent/README.md`。
项目提供 `.mycodingagent/config.example.json` 作为主配置模板；YAML 示例仅作迁移参考，运行时不读取。
完整配置说明、环境变量表、按场景可复制示例、Embedding、Milvus 和 MCP 配置示例见根目录 `docs/configuration.md`。
新增外部依赖配置时，优先加入 `settings.py` 的配置文件映射、JSON 示例和配置文档，并保留环境变量兜底能力。

Embedding 配置支持本地 sentence-transformers、Ollama HTTP、OpenAI-compatible 在线接口、DashScope 原生接口和
hash fallback。Skill 向量索引会记录 embedding signature；模型、接口或请求参数变化后会重新嵌入。

依赖方向和函数级索引见根目录 `PROJECT_FRAMEWORK.md`。
