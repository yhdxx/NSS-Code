# 上下文虚拟化评测

- 状态：`not_run`
- 指标 ID：`context_virtualization`

## 指标定义

比较 raw、virtualized 与 recent_only 在多轮长会话中的任务成功率、历史证据恢复率和输入成本。

## 计算公式

- 成功率 = 正确回答运行数 / 总运行数
- 输入压缩率 = (Raw 输入 token - 候选输入 token) / Raw 输入 token

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
python3 -m tests.eval.modern_runner run-context-virtualization
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

- 结论门禁：至少 30 个长会话任务、每种策略 3 次，并报告 p50/p95 与 95% 置信区间。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

不可使用量化结论（status=not_run）：尚未执行新版标准评测
