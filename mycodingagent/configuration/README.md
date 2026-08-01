# 配置

集中解析配置文件和环境变量并提供不可变配置对象，不包含业务逻辑。

加载优先级：

1. 代码内置默认值
2. `~/.config/myCodingAgent/config.yaml`
3. Agent 安装目录 `.mycodingagent/config.yaml`
4. `MYCODINGAGENT_LOAD_WORKSPACE_CONFIG=1` 时，当前工作区 `.mycodingagent/config.yaml`
5. `MYCODINGAGENT_CONFIG` 指定的 YAML/JSON 文件
6. 环境变量

项目提供 `.mycodingagent/config.example.yaml` 作为模板。新增外部依赖配置时，优先加入
`settings.py` 的配置文件映射和示例 YAML，并保留环境变量覆盖能力。

Embedding 配置支持本地 sentence-transformers、Ollama HTTP、OpenAI-compatible 在线接口、DashScope 原生接口和
hash fallback。Skill 向量索引会记录 embedding signature；模型、接口或请求参数变化后会重新嵌入。

依赖方向和函数级索引见根目录 `PROJECT_FRAMEWORK.md`。
