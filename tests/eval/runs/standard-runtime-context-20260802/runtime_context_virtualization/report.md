# 真实 Runtime 上下文虚拟化评测

- 状态：`passed`
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
  "sample_count": 270,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-02T17:29:11+0800",
  "git_commit": "131d1ec505269ea0f0dbb7e1357d1d55840c7aca",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 3,
  "run_id": "standard-runtime-context-20260802"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-runtime-context-virtualization --dataset tests/eval/datasets/runtime_context_virtualization_cases.jsonl --repeats 3
```

## 结果与置信区间

```json
{
  "by_strategy": {
    "forced_virtualized": {
      "api_completed_count": 90,
      "cache_hit_rate_token_weighted": 0.813144,
      "duration_mean_seconds": 6.2923,
      "duration_p95_seconds": 6.9963,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 0.011111,
      "prompt_tokens_mean": 16736.566667,
      "prompt_tokens_p50": 15671.5,
      "prompt_tokens_p95": 15871.3,
      "recovery_call_rate": 1.0,
      "recovery_success_rate": 0.988889,
      "request_count_mean": 2.1,
      "run_count": 90,
      "success_rate": 0.988889,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 0.966667,
        "mean": 0.988889
      },
      "tool_calls_mean": 6.122222,
      "total_tokens_mean": 17015.966667,
      "uncached_prompt_tokens_mean": 3127.322222,
      "uncached_prompt_tokens_p50": 3054.0,
      "uncached_prompt_tokens_p95": 3293.75
    },
    "natural": {
      "api_completed_count": 90,
      "cache_hit_rate_token_weighted": 0.806857,
      "duration_mean_seconds": 5.876522,
      "duration_p95_seconds": 6.9924,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 0.011111,
      "prompt_tokens_mean": 16116.077778,
      "prompt_tokens_p50": 15674.5,
      "prompt_tokens_p95": 15869.0,
      "recovery_call_rate": 1.0,
      "recovery_success_rate": 0.977778,
      "request_count_mean": 2.055556,
      "run_count": 90,
      "success_rate": 0.977778,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 0.944444,
        "mean": 0.977778
      },
      "tool_calls_mean": 6.066667,
      "total_tokens_mean": 16390.477778,
      "uncached_prompt_tokens_mean": 3112.7,
      "uncached_prompt_tokens_p50": 3121.0,
      "uncached_prompt_tokens_p95": 3204.0
    },
    "raw": {
      "api_completed_count": 90,
      "cache_hit_rate_token_weighted": 0.825494,
      "duration_mean_seconds": 4.107267,
      "duration_p95_seconds": 5.12795,
      "false_recovery_rate": 0.0,
      "final_virtualized_rate": 0.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 10481.966667,
      "prompt_tokens_p50": 10477.0,
      "prompt_tokens_p95": 10576.0,
      "recovery_call_rate": 0.0,
      "recovery_success_rate": null,
      "request_count_mean": 1.0,
      "run_count": 90,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 5.0,
      "total_tokens_mean": 10671.377778,
      "uncached_prompt_tokens_mean": 1829.166667,
      "uncached_prompt_tokens_p50": 80.0,
      "uncached_prompt_tokens_p95": 5423.0
    }
  },
  "case_count": 30,
  "completed_run_count": 270,
  "efficiency_claim_gate_passed": false,
  "paired_reduction_vs_raw": {
    "forced_virtualized": {
      "duration_seconds": {
        "high": -0.349079,
        "low": -0.869498,
        "mean": -0.531992
      },
      "paired_run_count": 90,
      "prompt_tokens": {
        "high": -0.494997,
        "low": -0.799439,
        "mean": -0.596701
      },
      "tool_calls": {
        "high": -0.2,
        "low": -0.273333,
        "mean": -0.224444
      },
      "total_tokens": {
        "high": -0.49129,
        "low": -0.800226,
        "mean": -0.594543
      },
      "uncached_prompt_tokens": {
        "high": -0.341891,
        "low": -1.355511,
        "mean": -0.709698
      }
    },
    "natural": {
      "duration_seconds": {
        "high": -0.324064,
        "low": -0.614909,
        "mean": -0.430762
      },
      "paired_run_count": 90,
      "prompt_tokens": {
        "high": -0.495139,
        "low": -0.614354,
        "mean": -0.537505
      },
      "tool_calls": {
        "high": -0.2,
        "low": -0.237834,
        "mean": -0.213333
      },
      "total_tokens": {
        "high": -0.492595,
        "low": -0.615192,
        "mean": -0.535929
      },
      "uncached_prompt_tokens": {
        "high": -0.32494,
        "low": -1.320009,
        "mean": -0.701704
      }
    }
  },
  "quality_gate_passed": true,
  "reason": "",
  "repeats": 3,
  "resume_conclusion": "真实 Runtime 虚拟化在 30 条长会话轨迹、三策略、每策略 3 次中基本保持答案质量，但未缓存输入和总 token 成本未下降；不可表述为端到端降本。",
  "run_count": 270,
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
  "count": 3,
  "examples": [
    {
      "answer": "The hidden evidence from case 012 cannot be recovered. The original file `/workspace/evidence/case_012.txt` no longer exists on disk, and the virtualized context_id `47a491bcb57841f7a73e32e9927bd4b0` returned `not_found` from `BatchRecoverContext` on two separate recovery attempts. The only remaining traces are metadata tags — the keyword `CRITICAL_RECORD` and the related file `adapter_012.py` — but neither constitutes the actual record code, forbidden module, or adapter path values that were in the original 1,950-character content.",
      "batch_recover_calls": 3,
      "cache_hit_rate": 0.932926,
      "case_id": "runtime_ctx_012_large_tool_output",
      "category": "large_tool_output",
      "completion_tokens": 3209,
      "context_store": {
        "context_epochs": 1,
        "context_snapshots": 11,
        "historical_turns": 34,
        "recoverable_contexts": 17
      },
      "context_window": 24000,
      "duration_seconds": 63.173,
      "false_recovery": false,
      "final_context_mode": "virtualized",
      "invalid_tool_calls": 1,
      "passed": false,
      "prompt_cache_hit_tokens": 103552,
      "prompt_cache_miss_tokens": 7445,
      "prompt_hash_change_count": 10,
      "prompt_tokens": 110997,
      "recovery_call_count": 9,
      "recovery_required": true,
      "recovery_success": false,
      "rendered_prompt_hash_change_count": 0,
      "repeat": 1,
      "request_count": 11,
      "runtime_context_hash_change_count": 0,
      "search_recoverable_calls": 3,
      "search_session_calls": 3,
      "status": "passed",
      "strategy": "forced_virtualized",
      "token_records": [
        {
          "completion_tokens": 168,
          "metadata": {
            "current_turn_tokens": 146,
            "estimated_request_tokens": 6039,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2470,
            "message_count": 78,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 5248,
          "prompt_cache_miss_tokens": 2066,
          "prompt_hash": "ee176756adee",
          "prompt_tokens": 7314,
          "request_index": 1,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 7482
        },
        {
          "completion_tokens": 193,
          "metadata": {
            "current_turn_tokens": 373,
            "estimated_request_tokens": 6266,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2470,
            "message_count": 80,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 7296,
          "prompt_cache_miss_tokens": 370,
          "prompt_hash": "6a84ebe7625e",
          "prompt_tokens": 7666,
          "request_index": 2,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 7859
        },
        {
          "completion_tokens": 119,
          "metadata": {
            "current_turn_tokens": 611,
            "estimated_request_tokens": 6504,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2470,
            "message_count": 83,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 7808,
          "prompt_cache_miss_tokens": 143,
          "prompt_hash": "6a8603c00a10",
          "prompt_tokens": 7951,
          "request_index": 3,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8070
        },
        {
          "completion_tokens": 114,
          "metadata": {
            "current_turn_tokens": 1064,
            "estimated_request_tokens": 6957,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2470,
            "message_count": 85,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 8064,
          "prompt_cache_miss_tokens": 365,
          "prompt_hash": "21b26372c990",
          "prompt_tokens": 8429,
          "request_index": 4,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8543
        },
        {
          "completion_tokens": 178,
          "metadata": {
            "current_turn_tokens": 1506,
            "estimated_request_tokens": 7399,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2470,
            "message_count": 87,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 8448,
          "prompt_cache_miss_tokens": 486,
          "prompt_hash": "dc750aafb717",
          "prompt_tokens": 8934,
          "request_index": 5,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9112
        },
        {
          "completion_tokens": 319,
          "metadata": {
            "current_turn_tokens": 1957,
            "estimated_request_tokens": 7850,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2470,
            "message_count": 89,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 9088,
          "prompt_cache_miss_tokens": 383,
          "prompt_hash": "77e072776772",
          "prompt_tokens": 9471,
          "request_index": 6,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9790
        },
        {
          "completion_tokens": 135,
          "metadata": {
            "current_turn_tokens": 2172,
            "estimated_request_tokens": 8065,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2470,
            "message_count": 92,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 9728,
          "prompt_cache_miss_tokens": 140,
          "prompt_hash": "2c32e2c0aa57",
          "prompt_tokens": 9868,
          "request_index": 7,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 10003
        },
        {
          "completion_tokens": 148,
          "metadata": {
            "current_turn_tokens": 2627,
            "estimated_request_tokens": 8520,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2470,
            "message_count": 94,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 9984,
          "prompt_cache_miss_tokens": 435,
          "prompt_hash": "c2529c171434",
          "prompt_tokens": 10419,
          "request_index": 8,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 10567
        },
        {
          "completion_tokens": 342,
          "metadata": {
            "current_turn_tokens": 4909,
            "estimated_request_tokens": 10802,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2470,
            "message_count": 96,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 10496,
          "prompt_cache_miss_tokens": 2420,
          "prompt_hash": "8444db94302a",
          "prompt_tokens": 12916,
          "request_index": 9,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 13258
        },
        {
          "completion_tokens": 769,
          "metadata": {
            "current_turn_tokens": 5139,
            "estimated_request_tokens": 11032,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2470,
            "message_count": 98,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 13184,
          "prompt_cache_miss_tokens": 261,
          "prompt_hash": "b97c5830ed5e",
          "prompt_tokens": 13445,
          "request_index": 10,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 14214
        },
        {
          "completion_tokens": 724,
          "metadata": {
            "current_turn_tokens": 5590,
            "estimated_request_tokens": 11483,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2470,
            "message_count": 100,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 14208,
          "prompt_cache_miss_tokens": 376,
          "prompt_hash": "ddd52623bb04",
          "prompt_tokens": 14584,
          "request_index": 11,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 15308
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
        "ReadFile",
        "SearchRecoverableContext",
        "SearchSessionHistory",
        "GetRecentConversationTurns",
        "SearchSessionHistory",
        "Glob",
        "SearchRecoverableContext",
        "SearchRecoverableContext",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "SearchSessionHistory"
      ],
      "tools_hash_change_count": 0,
      "total_tokens": 114206
    },
    {
      "answer": "The recovery failed — the context_id `58307222b3f245ec8c113fdbe7a4f54d` returned \"not_found\" and searching for related metadata also yielded no results, so I cannot retrieve the record code, forbidden module, or adapter path from the hidden evidence for case 017.",
      "batch_recover_calls": 1,
      "cache_hit_rate": 0.863119,
      "case_id": "runtime_ctx_017_large_tool_output",
      "category": "large_tool_output",
      "completion_tokens": 510,
      "context_store": {
        "context_epochs": 1,
        "context_snapshots": 3,
        "historical_turns": 39,
        "recoverable_contexts": 7
      },
      "context_window": 9000,
      "duration_seconds": 11.722,
      "false_recovery": false,
      "final_context_mode": "virtualized",
      "invalid_tool_calls": 0,
      "passed": false,
      "prompt_cache_hit_tokens": 20096,
      "prompt_cache_miss_tokens": 3187,
      "prompt_hash_change_count": 2,
      "prompt_tokens": 23283,
      "recovery_call_count": 2,
      "recovery_required": true,
      "recovery_success": false,
      "rendered_prompt_hash_change_count": 0,
      "repeat": 1,
      "request_count": 3,
      "runtime_context_hash_change_count": 0,
      "search_recoverable_calls": 1,
      "search_session_calls": 0,
      "status": "passed",
      "strategy": "natural",
      "token_records": [
        {
          "completion_tokens": 153,
          "metadata": {
            "current_turn_tokens": 146,
            "estimated_request_tokens": 6290,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2721,
            "message_count": 88,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 5248,
          "prompt_cache_miss_tokens": 2232,
          "prompt_hash": "e37103040393",
          "prompt_tokens": 7480,
          "request_index": 1,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 7633
        },
        {
          "completion_tokens": 110,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 6568,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 3088,
            "message_count": 91,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 168,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 7424,
          "prompt_cache_miss_tokens": 402,
          "prompt_hash": "829f9b85a9bc",
          "prompt_tokens": 7826,
          "request_index": 2,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 7936
        },
        {
          "completion_tokens": 247,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 6713,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 3233,
            "message_count": 93,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 168,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 7424,
          "prompt_cache_miss_tokens": 553,
          "prompt_hash": "1150734255ce",
          "prompt_tokens": 7977,
          "request_index": 3,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8224
        }
      ],
      "tool_call_count": 7,
      "tool_names": [
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "BatchRecoverContext",
        "SearchRecoverableContext"
      ],
      "tools_hash_change_count": 0,
      "total_tokens": 23793
    },
    {
      "answer": "The hidden evidence from case 009 cannot be recovered. The original file `/workspace/evidence/case_009.txt` was read but its output was virtualized behind context_id `a3b5060530ed4ea7a524d4dcd03cc109`. Both attempting to recover that context ID and re-reading the file have failed — the context ID returned \"not_found\" and the file no longer exists on disk. I have no visible evidence containing the record code, forbidden module, or adapter path to report.",
      "batch_recover_calls": 1,
      "cache_hit_rate": 0.918731,
      "case_id": "runtime_ctx_009_long_distance_fact",
      "category": "long_distance_fact",
      "completion_tokens": 1631,
      "context_store": {
        "context_epochs": 1,
        "context_snapshots": 6,
        "historical_turns": 37,
        "recoverable_contexts": 11
      },
      "context_window": 9000,
      "duration_seconds": 31.511,
      "false_recovery": false,
      "final_context_mode": "virtualized",
      "invalid_tool_calls": 1,
      "passed": false,
      "prompt_cache_hit_tokens": 44032,
      "prompt_cache_miss_tokens": 3895,
      "prompt_hash_change_count": 5,
      "prompt_tokens": 47927,
      "recovery_call_count": 3,
      "recovery_required": true,
      "recovery_success": false,
      "rendered_prompt_hash_change_count": 0,
      "repeat": 2,
      "request_count": 6,
      "runtime_context_hash_change_count": 0,
      "search_recoverable_calls": 1,
      "search_session_calls": 1,
      "status": "passed",
      "strategy": "natural",
      "token_records": [
        {
          "completion_tokens": 174,
          "metadata": {
            "current_turn_tokens": 146,
            "estimated_request_tokens": 6201,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2632,
            "message_count": 84,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 134,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 5248,
          "prompt_cache_miss_tokens": 2165,
          "prompt_hash": "0d3b18c1bc54",
          "prompt_tokens": 7413,
          "request_index": 1,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 7587
        },
        {
          "completion_tokens": 108,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 6478,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2998,
            "message_count": 87,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 168,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 7296,
          "prompt_cache_miss_tokens": 462,
          "prompt_hash": "afeb7fe0615c",
          "prompt_tokens": 7758,
          "request_index": 2,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 7866
        },
        {
          "completion_tokens": 157,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 6623,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 3143,
            "message_count": 89,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 168,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 7680,
          "prompt_cache_miss_tokens": 228,
          "prompt_hash": "09812f577580",
          "prompt_tokens": 7908,
          "request_index": 3,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8065
        },
        {
          "completion_tokens": 177,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 6719,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 3239,
            "message_count": 91,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 168,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 7808,
          "prompt_cache_miss_tokens": 204,
          "prompt_hash": "0889b0045177",
          "prompt_tokens": 8012,
          "request_index": 4,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8189
        },
        {
          "completion_tokens": 254,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 6881,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 3401,
            "message_count": 94,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 168,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 7936,
          "prompt_cache_miss_tokens": 253,
          "prompt_hash": "a0e4ba98c4a5",
          "prompt_tokens": 8189,
          "request_index": 5,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8443
        },
        {
          "completion_tokens": 761,
          "metadata": {
            "current_turn_tokens": 57,
            "estimated_request_tokens": 7342,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 3862,
            "message_count": 96,
            "rendered_prompt_format_version": "runtime-context-v2",
            "rendered_prompt_hash": "a05c371c74e5",
            "rendered_prompt_tokens": 168,
            "runtime_context_hash": "942ea94dcfc9",
            "runtime_context_tokens": 17,
            "stored_user_prompt_tokens": 98,
            "temporary_system_tokens": 1,
            "tool_count": 17,
            "tools_tokens": 2618
          },
          "model": "deepseek-v4-pro",
          "prompt_cache_hit_tokens": 8064,
          "prompt_cache_miss_tokens": 583,
          "prompt_hash": "82779e81ccf1",
          "prompt_tokens": 8647,
          "request_index": 6,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9408
        }
      ],
      "tool_call_count": 11,
      "tool_names": [
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "BatchRecoverContext",
        "SearchRecoverableContext",
        "ReadFile",
        "Glob",
        "Grep",
        "SearchSessionHistory"
      ],
      "tools_hash_change_count": 0,
      "total_tokens": 49558
    }
  ]
}
```

## 局限与有效性威胁

- 结论门禁：至少 30 条长会话轨迹、raw/forced_virtualized/natural 三策略、每策略 3 次；Virtualized 成功率不得比 Raw 低超过 5 个百分点，且未缓存输入 token 必须下降。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

真实 Runtime 虚拟化在 30 条长会话轨迹、三策略、每策略 3 次中基本保持答案质量，但未缓存输入和总 token 成本未下降；不可表述为端到端降本。
