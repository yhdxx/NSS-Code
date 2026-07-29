# myCodingAgent 有效性评测报告

- 生成时间：2026-07-28 23:21:56
- 评测原则：先生成测试集，再运行真实 API / 真实检索组件，最后汇总报告。

## 测试集规模

| 数据集 | 样例数 |
|---|---:|
| `capability_router_cases.jsonl` | 20 |
| `context_virtualization_cases.jsonl` | 12 |
| `long_term_workflow_cases.jsonl` | 6 |
| `multi_agent_tasks.jsonl` | 30 |
| `recovery_cases.jsonl` | 10 |
| `skill_router_500_cases.jsonl` | 1 |

## 已运行结果

| 模块 | 状态 | 关键结果 |
|---|---|---|
| `bge_precheck.jsonl` | passed | endpoint=http://127.0.0.1:11434/api/embed; model=bge-m3; dimension=1024 |
| `capability_router.jsonl` | passed | case_count=20 |
| `context_virtualization.jsonl` | passed | case_count=2 |
| `long_term_workflow.jsonl` | passed | case_count=3 |
| `multi_agent_ab.jsonl` | failed | case_count=6; run_count=12; direct_accuracy=1.0; multi_agent_accuracy=0.8333; direct_avg_duration_seconds=47.8842; multi_agent_avg_duration_seconds=507.1638 |
| `recovery.jsonl` | passed | case_count=3 |
| `skill_router_500.jsonl` | passed | skill_count=520; query_count=100; recall_at_1=1.0; recall_at_3=1.0; recall_at_5=1.0; mrr=1.0 |

## 模块覆盖说明

- 多智能体：比较 direct_mode 与 multi_agent_mode 在小/中/大规模代码任务上的准确率、耗时、工具调用和 token。
- 上下文虚拟化：比较 raw、virtualized、summary_baseline、recent_only 四种上下文策略对早期需求召回和成本的影响。
- 长期记忆：重点验证 workflow_candidate 跨会话检索后是否减少重复工具调用并提高成功率。
- Skill 路由：在 500+ name/description Skill 下测试目标 Skill 是否进入 Top-K 候选。
- Capability Router / MCP：验证简单任务、Skill、MCP、恢复工具等能力是否被正确路由。
- 恢复工具：验证虚拟化历史工具输出是否能通过 BatchRecoverContext 精确恢复。

## 结论填写规则

- 只有 `status=passed` 的模块可以作为简历或项目文档中的有效性证据。
- `blocked` 表示依赖未满足，例如 Milvus 未启动、BGE 不可用或真实 API 配置缺失。
- hash embedding smoke test 不计入 Skill 语义路由正式结论。
