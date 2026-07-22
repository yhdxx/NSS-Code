# 工具运行时

定义工具基类、注册表和具体工具适配器；业务模块通过 Protocol 与其交互。

- `CommitWorkingContext` 通过 `ContextEpochControl` 安排当前多轮工作阶段在回合结束后归档，不直接依赖 `MemoryRuntime` 实现。
- `BatchRecoverContext`、`SearchRecoverableContext` 等工具仅在证据已离开活动工作阶段后按需恢复。

依赖方向和函数级索引见根目录 `PROJECT_FRAMEWORK.md`。
