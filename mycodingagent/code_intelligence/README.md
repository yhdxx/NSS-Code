# 代码理解

提供 Python、Go、TypeScript、JavaScript、Rust 和 Java 的 tree-sitter 增量索引，以及按语言懒启动的 LSP 客户端。

`ProjectGraphRuntime` 是图谱生命周期的唯一入口。General 模式下工作区事件只累加内存 revision；只有进入 Code 模式才懒初始化索引和图谱存储。Code 后台刷新按 revision 去抖、串行执行且默认静默，bootstrap 树只在消息真正追加时由终端渲染。

索引保存符号、限定调用、import 和语法引用。`overview` 聚合目录结构，
`outline` 查看单文件结构，`impact` 聚合单个符号的修改影响，`batch` 让多个结构查询共享一次刷新。
operation 参数不匹配时返回结构化错误和 `suggested_call`。Schema 带版本号，不兼容时自动重建可丢弃的索引缓存。

LSP 只负责精确定义、引用、类型和诊断等语义复核，维护 `didOpen`/`didChange` 文档版本并在退出时关闭进程。
语言服务器是可选外部依赖；运行时会报告每种语言的可用状态和最近启动错误。

`contracts.py` 向工具层暴露最小 Protocol；具体索引和进程只在 `app/main.py` 组装。索引和图谱属于可重建缓存，schema 不兼容时仅在 Code 初始化期间重建。
