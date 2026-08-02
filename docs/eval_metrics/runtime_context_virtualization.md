# 真实 Runtime 上下文虚拟化评测

- 状态：`insufficient_sample`
- 指标 ID：`runtime_context_virtualization`

## 指标定义

通过真实 MemoryRuntime、工具 schema、可恢复工具输出和 ask_deepseek 调用链，对比 raw、forced_virtualized 与 natural 策略的质量、token 成本、缓存命中和恢复行为。

## 计算公式

- 任务成功率 = 正确回答隐藏历史证据锚点的运行数 / 总运行数
- 未缓存输入降幅 = (Raw 未缓存输入 token - 候选未缓存输入 token) / Raw 未缓存输入 token
- 缓存命中率 = prompt_cache_hit_tokens / (prompt_cache_hit_tokens + prompt_cache_miss_tokens)
- 恢复成功率 = 需要恢复且恢复后答对的运行数 / 需要恢复的运行数

## 数据集与样本

```json
{
  "dataset_path": "tests/eval/datasets/runtime_context_virtualization_cases.jsonl",
  "dataset_sha256": "7d98b83333f45c5bf177632b2a43740db68a8ba26d0dd1db8a20bc299ae24f86",
  "sample_count": 3,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-02T17:26:22+0800",
  "git_commit": "9fb581c0c63e7e7343dd926cbc70b85d95536708",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 1,
  "run_id": "smoke-runtime-context-v4-20260802"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-runtime-context-virtualization --dataset tests/eval/datasets/runtime_context_virtualization_cases.jsonl --repeats 1
```

## 结果与置信区间

```json
{
  "by_strategy": {
    "forced_virtualized": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.808091,
      "duration_mean_seconds": 6.363,
      "duration_p95_seconds": 6.363,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 15523.0,
      "prompt_tokens_p50": 15523.0,
      "prompt_tokens_p95": 15523.0,
      "recovery_call_rate": 1.0,
      "recovery_success_rate": 1.0,
      "request_count_mean": 2.0,
      "run_count": 1,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 6.0,
      "total_tokens_mean": 15794.0,
      "uncached_prompt_tokens_mean": 2979.0,
      "uncached_prompt_tokens_p50": 2979.0,
      "uncached_prompt_tokens_p95": 2979.0
    },
    "natural": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.807363,
      "duration_mean_seconds": 5.542,
      "duration_p95_seconds": 5.542,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 15537.0,
      "prompt_tokens_p50": 15537.0,
      "prompt_tokens_p95": 15537.0,
      "recovery_call_rate": 1.0,
      "recovery_success_rate": 1.0,
      "request_count_mean": 2.0,
      "run_count": 1,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 6.0,
      "total_tokens_mean": 15797.0,
      "uncached_prompt_tokens_mean": 2993.0,
      "uncached_prompt_tokens_p50": 2993.0,
      "uncached_prompt_tokens_p95": 2993.0
    },
    "raw": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.995487,
      "duration_mean_seconds": 6.492,
      "duration_p95_seconds": 6.492,
      "false_recovery_rate": 0.0,
      "final_virtualized_rate": 0.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 10415.0,
      "prompt_tokens_p50": 10415.0,
      "prompt_tokens_p95": 10415.0,
      "recovery_call_rate": 0.0,
      "recovery_success_rate": null,
      "request_count_mean": 1.0,
      "run_count": 1,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 5.0,
      "total_tokens_mean": 10610.0,
      "uncached_prompt_tokens_mean": 47.0,
      "uncached_prompt_tokens_p50": 47.0,
      "uncached_prompt_tokens_p95": 47.0
    }
  },
  "case_count": 1,
  "completed_run_count": 3,
  "efficiency_claim_gate_passed": false,
  "paired_reduction_vs_raw": {
    "forced_virtualized": {
      "duration_seconds": {
        "high": 0.019871,
        "low": 0.019871,
        "mean": 0.019871
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": -0.490446,
        "low": -0.490446,
        "mean": -0.490446
      },
      "tool_calls": {
        "high": -0.2,
        "low": -0.2,
        "mean": -0.2
      },
      "total_tokens": {
        "high": -0.488596,
        "low": -0.488596,
        "mean": -0.488596
      },
      "uncached_prompt_tokens": {
        "high": -62.382979,
        "low": -62.382979,
        "mean": -62.382979
      }
    },
    "natural": {
      "duration_seconds": {
        "high": 0.146334,
        "low": 0.146334,
        "mean": 0.146334
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": -0.491791,
        "low": -0.491791,
        "mean": -0.491791
      },
      "tool_calls": {
        "high": -0.2,
        "low": -0.2,
        "mean": -0.2
      },
      "total_tokens": {
        "high": -0.488878,
        "low": -0.488878,
        "mean": -0.488878
      },
      "uncached_prompt_tokens": {
        "high": -62.680851,
        "low": -62.680851,
        "mean": -62.680851
      }
    }
  },
  "quality_gate_passed": false,
  "reason": "requires 30 cases, 3 repeats, 3 strategies, and no failed API calls",
  "repeats": 1,
  "run_count": 3,
  "strategies": [
    "raw",
    "forced_virtualized",
    "natural"
  ],
  "uncached_reduction_gate_passed": false
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

- 结论门禁：至少 30 条长会话轨迹、raw/forced_virtualized/natural 三策略、每策略 3 次；Virtualized 成功率不得比 Raw 低超过 5 个百分点，且未缓存输入 token 必须下降。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

不可使用量化结论（status=insufficient_sample）：requires 30 cases, 3 repeats, 3 strategies, and no failed API calls
