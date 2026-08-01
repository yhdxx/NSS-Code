# 项目图谱评测

- 状态：`passed`
- 指标 ID：`project_graph`

## 指标定义

衡量固定项目快照上的首次建图、热读取、单文件增量刷新、资源开销，以及人工标注存在时的符号覆盖率和语法级调用边准确性。

## 计算公式

- 符号覆盖率 = 正确检出的标注符号数 / 标注符号总数
- 调用精确率 = 正确调用边数 / 标注文件范围内检出的调用边数
- 调用召回率 = 正确调用边数 / 标注调用边总数

## 数据集与样本

```json
{
  "dataset_path": "tests/eval/manifests/public_projects.json",
  "dataset_sha256": "729dd3c888e44412f935fe87e567c165774a5a135682259aae4e4f803a2d33dc",
  "sample_count": 10,
  "tool_schema_hash": "ccaa0fa594218d90a15bf9600d3016018f7d96fd10770016dccde643ae705bfc"
}
```

## 测试环境

```json
{
  "base_url": "https://api.deepseek.com",
  "generated_at": "2026-08-01T18:24:02+0800",
  "git_commit": "1c5e2b27423b9618a1c76f0a1c4b38542011420e",
  "git_dirty": true,
  "model": "deepseek-v4-pro",
  "platform": "Linux-5.4.0-216-generic-x86_64-with-glibc2.31",
  "python": "3.12.6",
  "random_seed": 20260801,
  "repeats": 1,
  "run_id": "graph-resumable-20260801"
}
```

## 执行命令

```bash
python3 -m tests.eval.modern_runner run-project-graph --manifest tests/eval/manifests/public_projects.json --projects-root /tmp/mycodingagent_eval_projects --annotations tests/eval/annotations
```

## 结果与置信区间

```json
{
  "accuracy_reason": "manual symbol/call annotations are absent",
  "accuracy_status": "not_run",
  "annotation_projects": 0,
  "call_precision": null,
  "call_recall": null,
  "completed_projects": 10,
  "first_build_seconds": {
    "ci95": {
      "high": 340.004863,
      "low": 72.390524,
      "mean": 178.562325
    },
    "mean": 178.562325,
    "p50": 92.057782,
    "p95": 587.058589,
    "sample_count": 10
  },
  "incremental_refresh_seconds": {
    "ci95": {
      "high": 2.5734,
      "low": 0.202692,
      "mean": 1.087932
    },
    "mean": 1.087932,
    "p50": 0.186056,
    "p95": 4.640171,
    "sample_count": 10
  },
  "peak_memory_mib": {
    "ci95": {
      "high": 31.414068,
      "low": 8.819115,
      "mean": 17.458593
    },
    "mean": 17.458593,
    "p50": 10.178424,
    "p95": 50.464661,
    "sample_count": 10
  },
  "performance_status": "passed",
  "project_count": 10,
  "resume_conclusion": "在 10 个固定 commit 项目上完成图谱性能评测；符号覆盖率及调用边精确率/召回率尚无人工标注，不作为准确性证据。",
  "symbol_coverage": null,
  "warm_read_seconds": {
    "ci95": {
      "high": 0.00297,
      "low": 0.001001,
      "mean": 0.001898
    },
    "mean": 0.001898,
    "p50": 0.000991,
    "p95": 0.004621,
    "sample_count": 10
  }
}
```

## 失败、超时与异常样例

```json
{
  "count": 0,
  "examples": []
}
```

## 局限与有效性威胁

- 结论门禁：性能结果需覆盖 10 个固定 commit；准确性结果还需每项目至少 30 个符号和 20 条调用边的人工标注。
- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。
- 失败、超时和缺失字段计入产物，不从分母中静默剔除。

## 简历可用结论

在 10 个固定 commit 项目上完成图谱性能评测；符号覆盖率及调用边精确率/召回率尚无人工标注，不作为准确性证据。
