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
  "dataset_sha256": "3ea018c5975c4f1c282df28bded047c491b6122f324a0fc3ab56f5fc7a2680b8",
  "sample_count": 3,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-02T17:11:28+0800",
  "git_commit": "9fb581c0c63e7e7343dd926cbc70b85d95536708",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 1,
  "run_id": "smoke-runtime-context-20260802"
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
      "cache_hit_rate_token_weighted": 0.921948,
      "duration_mean_seconds": 87.433,
      "duration_p95_seconds": 87.433,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 1.0,
      "prompt_tokens_mean": 146889.0,
      "prompt_tokens_p50": 146889.0,
      "prompt_tokens_p95": 146889.0,
      "recovery_call_rate": 1.0,
      "recovery_success_rate": 0.0,
      "request_count_mean": 13.0,
      "run_count": 1,
      "success_rate": 0.0,
      "success_rate_ci95": {
        "high": 0.0,
        "low": 0.0,
        "mean": 0.0
      },
      "tool_calls_mean": 17.0,
      "total_tokens_mean": 152199.0,
      "uncached_prompt_tokens_mean": 11465.0,
      "uncached_prompt_tokens_p50": 11465.0,
      "uncached_prompt_tokens_p95": 11465.0
    },
    "natural": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.733614,
      "duration_mean_seconds": 32.28,
      "duration_p95_seconds": 32.28,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 73979.0,
      "prompt_tokens_p50": 73979.0,
      "prompt_tokens_p95": 73979.0,
      "recovery_call_rate": 1.0,
      "recovery_success_rate": 0.0,
      "request_count_mean": 8.0,
      "run_count": 1,
      "success_rate": 0.0,
      "success_rate_ci95": {
        "high": 0.0,
        "low": 0.0,
        "mean": 0.0
      },
      "tool_calls_mean": 12.0,
      "total_tokens_mean": 75786.0,
      "uncached_prompt_tokens_mean": 19707.0,
      "uncached_prompt_tokens_p50": 19707.0,
      "uncached_prompt_tokens_p95": 19707.0
    },
    "raw": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.112212,
      "duration_mean_seconds": 3.672,
      "duration_p95_seconds": 3.672,
      "false_recovery_rate": 0.0,
      "final_virtualized_rate": 0.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 11407.0,
      "prompt_tokens_p50": 11407.0,
      "prompt_tokens_p95": 11407.0,
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
      "total_tokens_mean": 11548.0,
      "uncached_prompt_tokens_mean": 10127.0,
      "uncached_prompt_tokens_p50": 10127.0,
      "uncached_prompt_tokens_p95": 10127.0
    }
  },
  "case_count": 1,
  "completed_run_count": 3,
  "efficiency_claim_gate_passed": false,
  "paired_reduction_vs_raw": {
    "forced_virtualized": {
      "duration_seconds": {
        "high": -22.81073,
        "low": -22.81073,
        "mean": -22.81073
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": -11.877093,
        "low": -11.877093,
        "mean": -11.877093
      },
      "tool_calls": {
        "high": -2.4,
        "low": -2.4,
        "mean": -2.4
      },
      "total_tokens": {
        "high": -12.179685,
        "low": -12.179685,
        "mean": -12.179685
      },
      "uncached_prompt_tokens": {
        "high": -0.132122,
        "low": -0.132122,
        "mean": -0.132122
      }
    },
    "natural": {
      "duration_seconds": {
        "high": -7.79085,
        "low": -7.79085,
        "mean": -7.79085
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": -5.485404,
        "low": -5.485404,
        "mean": -5.485404
      },
      "tool_calls": {
        "high": -1.4,
        "low": -1.4,
        "mean": -1.4
      },
      "total_tokens": {
        "high": -5.562695,
        "low": -5.562695,
        "mean": -5.562695
      },
      "uncached_prompt_tokens": {
        "high": -0.945986,
        "low": -0.945986,
        "mean": -0.945986
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
      "answer": "After exhaustively recovering the hidden evidence at all offsets, the file `/workspace/evidence/case_001.txt` (6476 chars) contains only filler lines of the form \"preface_line_001_XXX: ordinary operational log with no benchmark answer\" and no actual record code, forbidden module, or adapter path values are present in any recoverable context.",
      "batch_recover_calls": 9,
      "cache_hit_rate": 0.921948,
      "case_id": "runtime_ctx_001_long_distance_fact",
      "category": "long_distance_fact",
      "completion_tokens": 5310,
      "context_store": {
        "context_epochs": 1,
        "context_snapshots": 13,
        "historical_turns": 35,
        "recoverable_contexts": 17
      },
      "context_window": 24000,
      "duration_seconds": 87.433,
      "false_recovery": false,
      "final_context_mode": "virtualized",
      "invalid_tool_calls": 1,
      "passed": false,
      "prompt_cache_hit_tokens": 135424,
      "prompt_cache_miss_tokens": 11465,
      "prompt_hash_change_count": 12,
      "prompt_tokens": 146889,
      "recovery_call_count": 11,
      "recovery_required": true,
      "recovery_success": false,
      "rendered_prompt_hash_change_count": 0,
      "repeat": 0,
      "request_count": 13,
      "runtime_context_hash_change_count": 0,
      "search_recoverable_calls": 1,
      "search_session_calls": 1,
      "status": "passed",
      "strategy": "forced_virtualized",
      "token_records": [
        {
          "completion_tokens": 163,
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
          "prompt_cache_hit_tokens": 1664,
          "prompt_cache_miss_tokens": 5651,
          "prompt_hash": "a2370eb1552e",
          "prompt_tokens": 7315,
          "request_index": 1,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 7478
        },
        {
          "completion_tokens": 325,
          "metadata": {
            "current_turn_tokens": 580,
            "estimated_request_tokens": 6520,
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
          "prompt_cache_miss_tokens": 580,
          "prompt_hash": "52af5c10da4f",
          "prompt_tokens": 7876,
          "request_index": 2,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8201
        },
        {
          "completion_tokens": 182,
          "metadata": {
            "current_turn_tokens": 1034,
            "estimated_request_tokens": 6974,
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
          "prompt_cache_hit_tokens": 7808,
          "prompt_cache_miss_tokens": 785,
          "prompt_hash": "1df6532aeb8e",
          "prompt_tokens": 8593,
          "request_index": 3,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8775
        },
        {
          "completion_tokens": 209,
          "metadata": {
            "current_turn_tokens": 1496,
            "estimated_request_tokens": 7436,
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
          "prompt_cache_hit_tokens": 8704,
          "prompt_cache_miss_tokens": 491,
          "prompt_hash": "56998053dc72",
          "prompt_tokens": 9195,
          "request_index": 4,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9404
        },
        {
          "completion_tokens": 226,
          "metadata": {
            "current_turn_tokens": 1949,
            "estimated_request_tokens": 7889,
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
          "prompt_cache_hit_tokens": 9344,
          "prompt_cache_miss_tokens": 460,
          "prompt_hash": "38342a70439a",
          "prompt_tokens": 9804,
          "request_index": 5,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 10030
        },
        {
          "completion_tokens": 137,
          "metadata": {
            "current_turn_tokens": 2405,
            "estimated_request_tokens": 8345,
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
          "prompt_cache_hit_tokens": 9984,
          "prompt_cache_miss_tokens": 443,
          "prompt_hash": "6fd6ec817858",
          "prompt_tokens": 10427,
          "request_index": 6,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 10564
        },
        {
          "completion_tokens": 322,
          "metadata": {
            "current_turn_tokens": 2509,
            "estimated_request_tokens": 8449,
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
          "prompt_cache_hit_tokens": 10496,
          "prompt_cache_miss_tokens": 95,
          "prompt_hash": "fcd579169ce9",
          "prompt_tokens": 10591,
          "request_index": 7,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 10913
        },
        {
          "completion_tokens": 873,
          "metadata": {
            "current_turn_tokens": 2967,
            "estimated_request_tokens": 8907,
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
          "prompt_cache_hit_tokens": 10880,
          "prompt_cache_miss_tokens": 450,
          "prompt_hash": "15dcc2a2ae0f",
          "prompt_tokens": 11330,
          "request_index": 8,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 12203
        },
        {
          "completion_tokens": 534,
          "metadata": {
            "current_turn_tokens": 3423,
            "estimated_request_tokens": 9363,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 96,
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
          "prompt_cache_hit_tokens": 12160,
          "prompt_cache_miss_tokens": 442,
          "prompt_hash": "a86c8d1dc916",
          "prompt_tokens": 12602,
          "request_index": 9,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 13136
        },
        {
          "completion_tokens": 569,
          "metadata": {
            "current_turn_tokens": 3880,
            "estimated_request_tokens": 9820,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 98,
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
          "prompt_cache_hit_tokens": 13056,
          "prompt_cache_miss_tokens": 495,
          "prompt_hash": "69f0ea1ed91a",
          "prompt_tokens": 13551,
          "request_index": 10,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 14120
        },
        {
          "completion_tokens": 541,
          "metadata": {
            "current_turn_tokens": 4342,
            "estimated_request_tokens": 10282,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 100,
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
          "prompt_cache_hit_tokens": 14080,
          "prompt_cache_miss_tokens": 395,
          "prompt_hash": "3febd64d0b64",
          "prompt_tokens": 14475,
          "request_index": 11,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 15016
        },
        {
          "completion_tokens": 551,
          "metadata": {
            "current_turn_tokens": 4488,
            "estimated_request_tokens": 10428,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 102,
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
          "prompt_cache_hit_tokens": 14976,
          "prompt_cache_miss_tokens": 107,
          "prompt_hash": "b0d4458a99c5",
          "prompt_tokens": 15083,
          "request_index": 12,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 15634
        },
        {
          "completion_tokens": 678,
          "metadata": {
            "current_turn_tokens": 5001,
            "estimated_request_tokens": 10941,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 104,
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
          "prompt_cache_hit_tokens": 14976,
          "prompt_cache_miss_tokens": 1071,
          "prompt_hash": "3f578585d946",
          "prompt_tokens": 16047,
          "request_index": 13,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 16725
        }
      ],
      "tool_call_count": 17,
      "tool_names": [
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "ReadFile",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "SearchSessionHistory",
        "SearchRecoverableContext",
        "BatchRecoverContext"
      ],
      "tools_hash_change_count": 0,
      "total_tokens": 152199
    },
    {
      "answer": "Based on my thorough recovery of the full contents of `/workspace/evidence/case_001.txt` (context_id: `5752f5054c0f4823b157804beffd6dd9`), the file contains only filler text — \"ordinary operational log with no benchmark answer\" preface lines and \"unrelated diagnostic detail\" suffix lines — and does not contain any record code, forbidden module, or adapter path values to report.",
      "batch_recover_calls": 7,
      "cache_hit_rate": 0.733614,
      "case_id": "runtime_ctx_001_long_distance_fact",
      "category": "long_distance_fact",
      "completion_tokens": 1807,
      "context_store": {
        "context_epochs": 1,
        "context_snapshots": 8,
        "historical_turns": 35,
        "recoverable_contexts": 12
      },
      "context_window": 12000,
      "duration_seconds": 32.28,
      "false_recovery": false,
      "final_context_mode": "virtualized",
      "invalid_tool_calls": 0,
      "passed": false,
      "prompt_cache_hit_tokens": 54272,
      "prompt_cache_miss_tokens": 19707,
      "prompt_hash_change_count": 7,
      "prompt_tokens": 73979,
      "recovery_call_count": 7,
      "recovery_required": true,
      "recovery_success": false,
      "rendered_prompt_hash_change_count": 0,
      "repeat": 0,
      "request_count": 8,
      "runtime_context_hash_change_count": 0,
      "search_recoverable_calls": 0,
      "search_session_calls": 0,
      "status": "passed",
      "strategy": "natural",
      "token_records": [
        {
          "completion_tokens": 172,
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
          "prompt_hash": "efe6cf83f5d6",
          "prompt_tokens": 7316,
          "request_index": 1,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 7488
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
          "prompt_cache_miss_tokens": 593,
          "prompt_hash": "1d3c766e8e07",
          "prompt_tokens": 7889,
          "request_index": 2,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8056
        },
        {
          "completion_tokens": 143,
          "metadata": {
            "current_turn_tokens": 1064,
            "estimated_request_tokens": 7004,
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
          "prompt_cache_hit_tokens": 7936,
          "prompt_cache_miss_tokens": 538,
          "prompt_hash": "438c33b17e12",
          "prompt_tokens": 8474,
          "request_index": 3,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8617
        },
        {
          "completion_tokens": 368,
          "metadata": {
            "current_turn_tokens": 1534,
            "estimated_request_tokens": 7474,
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
          "prompt_cache_miss_tokens": 478,
          "prompt_hash": "5c6bf065c5e9",
          "prompt_tokens": 9054,
          "request_index": 4,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9422
        },
        {
          "completion_tokens": 341,
          "metadata": {
            "current_turn_tokens": 55,
            "estimated_request_tokens": 8022,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 4544,
            "message_count": 89,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a85fc773b005",
            "rendered_prompt_tokens": 151,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 84,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 7296,
          "prompt_cache_miss_tokens": 2224,
          "prompt_hash": "b036f3534f7f",
          "prompt_tokens": 9520,
          "request_index": 5,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9861
        },
        {
          "completion_tokens": 244,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 8479,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 4999,
            "message_count": 91,
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
          "prompt_cache_miss_tokens": 2740,
          "prompt_hash": "ac09d472830c",
          "prompt_tokens": 10036,
          "request_index": 6,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 10280
        },
        {
          "completion_tokens": 177,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 8940,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 5460,
            "message_count": 93,
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
          "prompt_cache_hit_tokens": 9344,
          "prompt_cache_miss_tokens": 1207,
          "prompt_hash": "2ba701a98cee",
          "prompt_tokens": 10551,
          "request_index": 7,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 10728
        },
        {
          "completion_tokens": 195,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 9454,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 5974,
            "message_count": 96,
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
          "prompt_cache_hit_tokens": 1280,
          "prompt_cache_miss_tokens": 9859,
          "prompt_hash": "87b6f4ed89ec",
          "prompt_tokens": 11139,
          "request_index": 8,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 11334
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
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext"
      ],
      "tools_hash_change_count": 0,
      "total_tokens": 75786
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
