# Code / General 工作模式 A/B 评测

- 状态：`deferred_by_user`
- 指标 ID：`code_general_ab`

## 指标定义

在相同模型、任务和工具 schema 下，对比 Code 图谱导航与 General 自主探索的任务成功率和执行成本。

## 计算公式

- 任务成功率 = 验收测试通过的运行数 / 总运行数
- 成本降幅 = (General 均值 - Code 均值) / General 均值

## 数据集与样本

```json
{
  "sample_count": 0,
  "tool_schema_hash": "353c3c21365b3bc5bc32e362728d51213a4566946b7bc4d0d809a82de93d9360"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-01T17:23:37+0800",
  "git_commit": "ec48e4dafbce640241eb0dd4ebc5d527870098f3",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 1,
  "run_id": "deferred-graph-redesign-20260801"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner defer-code-general-ab
```

## 结果与置信区间

```json
{
  "reason": "用户正在修改项目图谱逻辑；图谱与 Code/General 实测已显式延期。"
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

- 结论门禁：至少 30 个任务、每模式 3 次；Code 成功率不得比 General 低超过 5 个百分点，且 token 或读取/工具调用成本显著下降，才可表述为提高效率。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

不可使用量化结论（status=deferred_by_user）：用户正在修改项目图谱逻辑；图谱与 Code/General 实测已显式延期。
