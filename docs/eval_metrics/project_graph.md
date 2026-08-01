# 项目图谱评测

- 状态：`deferred_by_user`
- 指标 ID：`project_graph`

## 指标定义

衡量固定项目快照上的首次建图、热读取、单文件增量刷新、资源开销，以及人工标注存在时的符号覆盖率和语法级调用边准确性。

## 计算公式

- 符号覆盖率 = 正确检出的标注符号数 / 标注符号总数
- 调用精确率 = 正确调用边数 / 标注文件范围内检出的调用边数
- 调用召回率 = 正确调用边数 / 标注调用边总数

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
  "generated_at": "2026-08-01T17:24:59+0800",
  "git_commit": "ec48e4dafbce640241eb0dd4ebc5d527870098f3",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 1,
  "run_id": "deferred-graph-redesign-docs-20260801"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner defer-project-graph
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

- 结论门禁：性能结果需覆盖 10 个固定 commit；准确性结果还需每项目至少 30 个符号和 20 条调用边的人工标注。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

不可使用量化结论（status=deferred_by_user）：用户正在修改项目图谱逻辑；图谱与 Code/General 实测已显式延期。
