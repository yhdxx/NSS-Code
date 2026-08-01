# Multi-Agent 协作 A/B 评测

- 状态：`not_run`
- 指标 ID：`multi_agent`

## 指标定义

比较 direct 与 Planner-Scheduler-Test 协作流程在分层代码任务上的成功率、耗时、token、工具调用和冲突/重试情况。

## 计算公式

- 任务成功率 = 验收测试通过运行数 / 总运行数
- 相对开销 = Multi-Agent 均值 / Direct 均值

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
python3 -m tests.eval.modern_runner run-multi-agent
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

- 结论门禁：至少 30 个任务、每模式 3 次；成功率收益和复杂任务收益明确前，只表述实现了状态机协作与冲突控制。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

不可使用量化结论（status=not_run）：尚未执行新版标准评测
