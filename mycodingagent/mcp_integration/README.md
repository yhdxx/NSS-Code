# MCP 集成

封装 MCP stdio/Streamable HTTP 配置、懒连接、持久化 schema 缓存、调用前 discovery gate、执行和
fail-closed 权限审批。只有 `list_mcp_tools`/`search_mcp_tools` 实际展示且 metadata 指纹仍匹配的工具才能进入执行与审批。

stdio server 可显式开启 Docker 隔离；宿主启动、网络、工作区写入和危险工具分别受审批边界控制。容器配置支持
镜像 ENTRYPOINT、独立 CPU/内存/PID/共享内存限制和 host 映射。MCP 图片结果统一保存到工作区
`.mycodingagent/artifacts/mcp/`，供 `AnalyzeImage` 继续处理。

MCP 配置模板见根目录 `.mycodingagent/mcp.example.json`。完整字段说明、加载顺序、按场景可复制示例、GitHub token
、Playwright Headless Chromium 和 Streamable HTTP 示例见 `docs/mcp.md`，模板中的说明字段统一使用中文。

依赖方向和函数级索引见根目录 `PROJECT_FRAMEWORK.md`。
