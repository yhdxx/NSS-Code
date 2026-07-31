# 记忆系统

负责会话、上下文虚拟化、跨多轮热工作阶段、检查点、恢复和 SQLite 持久化。

- `context_epoch.py`：通过 `ContextEpochManager` 管理活动阶段、30% 提醒、40% 强制提交和阶段迁移。
- `contracts.py`：向工具层暴露最小 `ContextEpochControl` Protocol。
- `runtime.py`：编排模型渲染、回合完成、阶段提交、cold 区域归档阈值和检查点生命周期。
- `stores.py`：持久化 `context_epochs`、消息、工具输出、快照和 token 使用记录。
- `workspace_checkpoint.py`：保存内容寻址的文件写前快照，并在 hash 冲突检查后执行 rewind。

依赖方向和函数级索引见根目录 `PROJECT_FRAMEWORK.md`。
