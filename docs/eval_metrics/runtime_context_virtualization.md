# 真实 Runtime 上下文虚拟化评测

- 状态：`insufficient_sample`
- 指标 ID：`runtime_context_virtualization`

## 指标定义

通过真实 MemoryRuntime、工具 schema、可恢复工具输出和 ask_deepseek 调用链，对比 raw 质量参考、Claude-style 压缩基线、forced_virtualized 与 natural 策略的质量、token 成本、缓存命中和恢复行为。

## 计算公式

- 任务成功率 = 正确回答隐藏历史证据锚点的运行数 / 总运行数
- Raw 仅作为无压缩质量参考，不作为降本基线
- 相对 Claude 压缩基线的未缓存输入降幅 = (Claude-style baseline 未缓存输入 token - 候选未缓存输入 token) / Claude-style baseline 未缓存输入 token
- 缓存命中率 = prompt_cache_hit_tokens / (prompt_cache_hit_tokens + prompt_cache_miss_tokens)
- 恢复成功率 = 需要恢复且恢复后答对的运行数 / 需要恢复的运行数

## 数据集与样本

```json
{
  "dataset_path": "tests/eval/datasets/runtime_context_virtualization_cases.jsonl",
  "dataset_sha256": "7d98b83333f45c5bf177632b2a43740db68a8ba26d0dd1db8a20bc299ae24f86",
  "sample_count": 4,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-02T18:27:29+0800",
  "git_commit": "5430e174eb831537994ea5e49b7d3f468d0d6e05",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 1,
  "run_id": "smoke-runtime-context-claude-20260802"
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
    "claude_compression_baseline": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.241924,
      "duration_mean_seconds": 5.308,
      "duration_p95_seconds": 5.308,
      "false_recovery_rate": 0.0,
      "final_virtualized_rate": 0.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 5820.0,
      "prompt_tokens_p50": 5820.0,
      "prompt_tokens_p95": 5820.0,
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
      "tool_calls_mean": 0.0,
      "total_tokens_mean": 6097.0,
      "uncached_prompt_tokens_mean": 4412.0,
      "uncached_prompt_tokens_p50": 4412.0,
      "uncached_prompt_tokens_p95": 4412.0
    },
    "forced_virtualized": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.803022,
      "duration_mean_seconds": 5.1,
      "duration_p95_seconds": 5.1,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 15621.0,
      "prompt_tokens_p50": 15621.0,
      "prompt_tokens_p95": 15621.0,
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
      "total_tokens_mean": 15874.0,
      "uncached_prompt_tokens_mean": 3077.0,
      "uncached_prompt_tokens_p50": 3077.0,
      "uncached_prompt_tokens_p95": 3077.0
    },
    "natural": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.803587,
      "duration_mean_seconds": 5.128,
      "duration_p95_seconds": 5.128,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 15610.0,
      "prompt_tokens_p50": 15610.0,
      "prompt_tokens_p95": 15610.0,
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
      "total_tokens_mean": 15872.0,
      "uncached_prompt_tokens_mean": 3066.0,
      "uncached_prompt_tokens_p50": 3066.0,
      "uncached_prompt_tokens_p95": 3066.0
    },
    "raw": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.490046,
      "duration_mean_seconds": 4.38,
      "duration_p95_seconds": 4.38,
      "false_recovery_rate": 0.0,
      "final_virtualized_rate": 0.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 10448.0,
      "prompt_tokens_p50": 10448.0,
      "prompt_tokens_p95": 10448.0,
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
      "total_tokens_mean": 10652.0,
      "uncached_prompt_tokens_mean": 5328.0,
      "uncached_prompt_tokens_p50": 5328.0,
      "uncached_prompt_tokens_p95": 5328.0
    }
  },
  "case_count": 1,
  "claude_baseline_quality_gate_passed": false,
  "completed_run_count": 4,
  "cost_baseline_strategy": "claude_compression_baseline",
  "efficiency_claim_gate_passed": false,
  "paired_delta_vs_raw_quality_reference": {
    "claude_compression_baseline": {
      "duration_seconds": {
        "high": -0.211872,
        "low": -0.211872,
        "mean": -0.211872
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": 0.442956,
        "low": 0.442956,
        "mean": 0.442956
      },
      "tool_calls": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "total_tokens": {
        "high": 0.427619,
        "low": 0.427619,
        "mean": 0.427619
      },
      "uncached_prompt_tokens": {
        "high": 0.171922,
        "low": 0.171922,
        "mean": 0.171922
      }
    },
    "forced_virtualized": {
      "duration_seconds": {
        "high": -0.164384,
        "low": -0.164384,
        "mean": -0.164384
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": -0.495119,
        "low": -0.495119,
        "mean": -0.495119
      },
      "tool_calls": {
        "high": -0.2,
        "low": -0.2,
        "mean": -0.2
      },
      "total_tokens": {
        "high": -0.490237,
        "low": -0.490237,
        "mean": -0.490237
      },
      "uncached_prompt_tokens": {
        "high": 0.422485,
        "low": 0.422485,
        "mean": 0.422485
      }
    },
    "natural": {
      "duration_seconds": {
        "high": -0.170776,
        "low": -0.170776,
        "mean": -0.170776
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": -0.494066,
        "low": -0.494066,
        "mean": -0.494066
      },
      "tool_calls": {
        "high": -0.2,
        "low": -0.2,
        "mean": -0.2
      },
      "total_tokens": {
        "high": -0.490049,
        "low": -0.490049,
        "mean": -0.490049
      },
      "uncached_prompt_tokens": {
        "high": 0.42455,
        "low": 0.42455,
        "mean": 0.42455
      }
    }
  },
  "paired_reduction_vs_claude_compression_baseline": {
    "forced_virtualized": {
      "duration_seconds": {
        "high": 0.039186,
        "low": 0.039186,
        "mean": 0.039186
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": -1.684021,
        "low": -1.684021,
        "mean": -1.684021
      },
      "tool_calls": {
        "high": null,
        "low": null,
        "mean": null
      },
      "total_tokens": {
        "high": -1.603576,
        "low": -1.603576,
        "mean": -1.603576
      },
      "uncached_prompt_tokens": {
        "high": 0.302584,
        "low": 0.302584,
        "mean": 0.302584
      }
    },
    "natural": {
      "duration_seconds": {
        "high": 0.033911,
        "low": 0.033911,
        "mean": 0.033911
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": -1.682131,
        "low": -1.682131,
        "mean": -1.682131
      },
      "tool_calls": {
        "high": null,
        "low": null,
        "mean": null
      },
      "total_tokens": {
        "high": -1.603247,
        "low": -1.603247,
        "mean": -1.603247
      },
      "uncached_prompt_tokens": {
        "high": 0.305077,
        "low": 0.305077,
        "mean": 0.305077
      }
    }
  },
  "quality_gate_passed": false,
  "quality_reference_strategy": "raw",
  "reason": "requires 30 cases, 3 repeats, 4 strategies, and no failed API calls",
  "repeats": 1,
  "run_count": 4,
  "strategies": [
    "raw",
    "claude_compression_baseline",
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

- 结论门禁：至少 30 条长会话轨迹、raw/claude_compression_baseline/forced_virtualized/natural 四策略、每策略 3 次；Virtualized 成功率不得比 Raw 低超过 5 个百分点；Claude-style baseline 也需通过质量门禁；降本结论只看相对 Claude-style baseline 的未缓存输入 token 是否下降。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

不可使用量化结论（status=insufficient_sample）：requires 30 cases, 3 repeats, 4 strategies, and no failed API calls
