# 代码智能

代码智能不在启动阶段构建全局项目图谱，而是按工具调用动态解析当前需要的文件。

`DynamicDependencyRuntime` 使用 tree-sitter 支持 Python、Go、TypeScript、JavaScript、Rust 和 Java。单位使用以下规范名称：

```text
relative/path/file.py::function
relative/path/file.ts::Class
relative/path/file.ts::Class.method
```

`QueryUnitDependency` 根据目标文件的 import 索引筛选候选文件，再在候选文件中解析哪些单位调用了目标单位。结果包含调用方单位名称、路径和非空 description，并区分候选文件与无法唯一解析的关系。文件内容变化后，解析和 import 缓存按内容 hash 失效；调用关系不会通过终端名称直接猜测。

`UpdateUnitDescription` 按规范单位名称保存 description。传入空字符串会删除 description，成功结果固定为“修改成功”。

`PathTaskGraphRuntime` 是独立的会话级路径范围图。`CreateTaskGraph` 根据文件或目录路径生成目录树，`UpdateTaskGraph` 只保存 Agent 提交的工作状态（`pending`/`modified`）和测试状态（`untested`/`failed`/`passed`）。任务图不依赖代码索引，也不验证源码正确性。

LSP 仍是可选的语义复核能力；它与动态依赖查询相互独立。
