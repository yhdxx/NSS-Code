# 长期记忆有效性评测

- 状态：`not_run`
- 指标 ID：`long_term_memory`

## 指标定义

比较无记忆、正确检索记忆和错误干扰记忆对用户偏好、项目事实及历史 Workflow 任务的影响。

## 计算公式

- 分组准确率 = 满足预定义答案锚点的运行数 / 分组总运行数
- 正确记忆增益 = 正确记忆准确率 - 无记忆准确率

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
python3 -m tests.eval.modern_runner run-long-term-memory
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

- 结论门禁：三类记忆各至少 10 条、三种对照、每项 3 次；必须单独报告错误记忆造成的退化。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

不可使用量化结论（status=not_run）：尚未执行新版标准评测
