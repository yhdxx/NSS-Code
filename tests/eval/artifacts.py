from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


RUNS_DIR = Path("tests/eval/runs")
DOCS_DIR = Path("docs/eval_metrics")

METRIC_SPECS: dict[str, dict[str, Any]] = {
    "project_graph": {
        "title": "项目图谱评测",
        "definition": "衡量固定项目快照上的首次建图、热读取、单文件增量刷新、资源开销，以及人工标注存在时的符号覆盖率和语法级调用边准确性。",
        "formulas": [
            "符号覆盖率 = 正确检出的标注符号数 / 标注符号总数",
            "调用精确率 = 正确调用边数 / 标注文件范围内检出的调用边数",
            "调用召回率 = 正确调用边数 / 标注调用边总数",
        ],
        "gate": "性能结果需覆盖 10 个固定 commit；准确性结果还需每项目至少 30 个符号和 20 条调用边的人工标注。",
    },
    "code_general_ab": {
        "title": "Code / General 工作模式 A/B 评测",
        "definition": "在相同模型、任务和工具 schema 下，对比 Code 图谱导航与 General 自主探索的任务成功率和执行成本。",
        "formulas": [
            "任务成功率 = 验收测试通过的运行数 / 总运行数",
            "成本降幅 = (General 均值 - Code 均值) / General 均值",
        ],
        "gate": "至少 30 个任务、每模式 3 次；Code 成功率不得比 General 低超过 5 个百分点，且 token 或读取/工具调用成本显著下降，才可表述为提高效率。",
    },
    "context_virtualization": {
        "title": "上下文虚拟化评测",
        "definition": "比较 raw、virtualized 与 recent_only 在多轮长会话中的任务成功率、历史证据恢复率和输入成本。",
        "formulas": [
            "成功率 = 正确回答运行数 / 总运行数",
            "输入压缩率 = (Raw 输入 token - 候选输入 token) / Raw 输入 token",
        ],
        "gate": "至少 30 个长会话任务、每种策略 3 次，并报告 p50/p95 与 95% 置信区间。",
    },
    "runtime_context_virtualization": {
        "title": "真实 Runtime 上下文虚拟化评测",
        "definition": "通过真实 MemoryRuntime、工具 schema、可恢复工具输出和 ask_deepseek 调用链，对比 raw、forced_virtualized 与 natural 策略的质量、token 成本、缓存命中和恢复行为。",
        "formulas": [
            "任务成功率 = 正确回答隐藏历史证据锚点的运行数 / 总运行数",
            "未缓存输入降幅 = (Raw 未缓存输入 token - 候选未缓存输入 token) / Raw 未缓存输入 token",
            "缓存命中率 = prompt_cache_hit_tokens / (prompt_cache_hit_tokens + prompt_cache_miss_tokens)",
            "恢复成功率 = 需要恢复且恢复后答对的运行数 / 需要恢复的运行数",
        ],
        "gate": "至少 30 条长会话轨迹、raw/forced_virtualized/natural 三策略、每策略 3 次；Virtualized 成功率不得比 Raw 低超过 5 个百分点，且未缓存输入 token 必须下降。",
    },
    "prefix_cache": {
        "title": "前缀缓存命中率评测",
        "definition": "在 system prompt 与工具 schema 稳定的连续请求中，测量服务商返回的缓存命中 token 占比；预热请求不计入。该评测不依赖或假设项目图谱消息常驻。",
        "formulas": [
            "缓存命中率 = prompt_cache_hit_tokens / (prompt_cache_hit_tokens + prompt_cache_miss_tokens)",
        ],
        "gate": "服务商必须返回 hit/miss token，至少 30 个会话且每会话完成预热与 3 次测量；否则 93.5% 不得用于简历。",
    },
    "long_term_memory": {
        "title": "长期记忆有效性评测",
        "definition": "比较无记忆、正确检索记忆和错误干扰记忆对用户偏好、项目事实及历史 Workflow 任务的影响。",
        "formulas": [
            "分组准确率 = 满足预定义答案锚点的运行数 / 分组总运行数",
            "正确记忆增益 = 正确记忆准确率 - 无记忆准确率",
        ],
        "gate": "三类记忆各至少 10 条、三种对照、每项 3 次；必须单独报告错误记忆造成的退化。",
    },
    "capability_routing": {
        "title": "Skill / MCP 能力路由评测",
        "definition": "在千级 Skill 与 MCP 能力语料中，用不直接复用能力名称的人工风格查询衡量候选召回和排序质量。",
        "formulas": [
            "Recall@K = Top-K 含相关能力的查询数 / 查询总数",
            "MRR = mean(1 / 首个相关结果排名)",
            "NDCG@5 = DCG@5 / IDCG@5",
        ],
        "gate": "至少 1200 个能力（含 900 Skill、300 MCP）与 200 条人工风格查询；纯模板同名数据不得作为精准路由结论。",
    },
    "multi_agent": {
        "title": "Multi-Agent 协作 A/B 评测",
        "definition": "比较 direct 与 Planner-Scheduler-Test 协作流程在分层代码任务上的成功率、耗时、token、工具调用和冲突/重试情况。",
        "formulas": [
            "任务成功率 = 验收测试通过运行数 / 总运行数",
            "相对开销 = Multi-Agent 均值 / Direct 均值",
        ],
        "gate": "至少 30 个任务、每模式 3 次；成功率收益和复杂任务收益明确前，只表述实现了状态机协作与冲突控制。",
    },
}


def make_run_id(prefix: str = "eval") -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}"


def metric_run_dir(run_root: Path, run_id: str, metric: str) -> Path:
    path = run_root / run_id / metric
    if (path / "summary.json").exists():
        raise FileExistsError(f"refusing to overwrite completed metric run: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if is_dataclass(payload):
        payload = asdict(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n" for row in rows), encoding="utf-8")
    return path


def complete_metric_run(
    *,
    metric: str,
    run_dir: Path,
    summary: dict[str, Any],
    metadata: dict[str, Any],
    command: str,
    details: list[dict[str, Any]] | None = None,
    docs_dir: Path = DOCS_DIR,
) -> Path:
    if metric not in METRIC_SPECS:
        raise KeyError(metric)
    normalized = dict(summary)
    normalized.setdefault("module", metric)
    normalized.setdefault("status", "not_run")
    write_json(run_dir / "summary.json", normalized)
    write_json(run_dir / "run_metadata.json", metadata)
    if details is not None:
        write_jsonl(run_dir / "details.jsonl", details)
    report = render_metric_document(metric, normalized, metadata, command, details or [])
    write_json(run_dir / "report_payload.json", {"metric": metric, "command": command})
    run_report = run_dir / "report.md"
    run_report.write_text(report, encoding="utf-8")
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / f"{metric}.md").write_text(report, encoding="utf-8")
    return run_report


def render_metric_document(
    metric: str,
    summary: dict[str, Any],
    metadata: dict[str, Any],
    command: str,
    details: list[dict[str, Any]],
) -> str:
    spec = METRIC_SPECS[metric]
    status = str(summary.get("status", "not_run"))
    failures = [
        row for row in details
        if row.get("status") in {"failed", "blocked", "timeout", "unavailable"}
        or row.get("passed") is False
        or int(row.get("invalid_tool_calls") or 0) > 0
    ]
    environment = {key: metadata.get(key, "") for key in ("run_id", "generated_at", "git_commit", "git_dirty", "model", "base_url", "python", "platform", "random_seed", "repeats")}
    hashes = {key: metadata.get(key, "") for key in ("dataset_path", "dataset_sha256", "tool_schema_hash") if metadata.get(key)}
    result_payload = {key: value for key, value in summary.items() if key not in {"module", "status"}}
    if status == "passed":
        resume = str(summary.get("resume_conclusion") or "本次结果已执行，但仍须按门禁和局限限定表述。")
    else:
        reason = summary.get("reason") or summary.get("annotation_reason") or "评测尚未满足执行条件。"
        resume = f"不可使用量化结论（status={status}）：{reason}"
    lines = [
        f"# {spec['title']}", "", f"- 状态：`{status}`", f"- 指标 ID：`{metric}`", "",
        "## 指标定义", "", str(spec["definition"]), "",
        "## 计算公式", "", *[f"- {item}" for item in spec["formulas"]], "",
        "## 数据集与样本", "", _json_block({"sample_count": _sample_count(summary), **hashes}), "",
        "## 测试环境", "", _json_block(environment), "",
        "## 执行命令", "", f"```bash\n{command}\n```", "",
        "## 结果与置信区间", "", _json_block(result_payload if status not in {"not_run", "unavailable"} else {"status": status, "reason": summary.get("reason", "未执行或服务商未提供必要数据")}), "",
        "## 失败、超时与异常样例", "", _json_block({"count": len(failures), "examples": failures[:10]}), "",
        "## 局限与有效性威胁", "", f"- 结论门禁：{spec['gate']}", "- 固定模型与固定 commit 提高可复现性，但不能代表所有模型、语言和真实项目分布。", "- 失败、超时和缺失字段计入产物，不从分母中静默剔除。", "",
        "## 简历可用结论", "", resume, "",
    ]
    return "\n".join(lines)


def initialize_not_run_documents(*, docs_dir: Path = DOCS_DIR) -> list[Path]:
    paths = []
    metadata = {"run_id": "not-run", "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    for metric in METRIC_SPECS:
        report = render_metric_document(metric, {"status": "not_run", "reason": "尚未执行新版标准评测"}, metadata, f"python3 -m tests.eval.modern_runner run-{metric.replace('_', '-')}", [])
        docs_dir.mkdir(parents=True, exist_ok=True)
        path = docs_dir / f"{metric}.md"
        path.write_text(report, encoding="utf-8")
        paths.append(path)
    return paths


def _sample_count(summary: dict[str, Any]) -> Any:
    for key in ("run_count", "case_count", "query_count", "project_count", "sample_count"):
        if key in summary:
            return summary[key]
    return 0


def _json_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n```"
