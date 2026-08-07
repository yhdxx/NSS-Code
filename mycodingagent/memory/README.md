# 记忆系统

负责会话、上下文虚拟化、跨多轮热工作阶段、检查点、恢复和 SQLite 持久化。

- `context_epoch.py`：通过 `ContextEpochManager` 管理活动阶段、30% 提醒、40% 强制提交和阶段迁移。
- `contracts.py`：向工具层暴露最小 `ContextEpochControl` Protocol。
- `runtime.py`：编排模型渲染、回合完成、阶段提交、cold 区域归档阈值和检查点生命周期。
- `stores.py`：持久化 `context_epochs`、消息、工具输出、快照和 token 使用记录。
- `workspace_checkpoint.py`：保存内容寻址的文件写前快照，并在 hash 冲突检查后执行 rewind。

依赖方向和函数级索引见根目录 `PROJECT_FRAMEWORK.md`。

运行时由组合根把会话与检查点数据库绑定到当前工作区的
`.mycodingagent/state/sessions.sqlite3`。用户级长期记忆仍使用配置中的全局数据库；项目事实由长期记忆运行时单独写入
工作区 `.mycodingagent/state/project_memory.sqlite3`，从而让删除项目目录同时删除项目专属状态。

## 冷区工具调用

Raw 模式和当前 context epoch 的热区保留完整消息。只有消息从热区进入虚拟化冷区时，历史 assistant 的工具参数才会按工具类型压缩；canonical messages、执行参数和 SQLite 中的 `arguments_json`/`output_text` 始终保留原文。

每个模型可见工具调用都要求不超过 240 字符的 `intent`。它描述调用的工具或命令、动作和目的；同一用户轮次或 Plan 子任务的后续调用还应先概括上一轮工具结果。Runtime 不解析 intent 的语义。

冷区参数使用 `<COLD_ARGUMENT_VIRTUALIZED>` 占位符。`WriteFile` 保留 `file_path` 和 `intent`，正文始终省略；`EditFile` 保留路径和 intent，`old_string`/`new_string` 始终省略；`Bash` 仅保留不超过 240 字符的 command 和 intent，并移除执行控制字段。读取工具保留短路径、查询和范围；MCP 保留 server/tool/uri/prompt 与 intent；Plan、Skill 和未知工具按字段长度压缩。列表和对象占位符仍保持 JSON 容器类型。缺少有效 intent 时保留完整参数作为正确性兜底。

冷区普通工具结果只保留成功/错误状态、`context_id` 和恢复提示。需要原始参数或输出时，使用 `BatchRecoverContext` 的 `section=arguments|output|both`，分别通过 `arguments_offset`/`arguments_limit` 和 `output_offset`/`output_limit` 分页；单次最多处理 8 项、返回 60,000 字符。Skill 输出仍不可通过该接口恢复。
