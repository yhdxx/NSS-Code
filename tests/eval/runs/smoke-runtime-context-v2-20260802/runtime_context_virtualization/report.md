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
  "dataset_sha256": "d77336ce5fa2865a9c8aa133176527034acbc52e1c4fb922a60583667778a524",
  "sample_count": 3,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-02T17:17:13+0800",
  "git_commit": "9fb581c0c63e7e7343dd926cbc70b85d95536708",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 1,
  "run_id": "smoke-runtime-context-v2-20260802"
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
      "cache_hit_rate_token_weighted": 0.942895,
      "duration_mean_seconds": 57.101,
      "duration_p95_seconds": 57.101,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 1.0,
      "prompt_tokens_mean": 95298.0,
      "prompt_tokens_p50": 95298.0,
      "prompt_tokens_p95": 95298.0,
      "recovery_call_rate": 1.0,
      "recovery_success_rate": 1.0,
      "request_count_mean": 10.0,
      "run_count": 1,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 15.0,
      "total_tokens_mean": 97530.0,
      "uncached_prompt_tokens_mean": 5442.0,
      "uncached_prompt_tokens_p50": 5442.0,
      "uncached_prompt_tokens_p95": 5442.0
    },
    "natural": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.893186,
      "duration_mean_seconds": 27.292,
      "duration_p95_seconds": 27.292,
      "false_recovery_rate": null,
      "final_virtualized_rate": 1.0,
      "invalid_tool_calls_mean": 0.0,
      "prompt_tokens_mean": 41989.0,
      "prompt_tokens_p50": 41989.0,
      "prompt_tokens_p95": 41989.0,
      "recovery_call_rate": 1.0,
      "recovery_success_rate": 1.0,
      "request_count_mean": 5.0,
      "run_count": 1,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 9.0,
      "total_tokens_mean": 42988.0,
      "uncached_prompt_tokens_mean": 4485.0,
      "uncached_prompt_tokens_p50": 4485.0,
      "uncached_prompt_tokens_p95": 4485.0
    },
    "raw": {
      "api_completed_count": 1,
      "cache_hit_rate_token_weighted": 0.503889,
      "duration_mean_seconds": 6.188,
      "duration_p95_seconds": 6.188,
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
      "total_tokens_mean": 10642.0,
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
        "high": -8.227699,
        "low": -8.227699,
        "mean": -8.227699
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": -8.150072,
        "low": -8.150072,
        "mean": -8.150072
      },
      "tool_calls": {
        "high": -2.0,
        "low": -2.0,
        "mean": -2.0
      },
      "total_tokens": {
        "high": -8.164631,
        "low": -8.164631,
        "mean": -8.164631
      },
      "uncached_prompt_tokens": {
        "high": -0.053222,
        "low": -0.053222,
        "mean": -0.053222
      }
    },
    "natural": {
      "duration_seconds": {
        "high": -3.410472,
        "low": -3.410472,
        "mean": -3.410472
      },
      "paired_run_count": 1,
      "prompt_tokens": {
        "high": -3.031589,
        "low": -3.031589,
        "mean": -3.031589
      },
      "tool_calls": {
        "high": -0.8,
        "low": -0.8,
        "mean": -0.8
      },
      "total_tokens": {
        "high": -3.039466,
        "low": -3.039466,
        "mean": -3.039466
      },
      "uncached_prompt_tokens": {
        "high": 0.131991,
        "low": 0.131991,
        "mean": 0.131991
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
  "count": 1,
  "examples": [
    {
      "answer": "The hidden evidence was originally a ReadFile of `/workspace/evidence/case_001.txt` (now deleted), which I've successfully recovered. The exact values are: **record code `VIRT_KEY_001`, forbidden module `billing_001`, and adapter path `adapter_001.py`**.",
      "batch_recover_calls": 6,
      "cache_hit_rate": 0.942895,
      "case_id": "runtime_ctx_001_long_distance_fact",
      "category": "long_distance_fact",
      "completion_tokens": 2232,
      "context_store": {
        "context_epochs": 1,
        "context_snapshots": 10,
        "historical_turns": 35,
        "recoverable_contexts": 15
      },
      "context_window": 24000,
      "duration_seconds": 57.101,
      "false_recovery": false,
      "final_context_mode": "virtualized",
      "invalid_tool_calls": 1,
      "passed": true,
      "prompt_cache_hit_tokens": 89856,
      "prompt_cache_miss_tokens": 5442,
      "prompt_hash_change_count": 9,
      "prompt_tokens": 95298,
      "recovery_call_count": 7,
      "recovery_required": true,
      "recovery_success": true,
      "rendered_prompt_hash_change_count": 0,
      "repeat": 0,
      "request_count": 10,
      "runtime_context_hash_change_count": 0,
      "search_recoverable_calls": 1,
      "search_session_calls": 0,
      "status": "passed",
      "strategy": "forced_virtualized",
      "token_records": [
        {
          "completion_tokens": 176,
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
          "prompt_cache_miss_tokens": 2059,
          "prompt_hash": "e77c14d9fb49",
          "prompt_tokens": 7307,
          "request_index": 1,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 7483
        },
        {
          "completion_tokens": 291,
          "metadata": {
            "current_turn_tokens": 574,
            "estimated_request_tokens": 6514,
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
          "prompt_cache_miss_tokens": 590,
          "prompt_hash": "154e3fbc9b54",
          "prompt_tokens": 7886,
          "request_index": 2,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8177
        },
        {
          "completion_tokens": 224,
          "metadata": {
            "current_turn_tokens": 1024,
            "estimated_request_tokens": 6964,
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
          "prompt_cache_miss_tokens": 540,
          "prompt_hash": "29065b91b0e8",
          "prompt_tokens": 8604,
          "request_index": 3,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 8828
        },
        {
          "completion_tokens": 145,
          "metadata": {
            "current_turn_tokens": 1120,
            "estimated_request_tokens": 7060,
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
          "prompt_cache_miss_tokens": 151,
          "prompt_hash": "fac2123851f8",
          "prompt_tokens": 8855,
          "request_index": 4,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9000
        },
        {
          "completion_tokens": 443,
          "metadata": {
            "current_turn_tokens": 1271,
            "estimated_request_tokens": 7211,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 89,
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
          "prompt_cache_hit_tokens": 8960,
          "prompt_cache_miss_tokens": 70,
          "prompt_hash": "bb72cd936367",
          "prompt_tokens": 9030,
          "request_index": 5,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9473
        },
        {
          "completion_tokens": 131,
          "metadata": {
            "current_turn_tokens": 1422,
            "estimated_request_tokens": 7362,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 91,
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
          "prompt_cache_hit_tokens": 9472,
          "prompt_cache_miss_tokens": 69,
          "prompt_hash": "517321289232",
          "prompt_tokens": 9541,
          "request_index": 6,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 9672
        },
        {
          "completion_tokens": 291,
          "metadata": {
            "current_turn_tokens": 1875,
            "estimated_request_tokens": 7815,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 93,
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
          "prompt_cache_hit_tokens": 9472,
          "prompt_cache_miss_tokens": 592,
          "prompt_hash": "c7546d403399",
          "prompt_tokens": 10064,
          "request_index": 7,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 10355
        },
        {
          "completion_tokens": 148,
          "metadata": {
            "current_turn_tokens": 2326,
            "estimated_request_tokens": 8266,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 95,
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
          "prompt_cache_hit_tokens": 10240,
          "prompt_cache_miss_tokens": 518,
          "prompt_hash": "1afe439f6074",
          "prompt_tokens": 10758,
          "request_index": 8,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 10906
        },
        {
          "completion_tokens": 235,
          "metadata": {
            "current_turn_tokens": 2779,
            "estimated_request_tokens": 8719,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 97,
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
          "prompt_cache_miss_tokens": 427,
          "prompt_hash": "6583317f053d",
          "prompt_tokens": 11307,
          "request_index": 9,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 11542
        },
        {
          "completion_tokens": 148,
          "metadata": {
            "current_turn_tokens": 3229,
            "estimated_request_tokens": 9169,
            "fixed_system_tokens": 804,
            "historical_messages_tokens": 2517,
            "message_count": 99,
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
          "prompt_cache_hit_tokens": 11520,
          "prompt_cache_miss_tokens": 426,
          "prompt_hash": "4f3fa18c84cc",
          "prompt_tokens": 11946,
          "request_index": 10,
          "tools_hash": "0abea09b7d3c",
          "total_tokens": 12094
        }
      ],
      "tool_call_count": 15,
      "tool_names": [
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "ReadFile",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "ReadFile",
        "Glob",
        "Glob",
        "SearchRecoverableContext",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext",
        "BatchRecoverContext"
      ],
      "tools_hash_change_count": 0,
      "total_tokens": 97530
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
