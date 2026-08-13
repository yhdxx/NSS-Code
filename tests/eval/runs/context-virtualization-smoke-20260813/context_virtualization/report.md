# 上下文虚拟化评测

- 状态：`failed`
- 指标 ID：`context_virtualization`

## 指标定义

比较 raw、virtualized 与 recent_only 在多轮长会话中的任务成功率、历史证据恢复率和输入成本。

## 计算公式

- 成功率 = 正确回答运行数 / 总运行数
- 输入压缩率 = (Raw 输入 token - 候选输入 token) / Raw 输入 token

## 数据集与样本

```json
{
  "dataset_path": "tests/eval/datasets/context_virtualization_cases.jsonl",
  "dataset_sha256": "72864cf81b32eedcebe3a6a552677bcad8bae89bba89dd5b2717abe38bfc3331",
  "sample_count": 6,
  "tool_schema_hash": "f973b6028e66ecce13ff715b467bb2fbb456ea24e4935136aace4085e534f300"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-13T17:09:34+0800",
  "git_commit": "ad4b1563ade58eff5e234d0bc106eccad5e7486e",
  "git_dirty": false,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 1,
  "run_id": "context-virtualization-smoke-20260813"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-context --dataset tests/eval/datasets/context_virtualization_cases.jsonl --repeats 1
```

## 结果与置信区间

```json
{
  "by_mode": {
    "raw": {
      "input_reduction_vs_raw": 0.0,
      "prompt_tokens_mean": 14664.0,
      "prompt_tokens_p50": 14664.0,
      "prompt_tokens_p95": 14664.0,
      "run_count": 2,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      }
    },
    "recent_only": {
      "input_reduction_vs_raw": 0.922941,
      "prompt_tokens_mean": 1130.0,
      "prompt_tokens_p50": 1130.0,
      "prompt_tokens_p95": 1130.0,
      "run_count": 2,
      "success_rate": 0.0,
      "success_rate_ci95": {
        "high": 0.0,
        "low": 0.0,
        "mean": 0.0
      }
    },
    "virtualized": {
      "input_reduction_vs_raw": 0.581424,
      "prompt_tokens_mean": 6138.0,
      "prompt_tokens_p50": 6138.0,
      "prompt_tokens_p95": 6138.0,
      "run_count": 2,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      }
    }
  },
  "case_count": 2,
  "completed_run_count": 6,
  "reason": "requires 30 cases, 3 repeats, and no failed API calls",
  "run_count": 6
}
```

## 失败、超时与异常样例

```json
{
  "count": 2,
  "examples": [
    {
      "answer": "当前可见对话记录中未包含您最初提出的项目约束，因此无法确定禁止修改哪个模块及适配文件名。请补充该约束内容，我会完整复述。",
      "case_id": "ctx_01",
      "duration_ms": 26306.127,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1130,
      "repeat": 0,
      "status": "passed",
      "total_tokens": 2435
    },
    {
      "answer": "抱歉，当前可见的会话记录中并未包含您最初提出的项目约束内容，因此我无法完整说出禁止修改的模块和适配文件名。为避免编造信息，请提供该约束原文，我会严格按要求执行。",
      "case_id": "ctx_02",
      "duration_ms": 34939.955,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1130,
      "repeat": 0,
      "status": "passed",
      "total_tokens": 2795
    }
  ]
}
```

## 局限与有效性威胁

- 结论门禁：至少 30 个长会话任务、每种策略 3 次，并报告 p50/p95 与 95% 置信区间。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

不可使用量化结论（status=failed）：requires 30 cases, 3 repeats, and no failed API calls
