# Code / General 工作模式 A/B 评测

- 状态：`insufficient_sample`
- 指标 ID：`code_general_ab`

## 指标定义

在相同模型、任务和工具 schema 下，对比 Code 图谱导航与 General 自主探索的任务成功率和执行成本。

## 计算公式

- 任务成功率 = 验收测试通过的运行数 / 总运行数
- 成本降幅 = (General 均值 - Code 均值) / General 均值

## 数据集与样本

```json
{
  "dataset_path": "tests/eval/datasets/code_general_tasks.jsonl",
  "dataset_sha256": "5213c55b18c41f1db7c0edd33f197e479103f92ddee00793f7edda4609c4aa7a",
  "sample_count": 2,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-01T19:56:28+0800",
  "git_commit": "1c5e2b27423b9618a1c76f0a1c4b38542011420e",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 1,
  "run_id": "smoke-code-general-20260801"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-code-general-ab --dataset tests/eval/datasets/code_general_tasks.jsonl --repeats 1
```

## 结果与置信区间

```json
{
  "by_mode": {
    "code": {
      "duration_mean_seconds": 19.114,
      "graph_tool_calls_mean": 1.0,
      "invalid_tool_calls_mean": 1.0,
      "prompt_tokens_mean": 36894.0,
      "readfile_visible_bytes_mean": 112.0,
      "repeated_tool_calls_mean": 0.0,
      "run_count": 1,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 7.0,
      "total_tokens_mean": 37622.0
    },
    "general": {
      "duration_mean_seconds": 18.422,
      "graph_tool_calls_mean": 0.0,
      "invalid_tool_calls_mean": 1.0,
      "prompt_tokens_mean": 28756.0,
      "readfile_visible_bytes_mean": 112.0,
      "repeated_tool_calls_mean": 0.0,
      "run_count": 1,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 6.0,
      "total_tokens_mean": 29486.0
    }
  },
  "case_count": 1,
  "code_cost_reductions": {
    "prompt_tokens": -0.283002,
    "readfile_visible_bytes": 0.0,
    "tool_calls": -0.166667,
    "total_tokens": -0.275928
  },
  "code_success_rate_delta": 0.0,
  "efficiency_claim_gate_passed": false,
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

- 结论门禁：至少 30 个任务、每模式 3 次；Code 成功率不得比 General 低超过 5 个百分点，且 token 或读取/工具调用成本显著下降，才可表述为提高效率。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

不可使用量化结论（status=insufficient_sample）：requires 30 cases and 3 repeats per mode
