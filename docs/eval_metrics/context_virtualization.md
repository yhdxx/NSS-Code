# 上下文虚拟化评测

- 状态：`passed`
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
  "sample_count": 270,
  "tool_schema_hash": "f973b6028e66ecce13ff715b467bb2fbb456ea24e4935136aace4085e534f300"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-13T17:10:24+0800",
  "git_commit": "ad4b1563ade58eff5e234d0bc106eccad5e7486e",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 3,
  "run_id": "context-virtualization-rerun-20260813"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-context --dataset tests/eval/datasets/context_virtualization_cases.jsonl --repeats 3
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
      "run_count": 90,
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
      "run_count": 90,
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
      "run_count": 90,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      }
    }
  },
  "case_count": 30,
  "completed_run_count": 270,
  "reason": "",
  "run_count": 270
}
```

## 失败、超时与异常样例

```json
{
  "count": 90,
  "examples": [
    {
      "answer": "当前可见对话中未包含会话初期的项目约束内容，因此我无法完整说出禁止修改的模块及适配文件名。请补充该约束原文或相关上下文。",
      "case_id": "ctx_01",
      "duration_ms": 10847.726,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1130,
      "repeat": 0,
      "status": "passed",
      "total_tokens": 1534
    },
    {
      "answer": "当前可见的对话记录里没有包含会话初期你提出的项目约束原文，因此我无法完整说出“禁止修改哪个模块”以及“适配文件名”。请补充该约束内容，我可以帮你准确复述。",
      "case_id": "ctx_01",
      "duration_ms": 11309.938,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1130,
      "repeat": 1,
      "status": "passed",
      "total_tokens": 1571
    },
    {
      "answer": "当前可见的对话记录中未包含会话初期你提出的项目约束内容，因此我无法完整说出“禁止修改哪个模块”以及“适配文件名”。请提供或补充该约束，我再按要求完整复述。",
      "case_id": "ctx_02",
      "duration_ms": 15669.993,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1130,
      "repeat": 0,
      "status": "passed",
      "total_tokens": 1571
    },
    {
      "answer": "当前可见对话中未包含您早期提出的项目约束内容，因此我无法完整说出禁止修改的模块及适配文件名。请补充该约束原文，我会严格按要求复述。",
      "case_id": "ctx_02",
      "duration_ms": 18232.576,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1130,
      "repeat": 1,
      "status": "passed",
      "total_tokens": 1664
    },
    {
      "answer": "当前可见的对话记录中未包含会话初期您提出的项目约束内容，因此我无法完整说出禁止修改的模块和适配文件名。请补充该约束原文。",
      "case_id": "ctx_01",
      "duration_ms": 27357.221,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1130,
      "repeat": 2,
      "status": "passed",
      "total_tokens": 2413
    },
    {
      "answer": "当前可见的对话内容中未包含你会话初期提出的项目约束，因此我无法完整说出禁止修改的模块及适配文件名。请补充该约束内容，我会严格按此遵守。",
      "case_id": "ctx_03",
      "duration_ms": 30129.126,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1130,
      "repeat": 2,
      "status": "passed",
      "total_tokens": 1735
    },
    {
      "answer": "当前可见的对话记录中未包含会话初期你提出的项目约束内容，因此我无法完整说出禁止修改哪个模块以及适配文件名。请补充相关原文，我再按要求完整回答。",
      "case_id": "ctx_03",
      "duration_ms": 31031.412,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1130,
      "repeat": 0,
      "status": "passed",
      "total_tokens": 1792
    },
    {
      "answer": "当前可见的对话记录中未包含会话初期您提出的项目约束，因此我无法完整说出禁止修改的模块及适配文件名。请补充该约束内容，我可以帮您确认。",
      "case_id": "ctx_02",
      "duration_ms": 31323.139,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1130,
      "repeat": 2,
      "status": "passed",
      "total_tokens": 2279
    },
    {
      "answer": "当前可见上下文中没有包含会话初期你提出的项目约束内容，因此我无法完整说出禁止修改的模块及适配文件名。请补充或重新发送相关约束内容。",
      "case_id": "ctx_04",
      "duration_ms": 38864.931,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1130,
      "repeat": 0,
      "status": "passed",
      "total_tokens": 1668
    },
    {
      "answer": "当前可见的对话记录中并未包含会话初期你提出的项目约束内容，因此我无法完整说出“禁止修改哪个模块”以及“适配文件名”是什么。请补充或重新提供该约束，我可以帮你确认。",
      "case_id": "ctx_03",
      "duration_ms": 40004.676,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1130,
      "repeat": 1,
      "status": "passed",
      "total_tokens": 2193
    }
  ]
}
```

## 局限与有效性威胁

- 结论门禁：至少 30 个长会话任务、每种策略 3 次，并报告 p50/p95 与 95% 置信区间。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

本次结果已执行，但仍须按门禁和局限限定表述。
