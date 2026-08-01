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
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-01T19:11:19+0800",
  "git_commit": "1c5e2b27423b9618a1c76f0a1c4b38542011420e",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 3,
  "run_id": "standard-context-20260801"
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
      "prompt_tokens_mean": 14585.0,
      "prompt_tokens_p50": 14585.0,
      "prompt_tokens_p95": 14585.0,
      "run_count": 90,
      "success_rate": 1.0,
      "success_rate_ci95": {
        "high": 1.0,
        "low": 1.0,
        "mean": 1.0
      }
    },
    "recent_only": {
      "input_reduction_vs_raw": 0.92794,
      "prompt_tokens_mean": 1051.0,
      "prompt_tokens_p50": 1051.0,
      "prompt_tokens_p95": 1051.0,
      "run_count": 90,
      "success_rate": 0.0,
      "success_rate_ci95": {
        "high": 0.0,
        "low": 0.0,
        "mean": 0.0
      }
    },
    "virtualized": {
      "input_reduction_vs_raw": 0.584573,
      "prompt_tokens_mean": 6059.0,
      "prompt_tokens_p50": 6059.0,
      "prompt_tokens_p95": 6059.0,
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
  "resume_conclusion": "在 30 个合成长会话、每策略 3 次的受控证据恢复实验中，virtualized 保持 100% 锚点命中率，并相对 raw 减少 58.46% 输入 token；该结果不等同于真实开发任务端到端成功率。",
  "run_count": 270
}
```

## 失败、超时与异常样例

```json
{
  "count": 90,
  "examples": [
    {
      "answer": "在可见的对话记录中，你并未提及任何项目约束、禁止修改的模块或适配文件名。所有消息仅为对“中间无关需求”的简短确认，没有包含这些信息。",
      "case_id": "ctx_01",
      "duration_ms": 6757.942,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1051,
      "repeat": 2,
      "status": "passed",
      "total_tokens": 1240
    },
    {
      "answer": "根据提供的对话记录，无法找到任何关于项目约束的信息，包括禁止修改的模块或适配文件名。因此无法回答该问题。",
      "case_id": "ctx_02",
      "duration_ms": 12235.29,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1051,
      "repeat": 2,
      "status": "passed",
      "total_tokens": 1271
    },
    {
      "answer": "从当前提供的对话记录中，未见到您初期提出的项目约束内容，因此无法给出禁止修改的模块及适配文件名的具体信息。",
      "case_id": "ctx_02",
      "duration_ms": 15109.492,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1051,
      "repeat": 1,
      "status": "passed",
      "total_tokens": 1405
    },
    {
      "answer": "根据可见的对话历史，没有提及任何项目约束，包括禁止修改的模块和适配文件名。无法提供相关回答。",
      "case_id": "ctx_02",
      "duration_ms": 19533.499,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1051,
      "repeat": 0,
      "status": "passed",
      "total_tokens": 1615
    },
    {
      "answer": "在提供的可见对话中，没有任何关于项目约束的描述，因此无法回答禁止修改哪个模块以及适配文件名。",
      "case_id": "ctx_03",
      "duration_ms": 22276.99,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1051,
      "repeat": 1,
      "status": "passed",
      "total_tokens": 1275
    },
    {
      "answer": "在现有的会话记录中，并未出现您所提及的“项目约束”及“禁止修改哪个模块以及适配文件名”的相关信息。仅能看到从“已确认中间需求 131”开始的一系列简短确认对话。若早期存在相关约束，请提供更完整的上下文。",
      "case_id": "ctx_03",
      "duration_ms": 22965.107,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1051,
      "repeat": 0,
      "status": "passed",
      "total_tokens": 1412
    },
    {
      "answer": "在可见的对话记录中，未出现任何关于项目约束、禁止修改的模块或适配文件名的内容，因此无法给出答案。",
      "case_id": "ctx_03",
      "duration_ms": 23852.515,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1051,
      "repeat": 2,
      "status": "passed",
      "total_tokens": 1345
    },
    {
      "answer": "在目前可见的对话记录中，您并未提出任何项目约束，也没有提到禁止修改哪个模块或适配文件名。因此我无法回答。",
      "case_id": "ctx_01",
      "duration_ms": 29308.407,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1051,
      "repeat": 1,
      "status": "passed",
      "total_tokens": 2257
    },
    {
      "answer": "在提供的对话记录中，未提及任何项目约束，也没有说明禁止修改哪个模块以及必须适配的文件名。因此无法作答。",
      "case_id": "ctx_04",
      "duration_ms": 35018.918,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1051,
      "repeat": 1,
      "status": "passed",
      "total_tokens": 1447
    },
    {
      "answer": "从当前可见的对话记录（从“已确认中间需求 131”开始）中，没有找到你提出过任何项目约束，也没有关于禁止修改哪个模块或适配文件名的说明。因此，基于可见证据，无法回答该问题。",
      "case_id": "ctx_04",
      "duration_ms": 41786.823,
      "mode": "recent_only",
      "passed": false,
      "prompt_chars": 3968,
      "prompt_tokens": 1051,
      "repeat": 2,
      "status": "passed",
      "total_tokens": 1735
    }
  ]
}
```

## 局限与有效性威胁

- 结论门禁：至少 30 个长会话任务、每种策略 3 次，并报告 p50/p95 与 95% 置信区间。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

在 30 个合成长会话、每策略 3 次的受控证据恢复实验中，virtualized 保持 100% 锚点命中率，并相对 raw 减少 58.46% 输入 token；该结果不等同于真实开发任务端到端成功率。
