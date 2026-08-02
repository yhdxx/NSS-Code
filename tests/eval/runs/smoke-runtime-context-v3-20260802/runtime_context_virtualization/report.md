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
  "generated_at": "2026-08-02T17:21:39+0800",
  "git_commit": "9fb581c0c63e7e7343dd926cbc70b85d95536708",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 1,
  "run_id": "smoke-runtime-context-v3-20260802"
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
      "cache_hit_rate_token_weighted": 0.929816,
      "duration_mean_seconds": 52.693,
      "duration_p95_seconds": 52.693,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 1.0,
      "prompt_tokens_mean": 73649.0,
      "prompt_tokens_p50": 73649.0,
      "prompt_tokens_p95": 73649.0,
      "recovery_call_rate": 1.0,
      "recovery_success_rate": 1.0,
      "request_count_mean": 8.0,
      "run_count": 1,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 12.0,
      "total_tokens_mean": 75475.0,
      "uncached_prompt_tokens_mean": 5169.0,
      "uncached_prompt_tokens_p50": 5169.0,
      "uncached_prompt_tokens_p95": 5169.0
    },
    "natural": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.602013,
      "duration_mean_seconds": 115.694,
      "duration_p95_seconds": 115.694,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 1.0,
      "prompt_tokens_mean": 83347.0,
      "prompt_tokens_p50": 83347.0,
      "prompt_tokens_p95": 83347.0,
      "recovery_call_rate": 1.0,
      "recovery_success_rate": 0.0,
      "request_count_mean": 9.0,
      "run_count": 1,
      "success_rate": 0.0,
      "success_rate_ci95": {
        "high": 0.0,
        "low": 0.0,
        "mean": 0.0
      },
      "tool_calls_mean": 13.0,
      "total_tokens_mean": 87297.0,
      "uncached_prompt_tokens_mean": 33171.0,
      "uncached_prompt_tokens_p50": 33171.0,
      "uncached_prompt_tokens_p95": 33171.0
    },
    "raw": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.503889,
      "duration_mean_seconds": 6.11,
      "duration_p95_seconds": 6.11,
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
      "total_tokens_mean": 10615.0,
      "uncached_prompt_tokens_mean": 5167.0,
      "uncached_prompt_tokens_p50": 5167.0,
      "uncached_prompt_tokens_p95": 5167.0
    }
  },
  "case_count": 1,
  "completed_run_count": 3,
  "efficiency_claim_gate_passed": false,
  "paired_reduction_vs_raw": {
    "forced_virtualized": {
      "duration_seconds": {
        "high": -7.624059,
        "low": -7.624059,
        "mean": -7.624059
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": -6.071435,
        "low": -6.071435,
        "mean": -6.071435
      },
      "tool_calls": {
        "high": -1.4,
        "low": -1.4,
        "mean": -1.4
      },
      "total_tokens": {
        "high": -6.110221,
        "low": -6.110221,
        "mean": -6.110221
      },
      "uncached_prompt_tokens": {
        "high": -0.000387,
        "low": -0.000387,
        "mean": -0.000387
      }
    },
    "natural": {
      "duration_seconds": {
        "high": -17.935188,
        "low": -17.935188,
        "mean": -17.935188
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": -7.002592,
        "low": -7.002592,
        "mean": -7.002592
      },
      "tool_calls": {
        "high": -1.6,
        "low": -1.6,
        "mean": -1.6
      },
      "total_tokens": {
        "high": -7.223928,
        "low": -7.223928,
        "mean": -7.223928
      },
      "uncached_prompt_tokens": {
        "high": -5.419779,
        "low": -5.419779,
        "mean": -5.419779
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
  "count": 2,
  "examples": [
    {
      "answer": "The case 001 record code is **VIRT_KEY_001**, the forbidden module is **billing_001**, and the adapter path is **adapter_001.py**.",
      "batch_recover_calls": 6,
      "cache_hit_rate": 0.929816,
      "case_id": "runtime_ctx_001_long_distance_fact",
      "category": "long_distance_fact",
      "completion_tokens": 1826,
      "context_store": {
        "context_epochs": 1,
        "context_snapshots": 8,
        "historical_turns": 35,
        "recoverable_contexts": 12
      },
      "context_window": 24000,
      "duration_seconds": 52.693,
      "false_recovery": false,
      "final_context_mode": "virtualized",
      "invalid_tool_calls": 1,
      "passed": true,
      "prompt_cache_hit_tokens": 68480,
      "prompt_cache_miss_tokens": 5169,
      "prompt_hash_change_count": 7,
      "prompt_tokens": 73649,
      "recovery_call_count": 6,
      "recovery_required": true,
      "recovery_success": true,
      "rendered_prompt_hash_change_count": 0,
      "repeat": 0,
      "request_count": 8,
      "runtime_context_hash_change_count": 0,
      "search_recoverable_calls": 0,
      "search_session_calls": 0,
      "status": "passed",
      "strategy": "forced_virtualized",
      "token_records": [
        {
          "completion_tokens": 206,
          "metadata": {
            "current_turn_tokens": 132,
            "estimated_request_tokens": 6072,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 80,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 120,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 5248,
          "prompt_cache_miss_tokens": 2068,
          "prompt_hash": "326fd3ba2e8d",
          "prompt_tokens": 7316,
          "request_index": 1,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 7522
        },
        {
          "completion_tokens": 167,
          "metadata": {
            "current_turn_tokens": 594,
            "estimated_request_tokens": 6534,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 82,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 120,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 7296,
          "prompt_cache_miss_tokens": 626,
          "prompt_hash": "d133d1be98e6",
          "prompt_tokens": 7922,
          "request_index": 2,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8089
        },
        {
          "completion_tokens": 150,
          "metadata": {
            "current_turn_tokens": 1061,
            "estimated_request_tokens": 7001,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 84,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 120,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 8064,
          "prompt_cache_miss_tokens": 447,
          "prompt_hash": "cf9b6ac3de9f",
          "prompt_tokens": 8511,
          "request_index": 3,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8661
        },
        {
          "completion_tokens": 194,
          "metadata": {
            "current_turn_tokens": 1173,
            "estimated_request_tokens": 7113,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 86,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 120,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 8576,
          "prompt_cache_miss_tokens": 112,
          "prompt_hash": "1614c5462fbd",
          "prompt_tokens": 8688,
          "request_index": 4,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8882
        },
        {
          "completion_tokens": 181,
          "metadata": {
            "current_turn_tokens": 1631,
            "estimated_request_tokens": 7571,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 88,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 120,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 8832,
          "prompt_cache_miss_tokens": 451,
          "prompt_hash": "9afa7edded02",
          "prompt_tokens": 9283,
          "request_index": 5,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9464
        },
        {
          "completion_tokens": 354,
          "metadata": {
            "current_turn_tokens": 2085,
            "estimated_request_tokens": 8025,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 90,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 120,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 9344,
          "prompt_cache_miss_tokens": 521,
          "prompt_hash": "3d7417bd5bf9",
          "prompt_tokens": 9865,
          "request_index": 6,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 10219
        },
        {
          "completion_tokens": 445,
          "metadata": {
            "current_turn_tokens": 2553,
            "estimated_request_tokens": 8493,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 92,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 120,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 10112,
          "prompt_cache_miss_tokens": 534,
          "prompt_hash": "3c455559b8d7",
          "prompt_tokens": 10646,
          "request_index": 7,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 11091
        },
        {
          "completion_tokens": 129,
          "metadata": {
            "current_turn_tokens": 2931,
            "estimated_request_tokens": 8871,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 94,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 120,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 11008,
          "prompt_cache_miss_tokens": 410,
          "prompt_hash": "a5a819ed5efc",
          "prompt_tokens": 11418,
          "request_index": 8,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 11547
        }
      ],
      "tool_call_count": 12,
      "tool_names": [
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "ReadFile",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext"
      ],
      "tools_hash_change_count": 0,
      "total_tokens": 75475
    },
    {
      "answer": "The record code, forbidden module, and adapter path remain inaccessible — despite multiple recovery attempts through the nested context chain (`ebc4cce7566444258e106db8ccb7e4e6` → `be7be43c59b04d3cb376b9e5bb8058a5` → `cb7adaee2b2f47ac8b8e0ae6f7e7bd81`), every preview only renders the suffix diagnostic lines (16–24) while the prefix containing the three requested fields is persistently truncated. The evidence file itself no longer exists at `/workspace/evidence/case_001.txt`.",
      "batch_recover_calls": 6,
      "cache_hit_rate": 0.602013,
      "case_id": "runtime_ctx_001_long_distance_fact",
      "category": "long_distance_fact",
      "completion_tokens": 3950,
      "context_store": {
        "context_epochs": 1,
        "context_snapshots": 9,
        "historical_turns": 35,
        "recoverable_contexts": 13
      },
      "context_window": 9000,
      "duration_seconds": 115.694,
      "false_recovery": false,
      "final_context_mode": "virtualized",
      "invalid_tool_calls": 1,
      "passed": false,
      "prompt_cache_hit_tokens": 50176,
      "prompt_cache_miss_tokens": 33171,
      "prompt_hash_change_count": 8,
      "prompt_tokens": 83347,
      "recovery_call_count": 7,
      "recovery_required": true,
      "recovery_success": false,
      "rendered_prompt_hash_change_count": 0,
      "repeat": 0,
      "request_count": 9,
      "runtime_context_hash_change_count": 0,
      "search_recoverable_calls": 1,
      "search_session_calls": 0,
      "status": "passed",
      "strategy": "natural",
      "token_records": [
        {
          "completion_tokens": 158,
          "metadata": {
            "current_turn_tokens": 132,
            "estimated_request_tokens": 6072,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 80,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 120,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 5248,
          "prompt_cache_miss_tokens": 2069,
          "prompt_hash": "dd3a90633bd4",
          "prompt_tokens": 7317,
          "request_index": 1,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 7475
        },
        {
          "completion_tokens": 230,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 6571,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 3091,
            "message_count": 83,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 154,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 7296,
          "prompt_cache_miss_tokens": 589,
          "prompt_hash": "81a9891cef93",
          "prompt_tokens": 7885,
          "request_index": 2,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8115
        },
        {
          "completion_tokens": 673,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 7055,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 3575,
            "message_count": 85,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 154,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 7808,
          "prompt_cache_miss_tokens": 629,
          "prompt_hash": "aa6fca44c5e7",
          "prompt_tokens": 8437,
          "request_index": 3,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9110
        },
        {
          "completion_tokens": 150,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 7553,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 4073,
            "message_count": 87,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 154,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 8320,
          "prompt_cache_miss_tokens": 681,
          "prompt_hash": "4c1a3c840f23",
          "prompt_tokens": 9001,
          "request_index": 4,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9151
        },
        {
          "completion_tokens": 146,
          "metadata": {
            "current_turn_tokens": 58,
            "estimated_request_tokens": 7653,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 4172,
            "message_count": 89,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 155,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 8320,
          "prompt_cache_miss_tokens": 786,
          "prompt_hash": "917415d6edf7",
          "prompt_tokens": 9106,
          "request_index": 5,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9252
        },
        {
          "completion_tokens": 736,
          "metadata": {
            "current_turn_tokens": 58,
            "estimated_request_tokens": 8140,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 4659,
            "message_count": 91,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 155,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 8832,
          "prompt_cache_miss_tokens": 823,
          "prompt_hash": "9b7bf38fa04d",
          "prompt_tokens": 9655,
          "request_index": 6,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 10391
        },
        {
          "completion_tokens": 657,
          "metadata": {
            "current_turn_tokens": 58,
            "estimated_request_tokens": 8647,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 5166,
            "message_count": 94,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 155,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 1408,
          "prompt_cache_miss_tokens": 8830,
          "prompt_hash": "345bab9877da",
          "prompt_tokens": 10238,
          "request_index": 7,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 10895
        },
        {
          "completion_tokens": 450,
          "metadata": {
            "current_turn_tokens": 58,
            "estimated_request_tokens": 9107,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 5626,
            "message_count": 96,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 155,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 1408,
          "prompt_cache_miss_tokens": 9363,
          "prompt_hash": "c9cb5faa4e47",
          "prompt_tokens": 10771,
          "request_index": 8,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 11221
        },
        {
          "completion_tokens": 750,
          "metadata": {
            "current_turn_tokens": 58,
            "estimated_request_tokens": 9257,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 5776,
            "message_count": 98,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 155,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 1536,
          "prompt_cache_miss_tokens": 9401,
          "prompt_hash": "968e1d984d83",
          "prompt_tokens": 10937,
          "request_index": 9,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 11687
        }
      ],
      "tool_call_count": 13,
      "tool_names": [
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "ReadFile",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "SearchRecoverableContext"
      ],
      "tools_hash_change_count": 0,
      "total_tokens": 87297
    }
  ]
}
```

## 局限与有效性威胁

- 结论门禁：至少 30 条长会话轨迹、raw/forced_virtualized/natural 三策略、每策略 3 次；Virtualized 成功率不得比 Raw 低超过 5 个百分点，且未缓存输入 token 必须下降。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

不可使用量化结论（status=insufficient_sample）：requires 30 cases, 3 repeats, 3 strategies, and no failed API calls
