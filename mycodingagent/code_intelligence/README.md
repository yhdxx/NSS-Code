# 代码理解

提供 Python、Go、TypeScript、JavaScript、Rust 和 Java 的 tree-sitter 增量符号/调用索引，以及按语言懒启动的 LSP 客户端。

`contracts.py` 向工具层暴露最小 Protocol；具体索引和进程只在 `app/main.py` 组装。
