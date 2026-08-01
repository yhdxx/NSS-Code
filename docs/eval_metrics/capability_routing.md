# Skill / MCP 能力路由评测

- 状态：`not_run`
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
  "sample_count": 0
}
```

## 测试环境

```json
{
  "base_url": "",
  "generated_at": "2026-08-01T17:24:59+0800",
  "git_commit": "",
  "git_dirty": "",
  "model": "",
  "platform": "",
  "python": "",
  "random_seed": "",
  "repeats": "",
  "run_id": "not-run"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-capability-routing
```

## 结果与置信区间

```json
{
  "reason": "尚未执行新版标准评测",
  "status": "not_run"
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

不可使用量化结论（status=not_run）：尚未执行新版标准评测
