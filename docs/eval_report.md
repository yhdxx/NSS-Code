# myCodingAgent 评测索引

每个指标都有独立、可审计的测试文档。`not_run`、`blocked`、`unavailable` 和 `deferred_by_user` 均不构成效果证据。

- [capability_routing](eval_metrics/capability_routing.md)：`passed`
- [code_general_ab](eval_metrics/code_general_ab.md)：`passed`
- [context_compression_100k](eval_metrics/context_compression_100k.md)：`insufficient_sample`
- [long_term_memory](eval_metrics/long_term_memory.md)：`passed`
- [prefix_cache](eval_metrics/prefix_cache.md)：`passed`
- [project_graph](eval_metrics/project_graph.md)：`passed`（性能完成，准确率 `not_run`）

## 总体判断

本轮评测并不支持‘所有模块均已达到优秀效果’的结论。当前证据较强的部分是前缀缓存、正确记忆提供后的利用能力和项目图谱的热读取与增量刷新；能力路由、图谱首次构建和 Code 模式执行成本仍有明确优化空间。上下文压缩的 100K 定向评测样本不足，不能作为正式效果证据。

### 证据较强的指标

- 前缀缓存：30 个会话、每会话 3 次正式测量，token 加权命中率为 **98.66%**（95% CI **98.6586%–98.6615%**）。该结论基于服务商原生 hit/miss 字段，且项目图谱未常驻 message。
- 长期记忆利用：在 runtime 已提供正确检索结果的条件下，锚点命中率为 **98.89%**（95% CI **96.67%–100%**）。该结果不覆盖记忆抽取、存储和检索召回。
- 项目图谱性能：热读取平均 **1.90 ms**、p95 **4.62 ms**；单文件增量刷新平均 **1.09 s**、p95 **4.64 s**；峰值内存平均 **17.46 MiB**。

### 需要继续优化的指标

- 能力路由：1200 项 Skill/MCP 与 200 条改写查询上，Recall@1 为 **73.0%**，Recall@3 为 **82.5%**，Recall@5 为 **84.5%**（95% CI **79.5%–89.0%**），说明候选召回仍有提升空间。该实验仅覆盖 BGE 候选召回与排序，不代表工具执行正确率。
- 项目图谱首次构建：平均 **178.56 s**、p50 **92.06 s**、p95 **587.06 s**，大项目冷启动耗时较高。
- Code / General A/B：两种模式成功率均为 **100%**，但 Code 的工具调用增加 **7.51%**、可见读取字节增加 **5.08%**、Prompt token 增加 **10.09%**、总 token 增加 **9.78%**。当前不能声明 Code 模式或项目图谱提高了 Agent 工作效率。
- 上下文压缩 100K 定向评测：4 个 case × 4 策略 × 2 次重复，四种策略任务成功率均为 **100%**；Natural 平均 Prompt token **17,100**，摘要 + 最近 10 轮基线为 **2,274**，Raw 参考为 **97,916**。该样本状态为 `insufficient_sample`，只能用于验证机制和相对趋势，不能宣称 1M 窗口下的效果。

### 尚未获得或不可使用的证据

- 长期记忆尚无端到端抽取、存储、检索召回和最终任务效果证据。
- 项目图谱准确率为 `not_run`：缺少人工标注的符号和调用边，不能声明符号覆盖率、调用精确率或召回率。
- Multi-Agent 状态为 `deprecated_incomplete`：标准实验已按计划停止，历史小样本和未配对中止数据均不能用于声明成功率或效率提升。

### 简历表述建议

可以使用前缀缓存 98.66% 以及图谱热读/增量刷新性能；必须同时写明样本规模。100K 上下文压缩结果仅可作为探索性结果，不能外推到 1M，也不应声称 Code 模式、项目图谱或 Multi-Agent 提升了端到端开发效率。

## 回归验证

- 本轮定向回归：`113 passed in 2.30s`（memory runtime、LLM runtime client、eval framework）。
- `compileall` 与 `git diff --check` 均通过。
