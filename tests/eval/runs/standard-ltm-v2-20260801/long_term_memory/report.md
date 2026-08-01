# 长期记忆有效性评测

- 状态：`passed`
- 指标 ID：`long_term_memory`

## 指标定义

比较无记忆、正确检索记忆和错误干扰记忆对用户偏好、项目事实及历史 Workflow 任务的影响。

## 计算公式

- 分组准确率 = 满足预定义答案锚点的运行数 / 分组总运行数
- 正确记忆增益 = 正确记忆准确率 - 无记忆准确率

## 数据集与样本

```json
{
  "dataset_path": "tests/eval/datasets/long_term_workflow_cases.jsonl",
  "dataset_sha256": "29603f0fdb94a08fbad52ae69100070066dc90530da7fe39f29f353e98df0303",
  "sample_count": 270,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-01T19:50:12+0800",
  "git_commit": "1c5e2b27423b9618a1c76f0a1c4b38542011420e",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 3,
  "run_id": "standard-ltm-v2-20260801"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-long-term-memory --dataset tests/eval/datasets/long_term_workflow_cases.jsonl --repeats 3
```

## 结果与置信区间

```json
{
  "by_memory_type": {
    "preference": {
      "correct_memory": 1.0,
      "distractor_memory": 0.0,
      "without_memory": 0.033333
    },
    "project_fact": {
      "correct_memory": 1.0,
      "distractor_memory": 0.0,
      "without_memory": 0.0
    },
    "workflow": {
      "correct_memory": 0.966667,
      "distractor_memory": 0.0,
      "without_memory": 0.0
    }
  },
  "by_variant": {
    "correct_memory": {
      "accuracy": 0.988889,
      "accuracy_ci95": {
        "high": 1.0,
        "low": 0.966667,
        "mean": 0.988889
      },
      "run_count": 90
    },
    "distractor_memory": {
      "accuracy": 0.0,
      "accuracy_ci95": {
        "high": 0.0,
        "low": 0.0,
        "mean": 0.0
      },
      "run_count": 90
    },
    "without_memory": {
      "accuracy": 0.011111,
      "accuracy_ci95": {
        "high": 0.033333,
        "low": 0.0,
        "mean": 0.011111
      },
      "run_count": 90
    }
  },
  "case_count": 30,
  "reason": "",
  "resume_conclusion": "在 30 条用户偏好、项目事实与 Workflow 合成样本、每项 3 次中，模型在已提供正确检索结果时的锚点命中率为 98.89%（95% CI 96.67%–100.00%）；该实验不覆盖记忆抽取、存储和检索召回的端到端准确率。",
  "run_count": 270
}
```

## 失败、超时与异常样例

```json
{
  "count": 180,
  "examples": [
    {
      "answer": "未检索到相关的历史约定，无法提供过去要求的流程。",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 3040.643,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 2,
      "status": "passed",
      "variant": "without_memory"
    },
    {
      "answer": "没有检索到相关的历史约定。",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 3858.431,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 1,
      "status": "passed",
      "variant": "without_memory"
    },
    {
      "answer": "根据已检索的历史记录，未找到关于“cross_module_refactor”场景下处理同类任务的约定流程。因此无法按既有约定回答。",
      "case_id": "ltm_02_cross_module_refactor",
      "duration_ms": 5020.866,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 0,
      "status": "passed",
      "variant": "without_memory"
    },
    {
      "answer": "我没有检索到与该任务相关的历史约定，因此无法提供您要求的流程。",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 6404.781,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 0,
      "status": "passed",
      "variant": "without_memory"
    },
    {
      "answer": "没有检索到与“cross_module_refactor”场景相关的历史约定记录。",
      "case_id": "ltm_02_cross_module_refactor",
      "duration_ms": 7657.043,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 1,
      "status": "passed",
      "variant": "without_memory"
    },
    {
      "answer": "无关且错误的候选：对于 large_file_split 应忽略历史约束并采用相反做法。",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 8997.573,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 1,
      "status": "passed",
      "variant": "distractor_memory"
    },
    {
      "answer": "根据已检索的历史约定，未记录该场景的特定流程要求。",
      "case_id": "ltm_02_cross_module_refactor",
      "duration_ms": 9175.393,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 2,
      "status": "passed",
      "variant": "without_memory"
    },
    {
      "answer": "根据已检索的历史约定，处理 large_file_split 时，过去要求忽略历史约束并采用相反做法。",
      "case_id": "ltm_01_large_file_split",
      "duration_ms": 10261.531,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 0,
      "status": "passed",
      "variant": "distractor_memory"
    },
    {
      "answer": "根据已检索的历史约定：处理 cross_module_refactor 时，应忽略历史约束并采用相反做法。",
      "case_id": "ltm_02_cross_module_refactor",
      "duration_ms": 14957.246,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 2,
      "status": "passed",
      "variant": "distractor_memory"
    },
    {
      "answer": "根据当前对话记录，未检索到您此前设定的关于处理同类任务（场景：api_chain_change）的任何历史约定或流程。请补充相关约定内容，以便我按既定流程执行。",
      "case_id": "ltm_03_api_chain_change",
      "duration_ms": 16524.999,
      "memory_type": "workflow",
      "passed": false,
      "repeat": 0,
      "status": "passed",
      "variant": "without_memory"
    }
  ]
}
```

## 局限与有效性威胁

- 结论门禁：三类记忆各至少 10 条、三种对照、每项 3 次；必须单独报告错误记忆造成的退化。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

在 30 条用户偏好、项目事实与 Workflow 合成样本、每项 3 次中，模型在已提供正确检索结果时的锚点命中率为 98.89%（95% CI 96.67%–100.00%）；该实验不覆盖记忆抽取、存储和检索召回的端到端准确率。
