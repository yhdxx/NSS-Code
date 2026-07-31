# 工具运行时

定义工具基类、注册表和具体工具适配器；业务模块通过 Protocol 与其交互。

- `CommitWorkingContext` 通过 `ContextEpochControl` 安排当前热工作阶段在回合结束后转为冷上下文；它是轮转控制工具，不要求模型生成任务摘要，也不直接依赖 `MemoryRuntime` 实现。
- `BatchRecoverContext`、`SearchRecoverableContext` 等工具仅在证据已离开活动工作阶段后按需恢复。
- `execution.py` 是主 Agent 与 Multi-Agent 共享的执行、中断、状态记录和重复失败门控入口。
- `code_intelligence.py` 通过 Protocol 适配稳定的 `code_index` / `lsp` 工具 schema。
- `mcp_discovery.py` 只为本次实际展示的工具登记 metadata 指纹；`mcp_execution.py` 在审批和远程调用前强制校验该指纹。

依赖方向和函数级索引见根目录 `PROJECT_FRAMEWORK.md`。
