# MCP 集成

封装 MCP stdio/Streamable HTTP 配置、懒连接、持久化 schema 缓存、执行和 fail-closed 权限审批。

stdio server 可显式开启 Docker 隔离；宿主启动、网络、工作区写入和危险工具分别受审批边界控制。

依赖方向和函数级索引见根目录 `PROJECT_FRAMEWORK.md`。
