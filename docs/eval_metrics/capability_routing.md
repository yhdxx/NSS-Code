# Skill / MCP 能力路由评测

- 状态：`passed`
- 指标 ID：`capability_routing`

## 指标定义

在千级 Skill 与 MCP 能力语料中，用不直接复用能力名称的人工风格查询衡量候选召回和排序质量。

## 计算公式

- Recall@K = Top-K 含相关能力的查询数 / 查询总数
- MRR = mean(1 / 首个相关结果排名)
- NDCG@5 = DCG@5 / IDCG@5

## 数据集与样本

```json
{
  "dataset_path": "tests/eval/datasets/capability_routing_1200_cases.jsonl",
  "dataset_sha256": "bd9135b3b12a5243a509528799ccc60d424c7807b731a332c1152fa8d9b503a8",
  "sample_count": 200,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-01T19:37:25+0800",
  "git_commit": "1c5e2b27423b9618a1c76f0a1c4b38542011420e",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 1,
  "run_id": "standard-routing-batched-20260801"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-capability-routing --dataset tests/eval/datasets/capability_routing_1200_cases.jsonl
```

## 结果与置信区间

```json
{
  "avg_unrelated_top_5": 1.6,
  "capability_count": 1200,
  "duration_seconds": 249.147,
  "embedding_batch_size": 32,
  "mcp_count": 300,
  "metric_ci95": {
    "mrr": {
      "high": 0.834811,
      "low": 0.731949,
      "mean": 0.784274
    },
    "ndcg_at_5": {
      "high": 0.73598,
      "low": 0.633749,
      "mean": 0.686539
    },
    "recall_at_1": {
      "high": 0.79,
      "low": 0.665,
      "mean": 0.73
    },
    "recall_at_3": {
      "high": 0.87,
      "low": 0.77,
      "mean": 0.825
    },
    "recall_at_5": {
      "high": 0.89,
      "low": 0.795,
      "mean": 0.845
    }
  },
  "mrr": 0.784274,
  "ndcg_at_5": 0.686539,
  "query_count": 200,
  "reason": "Embedding retrieval core only; full MCP execution routing is separately integration-tested.",
  "recall_at_1": 0.73,
  "recall_at_3": 0.825,
  "recall_at_5": 0.845,
  "resume_conclusion": "在 1200 项 Skill/MCP 混合语料与 200 条改写查询上完成 BGE 检索评测；结论仅覆盖候选召回与排序，不等同于工具执行正确率。",
  "skill_count": 900
}
```

## 失败、超时与异常样例

```json
{
  "count": 0,
  "examples": []
}
```

## 局限与有效性威胁

- 结论门禁：至少 1200 个能力（含 900 Skill、300 MCP）与 200 条人工风格查询；纯模板同名数据不得作为精准路由结论。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

在 1200 项 Skill/MCP 混合语料与 200 条改写查询上完成 BGE 检索评测；结论仅覆盖候选召回与排序，不等同于工具执行正确率。
