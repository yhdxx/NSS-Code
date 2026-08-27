# 100K 上下文压缩策略评测

- 状态：`insufficient_sample`
- 指标 ID：`context_compression_100k`

## 测试对象

- 当前 MemoryRuntime 的工具输出外置、ContextEpoch 和可恢复冷历史渲染链路。
- 80% token 压力触发的一次性工程摘要，并保留压缩点最近 10 个用户轮次及后续消息。
- 不压缩 Raw 质量参考；所有策略使用相同系统提示和最终工具 schema。

## 指标定义

在统一 100K token 上下文窗口中，对比 Raw、当前自然虚拟化与 80% 触发的摘要 + 最近 10 轮策略。

## 计算公式

- 任务成功率 = 包含全部预定义答案锚点的运行数 / API 完成运行数
- 最终 Prompt 压缩率 = 1 - 候选最终可见 Prompt 估算 token / Raw 最终 Prompt 估算 token
- 累计 token 节省率 = 1 - 候选累计 token / 对照累计 token
- 缓存命中率 = prompt_cache_hit_tokens / (prompt_cache_hit_tokens + prompt_cache_miss_tokens)

## 测试方案

- 每条轨迹按项目 token 估算器构造到 90%（约 90K），摘要基线在首次达到 80% 的完整轮次边界压缩。
- 当前策略使用真实 MemoryRuntime 和恢复工具；Raw 与摘要基线直接回答可见上下文，不执行恢复工具。
- 每个 case/策略重复运行，累计摘要、最终回答和恢复调用的真实 API token；失败不从分母剔除。

## 数据集与样本

```json
{
  "dataset_path": "tests/eval/datasets/context_compression_100k_cases.jsonl",
  "dataset_sha256": "5f2d3f533dfc5c3c2bc147fccea2ad8e4ef9049165fedd062d4fef32b33de737",
  "sample_count": 32,
  "tool_schema_hash": "ba7189c376e71df34d845b0405648a4489bd0b27760dc64d53ab3b4515c8545c"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-26T22:52:16+0800",
  "git_commit": "f1a309995f4fe3e382061426f845de98127ac451",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 2,
  "run_id": "context-compression-100k-20260826-final"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-context-compression-100k --dataset tests/eval/datasets/context_compression_100k_cases.jsonl --repeats 2
```

## 结果与置信区间

```json
{
  "baseline_trigger_ratio": 0.8,
  "by_strategy": {
    "claude_compression_baseline": {
      "api_completed_count": 8,
      "cache_hit_rate_token_weighted": 0.816362,
      "duration_mean_seconds": 2.692375,
      "duration_p95_seconds": 4.1481,
      "false_recovery_rate": 0.0,
      "final_virtualized_rate": 0.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 2273.5,
      "prompt_tokens_p50": 2270.5,
      "prompt_tokens_p95": 2296.0,
      "recovery_call_rate": 0.0,
      "recovery_success_rate": null,
      "request_count_mean": 1.0,
      "run_count": 8,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 0.0,
      "total_tokens_mean": 2401.25,
      "uncached_prompt_tokens_mean": 417.5,
      "uncached_prompt_tokens_p50": 420.5,
      "uncached_prompt_tokens_p95": 755.1
    },
    "forced_virtualized": {
      "api_completed_count": 8,
      "cache_hit_rate_token_weighted": 0.873378,
      "duration_mean_seconds": 8.27725,
      "duration_p95_seconds": 22.93515,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 0.125,
      "prompt_tokens_mean": 24548.375,
      "prompt_tokens_p50": 17112.5,
      "prompt_tokens_p95": 55969.5,
      "recovery_call_rate": 1.0,
      "recovery_success_rate": 1.0,
      "request_count_mean": 2.75,
      "run_count": 8,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 9.25,
      "total_tokens_mean": 24982.25,
      "uncached_prompt_tokens_mean": 3108.375,
      "uncached_prompt_tokens_p50": 2870.5,
      "uncached_prompt_tokens_p95": 4305.4
    },
    "natural": {
      "api_completed_count": 8,
      "cache_hit_rate_token_weighted": 0.833678,
      "duration_mean_seconds": 4.788125,
      "duration_p95_seconds": 5.3989,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 17100.125,
      "prompt_tokens_p50": 17090.0,
      "prompt_tokens_p95": 17237.75,
      "recovery_call_rate": 1.0,
      "recovery_success_rate": 1.0,
      "request_count_mean": 2.0,
      "run_count": 8,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 8.0,
      "total_tokens_mean": 17327.875,
      "uncached_prompt_tokens_mean": 2844.125,
      "uncached_prompt_tokens_p50": 2850.5,
      "uncached_prompt_tokens_p95": 2961.6
    },
    "raw": {
      "api_completed_count": 8,
      "cache_hit_rate_token_weighted": 0.529109,
      "duration_mean_seconds": 7.239375,
      "duration_p95_seconds": 12.28755,
      "false_recovery_rate": 0.0,
      "final_virtualized_rate": 0.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 97915.5,
      "prompt_tokens_p50": 97905.5,
      "prompt_tokens_p95": 97985.0,
      "recovery_call_rate": 0.0,
      "recovery_success_rate": null,
      "request_count_mean": 1.0,
      "run_count": 8,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 7.0,
      "total_tokens_mean": 98108.75,
      "uncached_prompt_tokens_mean": 46107.5,
      "uncached_prompt_tokens_p50": 46090.5,
      "uncached_prompt_tokens_p95": 92210.65
    }
  },
  "case_count": 4,
  "claude_baseline_quality_gate_passed": false,
  "cold_start_paired_reduction_vs_claude_compression_baseline": {
    "forced_virtualized": {
      "duration_seconds": {
        "high": -0.668741,
        "low": -5.272984,
        "mean": -2.863865
      },
      "paired_run_count": 4,
      "prompt_tokens": {
        "high": -6.492621,
        "low": -26.191695,
        "mean": -13.078403
      },
      "tool_calls": {
        "high": null,
        "low": null,
        "mean": null
      },
      "total_tokens": {
        "high": -6.213919,
        "low": -24.348539,
        "mean": -12.502739
      },
      "uncached_prompt_tokens": {
        "high": -2.869858,
        "low": -5.090571,
        "mean": -3.652542
      }
    },
    "natural": {
      "duration_seconds": {
        "high": -0.152992,
        "low": -1.041966,
        "mean": -0.513654
      },
      "paired_run_count": 4,
      "prompt_tokens": {
        "high": -6.487261,
        "low": -6.541782,
        "mean": -6.510886
      },
      "tool_calls": {
        "high": null,
        "low": null,
        "mean": null
      },
      "total_tokens": {
        "high": -5.912966,
        "low": -6.332626,
        "mean": -6.153075
      },
      "uncached_prompt_tokens": {
        "high": -2.724436,
        "low": -3.060249,
        "mean": -2.888814
      }
    }
  },
  "completed_run_count": 32,
  "context_window": 100000,
  "cost_baseline_strategy": "claude_compression_baseline",
  "cost_gate_basis": "repeat_0_cold_start_uncached_prompt_tokens",
  "efficiency_claim_gate_passed": false,
  "paired_delta_vs_raw_quality_reference": {
    "claude_compression_baseline": {
      "duration_seconds": {
        "high": 0.709234,
        "low": 0.499206,
        "mean": 0.628093
      },
      "paired_run_count": 8,
      "prompt_tokens": {
        "high": 0.976881,
        "low": 0.976674,
        "mean": 0.976781
      },
      "tool_calls": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "total_tokens": {
        "high": 0.975879,
        "low": 0.975022,
        "mean": 0.975525
      },
      "uncached_prompt_tokens": {
        "high": 0.991805,
        "low": 0.984883,
        "mean": 0.990945
      }
    },
    "forced_virtualized": {
      "duration_seconds": {
        "high": 0.420299,
        "low": -0.925015,
        "mean": -0.143365
      },
      "paired_run_count": 8,
      "prompt_tokens": {
        "high": 0.826057,
        "low": 0.596641,
        "mean": 0.74929
      },
      "tool_calls": {
        "high": -0.142857,
        "low": -0.678571,
        "mean": -0.321429
      },
      "total_tokens": {
        "high": 0.824059,
        "low": 0.588764,
        "mean": 0.745362
      },
      "uncached_prompt_tokens": {
        "high": 0.958551,
        "low": 0.758632,
        "mean": 0.932584
      }
    },
    "natural": {
      "duration_seconds": {
        "high": 0.517112,
        "low": 0.004115,
        "mean": 0.3386
      },
      "paired_run_count": 8,
      "prompt_tokens": {
        "high": 0.826066,
        "low": 0.824686,
        "mean": 0.825358
      },
      "tool_calls": {
        "high": -0.142857,
        "low": -0.142857,
        "mean": -0.142857
      },
      "total_tokens": {
        "high": 0.824109,
        "low": 0.822651,
        "mean": 0.823381
      },
      "uncached_prompt_tokens": {
        "high": 0.964237,
        "low": 0.756709,
        "mean": 0.938315
      }
    }
  },
  "paired_reduction_vs_claude_compression_baseline": {
    "forced_virtualized": {
      "duration_seconds": {
        "high": -0.824493,
        "low": -3.737626,
        "mean": -2.07433
      },
      "paired_run_count": 8,
      "prompt_tokens": {
        "high": -6.50233,
        "low": -16.366949,
        "mean": -9.797614
      },
      "tool_calls": {
        "high": null,
        "low": null,
        "mean": null
      },
      "total_tokens": {
        "high": -6.239157,
        "low": -15.527623,
        "mean": -9.403852
      },
      "uncached_prompt_tokens": {
        "high": -3.968323,
        "low": -14.749836,
        "mean": -6.44521
      }
    },
    "natural": {
      "duration_seconds": {
        "high": -0.425546,
        "low": -1.189663,
        "mean": -0.778402
      },
      "paired_run_count": 8,
      "prompt_tokens": {
        "high": -6.501312,
        "low": -6.542065,
        "mean": -6.521498
      },
      "tool_calls": {
        "high": null,
        "low": null,
        "mean": null
      },
      "total_tokens": {
        "high": -6.081161,
        "low": -6.30451,
        "mean": -6.216189
      },
      "uncached_prompt_tokens": {
        "high": -3.399585,
        "low": -14.598083,
        "mean": -5.812275
      }
    }
  },
  "quality_gate_passed": false,
  "quality_reference_strategy": "raw",
  "reason": "requires 30 cases, 3 repeats, 4 strategies, and no failed API calls",
  "repeats": 2,
  "run_count": 32,
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
  "count": 1,
  "examples": [
    {
      "answer": "The early record code is `V100_RULE`, the forbidden module is `auth_core`, and the adapter path is `auth_adapter.py`.",
      "batch_recover_calls": 1,
      "cache_hit_rate": 0.934684,
      "case_id": "ctx100k_02_early_user_constraint",
      "category": "early_user_constraint",
      "completion_tokens": 1870,
      "context_store": {
        "context_epochs": 1,
        "context_snapshots": 8,
        "historical_turns": 38,
        "recoverable_contexts": 18
      },
      "context_window": 100000,
      "duration_seconds": 32.347,
      "false_recovery": false,
      "final_context_mode": "virtualized",
      "invalid_tool_calls": 1,
      "passed": true,
      "prompt_cache_hit_tokens": 71808,
      "prompt_cache_miss_tokens": 5018,
      "prompt_hash_change_count": 7,
      "prompt_tokens": 76826,
      "recovery_call_count": 5,
      "recovery_required": true,
      "recovery_success": true,
      "rendered_prompt_hash_change_count": 0,
      "repeat": 0,
      "request_count": 8,
      "runtime_context_hash_change_count": 0,
      "search_recoverable_calls": 2,
      "search_session_calls": 2,
      "status": "passed",
      "strategy": "forced_virtualized",
      "token_records": [
        {
          "completion_tokens": 170,
          "metadata": {
            "budget_estimated_tokens": 10218,
            "current_turn_tokens": 274,
            "estimated_request_tokens": 10219,
            "fixed_system_tokens": 2192,
            "historical_messages_tokens": 2946,
            "message_count": 90,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "b2dfcaf5da34",
            "rendered_prompt_tokens": 256,
            "runtime_context_hash": "0ba1fee95067",
            "runtime_context_tokens": 154,
            "stored_user_prompt_tokens": 85,
            "temporary_system_tokens": 1,
            "tool_count": 14,
            "tools_tokens": 4806
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 5760,
          "prompt_cache_miss_tokens": 2573,
          "prompt_hash": "41e0a7d76edb",
          "prompt_tokens": 8333,
          "request_index": 1,
          "tools_hash": "46e4e30333da",
          "total_tokens": 8503
        },
        {
          "completion_tokens": 123,
          "metadata": {
            "budget_estimated_tokens": 10462,
            "current_turn_tokens": 518,
            "estimated_request_tokens": 10463,
            "fixed_system_tokens": 2192,
            "historical_messages_tokens": 2946,
            "message_count": 92,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "b2dfcaf5da34",
            "rendered_prompt_tokens": 256,
            "runtime_context_hash": "0ba1fee95067",
            "runtime_context_tokens": 154,
            "stored_user_prompt_tokens": 85,
            "temporary_system_tokens": 1,
            "tool_count": 14,
            "tools_tokens": 4806
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 8448,
          "prompt_cache_miss_tokens": 242,
          "prompt_hash": "04aa4c0b2dbb",
          "prompt_tokens": 8690,
          "request_index": 2,
          "tools_hash": "46e4e30333da",
          "total_tokens": 8813
        },
        {
          "completion_tokens": 167,
          "metadata": {
            "budget_estimated_tokens": 10576,
            "current_turn_tokens": 632,
            "estimated_request_tokens": 10577,
            "fixed_system_tokens": 2192,
            "historical_messages_tokens": 2946,
            "message_count": 94,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "b2dfcaf5da34",
            "rendered_prompt_tokens": 256,
            "runtime_context_hash": "0ba1fee95067",
            "runtime_context_tokens": 154,
            "stored_user_prompt_tokens": 85,
            "temporary_system_tokens": 1,
            "tool_count": 14,
            "tools_tokens": 4806
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 8704,
          "prompt_cache_miss_tokens": 139,
          "prompt_hash": "14001588645e",
          "prompt_tokens": 8843,
          "request_index": 3,
          "tools_hash": "46e4e30333da",
          "total_tokens": 9010
        },
        {
          "completion_tokens": 145,
          "metadata": {
            "budget_estimated_tokens": 10808,
            "current_turn_tokens": 864,
            "estimated_request_tokens": 10809,
            "fixed_system_tokens": 2192,
            "historical_messages_tokens": 2946,
            "message_count": 97,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "b2dfcaf5da34",
            "rendered_prompt_tokens": 256,
            "runtime_context_hash": "0ba1fee95067",
            "runtime_context_tokens": 154,
            "stored_user_prompt_tokens": 85,
            "temporary_system_tokens": 1,
            "tool_count": 14,
            "tools_tokens": 4806
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 8960,
          "prompt_cache_miss_tokens": 128,
          "prompt_hash": "c1942149e94b",
          "prompt_tokens": 9088,
          "request_index": 4,
          "tools_hash": "46e4e30333da",
          "total_tokens": 9233
        },
        {
          "completion_tokens": 132,
          "metadata": {
            "budget_estimated_tokens": 11061,
            "current_turn_tokens": 1117,
            "estimated_request_tokens": 11062,
            "fixed_system_tokens": 2192,
            "historical_messages_tokens": 2946,
            "message_count": 100,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "b2dfcaf5da34",
            "rendered_prompt_tokens": 256,
            "runtime_context_hash": "0ba1fee95067",
            "runtime_context_tokens": 154,
            "stored_user_prompt_tokens": 85,
            "temporary_system_tokens": 1,
            "tool_count": 14,
            "tools_tokens": 4806
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 9216,
          "prompt_cache_miss_tokens": 164,
          "prompt_hash": "7f33fb6b39e8",
          "prompt_tokens": 9380,
          "request_index": 5,
          "tools_hash": "46e4e30333da",
          "total_tokens": 9512
        },
        {
          "completion_tokens": 471,
          "metadata": {
            "budget_estimated_tokens": 11518,
            "current_turn_tokens": 1574,
            "estimated_request_tokens": 11519,
            "fixed_system_tokens": 2192,
            "historical_messages_tokens": 2946,
            "message_count": 102,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "b2dfcaf5da34",
            "rendered_prompt_tokens": 256,
            "runtime_context_hash": "0ba1fee95067",
            "runtime_context_tokens": 154,
            "stored_user_prompt_tokens": 85,
            "temporary_system_tokens": 1,
            "tool_count": 14,
            "tools_tokens": 4806
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 9472,
          "prompt_cache_miss_tokens": 392,
          "prompt_hash": "6bb2654d0edf",
          "prompt_tokens": 9864,
          "request_index": 6,
          "tools_hash": "46e4e30333da",
          "total_tokens": 10335
        },
        {
          "completion_tokens": 325,
          "metadata": {
            "budget_estimated_tokens": 12087,
            "current_turn_tokens": 2143,
            "estimated_request_tokens": 12088,
            "fixed_system_tokens": 2192,
            "historical_messages_tokens": 2946,
            "message_count": 105,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "b2dfcaf5da34",
            "rendered_prompt_tokens": 256,
            "runtime_context_hash": "0ba1fee95067",
            "runtime_context_tokens": 154,
            "stored_user_prompt_tokens": 85,
            "temporary_system_tokens": 1,
            "tool_count": 14,
            "tools_tokens": 4806
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 10240,
          "prompt_cache_miss_tokens": 506,
          "prompt_hash": "da35e3064149",
          "prompt_tokens": 10746,
          "request_index": 7,
          "tools_hash": "46e4e30333da",
          "total_tokens": 11071
        },
        {
          "completion_tokens": 337,
          "metadata": {
            "budget_estimated_tokens": 12965,
            "current_turn_tokens": 3021,
            "estimated_request_tokens": 12966,
            "fixed_system_tokens": 2192,
            "historical_messages_tokens": 2946,
            "message_count": 108,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "b2dfcaf5da34",
            "rendered_prompt_tokens": 256,
            "runtime_context_hash": "0ba1fee95067",
            "runtime_context_tokens": 154,
            "stored_user_prompt_tokens": 85,
            "temporary_system_tokens": 1,
            "tool_count": 14,
            "tools_tokens": 4806
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 11008,
          "prompt_cache_miss_tokens": 874,
          "prompt_hash": "50b35fda55fd",
          "prompt_tokens": 11882,
          "request_index": 8,
          "tools_hash": "46e4e30333da",
          "total_tokens": 12219
        }
      ],
      "tool_call_count": 18,
      "tool_names": [
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "BatchRecoverContext",
        "ReadFile",
        "Glob",
        "SearchRecoverableContext",
        "Glob",
        "Glob",
        "SearchSessionHistory",
        "SearchSessionHistory",
        "SearchRecoverableContext",
        "Grep",
        "Grep"
      ],
      "tools_hash_change_count": 0,
      "total_tokens": 78696
    }
  ]
}
```

## 局限与有效性威胁

- 结论门禁：至少 4 类长会话、每策略 2 次；必须报告摘要与恢复开销。该规模只形成 100K 探索性证据，不作为 1M 直接证明。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

不可使用量化结论（status=insufficient_sample）：requires 30 cases, 3 repeats, 4 strategies, and no failed API calls
