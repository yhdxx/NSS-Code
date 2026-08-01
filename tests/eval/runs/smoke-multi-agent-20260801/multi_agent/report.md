# Multi-Agent 协作 A/B 评测

- 状态：`insufficient_sample`
- 指标 ID：`multi_agent`

## 指标定义

比较 direct 与 Planner-Scheduler-Test 协作流程在分层代码任务上的成功率、耗时、token、工具调用和冲突/重试情况。

## 计算公式

- 任务成功率 = 验收测试通过运行数 / 总运行数
- 相对开销 = Multi-Agent 均值 / Direct 均值

## 数据集与样本

```json
{
  "dataset_path": "tests/eval/datasets/multi_agent_tasks.jsonl",
  "dataset_sha256": "5213c55b18c41f1db7c0edd33f197e479103f92ddee00793f7edda4609c4aa7a",
  "sample_count": 2,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-01T20:18:05+0800",
  "git_commit": "1c5e2b27423b9618a1c76f0a1c4b38542011420e",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 1,
  "run_id": "smoke-multi-agent-20260801"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-multi-agent --dataset tests/eval/datasets/multi_agent_tasks.jsonl --repeats 1
```

## 结果与置信区间

```json
{
  "by_mode": {
    "direct": {
      "duration_mean_ci95": {
        "high": 14.693,
        "low": 14.693,
        "mean": 14.693
      },
      "duration_mean_seconds": 14.693,
      "duration_p50_seconds": 14.693,
      "duration_p95_seconds": 14.693,
      "failed_or_timeout_count": 0,
      "run_count": 1,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 6.0,
      "tool_calls_mean_ci95": {
        "high": 6.0,
        "low": 6.0,
        "mean": 6.0
      },
      "total_tokens_mean": 26933.0,
      "total_tokens_mean_ci95": {
        "high": 26933.0,
        "low": 26933.0,
        "mean": 26933.0
      }
    },
    "multi_agent": {
      "duration_mean_ci95": {
        "high": 150.924,
        "low": 150.924,
        "mean": 150.924
      },
      "duration_mean_seconds": 150.924,
      "duration_p50_seconds": 150.924,
      "duration_p95_seconds": 150.924,
      "failed_or_timeout_count": 0,
      "run_count": 1,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 28.0,
      "tool_calls_mean_ci95": {
        "high": 28.0,
        "low": 28.0,
        "mean": 28.0
      },
      "total_tokens_mean": 0.0,
      "total_tokens_mean_ci95": {
        "high": 0.0,
        "low": 0.0,
        "mean": 0.0
      }
    }
  },
  "case_count": 1,
  "reason": "requires 30 cases and 3 repeats per mode",
  "repeats": 1,
  "run_count": 2
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

不可使用量化结论（status=insufficient_sample）：requires 30 cases and 3 repeats per mode
