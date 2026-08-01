# Multi-Agent 协作 A/B 评测

- 状态：`deprecated_incomplete`
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
  "sample_count": 59,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-01T21:13:45+0800",
  "git_commit": "1c5e2b27423b9618a1c76f0a1c4b38542011420e",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 3,
  "run_id": "existing-multi-agent-deprecated-20260801"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner document-multi-agent-existing
```

## 结果与置信区间

```json
{
  "case_count": 6,
  "historical_complete_small_sample": {
    "direct": {
      "duration_mean_ci95": {
        "high": 68.126333,
        "low": 28.92,
        "mean": 47.884167
      },
      "duration_mean_seconds": 47.884167,
      "run_count": 6,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 19.5,
      "tool_calls_mean_ci95": {
        "high": 24.170833,
        "low": 14.495833,
        "mean": 19.5
      }
    },
    "multi_agent": {
      "duration_mean_ci95": {
        "high": 1032.505637,
        "low": 214.223833,
        "mean": 507.163833
      },
      "duration_mean_seconds": 507.163833,
      "run_count": 6,
      "success_rate": 0.833333,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 0.5,
        "mean": 0.833333
      },
      "tool_calls_mean": 43.333333,
      "tool_calls_mean_ci95": {
        "high": 61.666667,
        "low": 23.666667,
        "mean": 43.333333
      }
    }
  },
  "partial_standard_run_counts": {
    "direct": 35,
    "multi_agent": 12
  },
  "partial_standard_run_unpaired": {
    "direct": {
      "duration_mean_ci95": {
        "high": 288.980105,
        "low": 117.172862,
        "mean": 194.086857
      },
      "duration_mean_seconds": 194.086857,
      "run_count": 35,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      },
      "tool_calls_mean": 10.0,
      "tool_calls_mean_ci95": {
        "high": 12.142857,
        "low": 8.285714,
        "mean": 10.0
      }
    },
    "multi_agent": {
      "duration_mean_ci95": {
        "high": 1111.961992,
        "low": 879.220815,
        "mean": 993.863
      },
      "duration_mean_seconds": 993.863,
      "run_count": 12,
      "success_rate": 0.666667,
      "success_rate_ci95": {
        "high": 0.916667,
        "low": 0.416667,
        "mean": 0.666667
      },
      "tool_calls_mean": 21.416667,
      "tool_calls_mean_ci95": {
        "high": 29.583333,
        "low": 12.664583,
        "mean": 21.416667
      }
    }
  },
  "reason": "用户计划废弃 Multi-Agent 模块；标准 30 任务 × 3 重复实验已停止。",
  "resume_conclusion": "不可声明 Multi-Agent 提高效率或成功率；历史 6-case 对照中成功率更低且耗时显著更高，新版标准实验未完成，且模块计划废弃。",
  "run_count": 59,
  "token_accounting_status": "unavailable_subagent_aggregation"
}
```

## 失败、超时与异常样例

```json
{
  "count": 5,
  "examples": [
    {
      "case_id": "ma_large_05_reporting_refunds",
      "changed_files": [],
      "delegate_status": "timeout",
      "duration_seconds": 1800.0,
      "error": "TimeoutError: multi-agent did not finish within 1800 seconds during large-case evaluation",
      "evidence_source": "historical_complete_small_sample",
      "final_answer_tail": "",
      "mode": "multi_agent",
      "ordinal": 5,
      "passed": false,
      "project_size": "large",
      "pytest_returncode": -1,
      "pytest_stderr_tail": "",
      "pytest_stdout_tail": "",
      "run_log_tail": "Evaluation command timed out before _run_multi_agent_case returned.",
      "subagent_rounds": {},
      "subagent_tool_calls": {},
      "submitted_steps": 0,
      "tool_call_count": 0,
      "tool_names": []
    },
    {
      "case_id": "ma_large_03_payment_capture",
      "duration_seconds": 888.52,
      "error": "ReadError: ",
      "evidence_source": "partial_standard_run_unpaired",
      "mode": "multi_agent",
      "ordinal": 27,
      "passed": false,
      "project_size": "large",
      "repeat": 0,
      "run_log_tail": "",
      "status": "failed"
    },
    {
      "case_id": "ma_medium_06_inventory",
      "duration_seconds": 1037.431,
      "error": "ReadError: ",
      "evidence_source": "partial_standard_run_unpaired",
      "mode": "multi_agent",
      "ordinal": 18,
      "passed": false,
      "project_size": "medium",
      "repeat": 0,
      "run_log_tail": "",
      "status": "failed"
    },
    {
      "case_id": "ma_medium_11_search",
      "duration_seconds": 1146.208,
      "error": "ReadError: ",
      "evidence_source": "partial_standard_run_unpaired",
      "mode": "multi_agent",
      "ordinal": 23,
      "passed": false,
      "project_size": "medium",
      "repeat": 0,
      "run_log_tail": "",
      "status": "failed"
    },
    {
      "case_id": "ma_large_04_inventory_allocation",
      "duration_seconds": 1105.345,
      "error": "ReadError: ",
      "evidence_source": "partial_standard_run_unpaired",
      "mode": "multi_agent",
      "ordinal": 28,
      "passed": false,
      "project_size": "large",
      "repeat": 0,
      "run_log_tail": "",
      "status": "failed"
    }
  ]
}
```

## 局限与有效性威胁

- 结论门禁：至少 30 个任务、每模式 3 次；成功率收益和复杂任务收益明确前，只表述实现了状态机协作与冲突控制。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

不可使用量化结论（status=deprecated_incomplete）：用户计划废弃 Multi-Agent 模块；标准 30 任务 × 3 重复实验已停止。
