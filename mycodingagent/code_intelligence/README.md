# 代码理解

提供 Python、Go、TypeScript、JavaScript、Rust 和 Java 的 tree-sitter 增量索引，以及按语言懒启动的 LSP 客户端。

索引以工作区事件驱动脏路径刷新，保存符号、限定调用、import 和语法引用。`overview` 聚合目录结构，
`outline` 查看单文件结构，`impact` 聚合单个符号的修改影响，`batch` 让多个结构查询共享一次刷新。
operation 参数不匹配时返回结构化错误和 `suggested_call`。Schema 带版本号，不兼容时自动重建可丢弃的索引缓存。

LSP 只负责精确定义、引用、类型和诊断等语义复核，维护 `didOpen`/`didChange` 文档版本并在退出时关闭进程。
语言服务器是可选外部依赖；运行时会报告每种语言的可用状态和最近启动错误。

`contracts.py` 向工具层暴露最小 Protocol；具体索引和进程只在 `app/main.py` 组装。
