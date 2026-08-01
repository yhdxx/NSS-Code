# Versioned effectiveness evaluation

这些评测与普通 pytest 分离：部分命令会调用真实模型 API、BGE、Docker 或完整 Agent Runtime，必须显式执行。所有新版结果写入 `tests/eval/runs/<run_id>/<metric>/`，不会覆盖旧结果；每项指标同时更新 `docs/eval_metrics/<metric>.md`。

## 固定实验设计

- 默认模型：只使用当前项目配置的默认模型。
- 随机种子：`20260801`。
- 标准规模：30 个任务/会话，随机实验每组重复 3 次。
- 公开项目：`manifests/public_projects.json` 中 10 个固定 commit。
- 失败、超时和缺失字段保留在 details 中，不静默剔除。
- 服务商不返回缓存 hit/miss 字段时，前缀缓存状态必须是 `unavailable`。
- 未运行真实 API 时，文档必须是 `not_run`，不得引用历史小样本作为新结果。

## 运行顺序

```bash
PYTHONPATH=. .venv/bin/python -m tests.eval.modern_runner generate-datasets
PYTHONPATH=. .venv/bin/python -m tests.eval.modern_runner init-docs
PYTHONPATH=. .venv/bin/python -m tests.eval.modern_runner run-capability-routing
PYTHONPATH=. .venv/bin/python -m tests.eval.modern_runner run-prefix-cache --repeats 3
PYTHONPATH=. .venv/bin/python -m tests.eval.modern_runner run-context --repeats 3
PYTHONPATH=. .venv/bin/python -m tests.eval.modern_runner run-long-term-memory --repeats 3
PYTHONPATH=. .venv/bin/python -m tests.eval.modern_runner run-multi-agent --repeats 3
PYTHONPATH=. .venv/bin/python -m tests.eval.modern_runner report
```

项目图谱与 Code/General A/B 当前按用户要求延期：图谱逻辑修改完成前，不运行这两项，也不生成量化结论。当前延期状态可通过以下命令复现：

```bash
PYTHONPATH=. .venv/bin/python -m tests.eval.modern_runner defer-project-graph
PYTHONPATH=. .venv/bin/python -m tests.eval.modern_runner defer-code-general-ab
```

## 每份指标文档的强制内容

每份文档包含指标定义、数据集和 hash、环境、命令、公式、样本数、结果与 95% 置信区间、失败/超时样例、局限以及简历可用结论。只有满足文档内门禁的 `passed` 结果才能用于简历。
