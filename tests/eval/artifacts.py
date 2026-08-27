from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


RUNS_DIR = Path("tests/eval/runs")
DOCS_DIR = Path("docs/eval_metrics")

METRIC_SPECS: dict[str, dict[str, Any]] = {
    "context_compression_100k": {
        "title": "100K 上下文压缩策略评测",
        "definition": "在统一 100K token 上下文窗口中，对比 Raw、当前自然虚拟化与 80% 触发的摘要 + 最近 10 轮策略。",
        "test_object": [
            "当前 MemoryRuntime 的工具输出外置、ContextEpoch 和可恢复冷历史渲染链路。",
            "80% token 压力触发的一次性工程摘要，并保留压缩点最近 10 个用户轮次及后续消息。",
            "不压缩 Raw 质量参考；所有策略使用相同系统提示和最终工具 schema。",
        ],
        "test_plan": [
            "每条轨迹按项目 token 估算器构造到 90%（约 90K），摘要基线在首次达到 80% 的完整轮次边界压缩。",
            "当前策略使用真实 MemoryRuntime 和恢复工具；Raw 与摘要基线直接回答可见上下文，不执行恢复工具。",
            "每个 case/策略重复运行，累计摘要、最终回答和恢复调用的真实 API token；失败不从分母剔除。",
        ],
        "formulas": [
            "任务成功率 = 包含全部预定义答案锚点的运行数 / API 完成运行数",
            "最终 Prompt 压缩率 = 1 - 候选最终可见 Prompt 估算 token / Raw 最终 Prompt 估算 token",
            "累计 token 节省率 = 1 - 候选累计 token / 对照累计 token",
            "缓存命中率 = prompt_cache_hit_tokens / (prompt_cache_hit_tokens + prompt_cache_miss_tokens)",
        ],
        "gate": "至少 4 类长会话、每策略 2 次；必须报告摘要与恢复开销。该规模只形成 100K 探索性证据，不作为 1M 直接证明。",
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
        "definition": "通过真实 MemoryRuntime、工具 schema、可恢复工具输出和 ask_model 调用链，对比 raw 质量参考、Claude-style 压缩基线、forced_virtualized 与 natural 策略的质量、token 成本、缓存命中和恢复行为。",
        "formulas": [
            "任务成功率 = 正确回答隐藏历史证据锚点的运行数 / 总运行数",
            "Raw 仅作为无压缩质量参考，不作为降本基线",
            "cold-start 未缓存输入降幅 = (渐进式 Claude-style baseline 第 1 次重复未缓存输入 token - 候选第 1 次重复未缓存输入 token) / 渐进式 Claude-style baseline 第 1 次重复未缓存输入 token",
            "缓存命中率 = prompt_cache_hit_tokens / (prompt_cache_hit_tokens + prompt_cache_miss_tokens)",
            "恢复成功率 = 需要恢复且恢复后答对的运行数 / 需要恢复的运行数",
        ],
        "gate": "至少 30 条长会话轨迹、raw/claude_compression_baseline/forced_virtualized/natural 四策略、每策略 3 次；Virtualized 成功率不得比 Raw 低超过 5 个百分点；Claude-style baseline 也需通过质量门禁；降本门禁按第 1 次重复的 cold-start 未缓存输入 token 计算，避免相同 repeat 被服务商前缀缓存污染。",
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
    object_lines = []
    if spec.get("test_object"):
        object_lines = ["## 测试对象", "", *[f"- {item}" for item in spec["test_object"]], ""]
    plan_lines = []
    if spec.get("test_plan"):
        plan_lines = ["## 测试方案", "", *[f"- {item}" for item in spec["test_plan"]], ""]
    lines = [
        f"# {spec['title']}", "", f"- 状态：`{status}`", f"- 指标 ID：`{metric}`", "",
        *object_lines,
        "## 指标定义", "", str(spec["definition"]), "",
        "## 计算公式", "", *[f"- {item}" for item in spec["formulas"]], "",
        *plan_lines,
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
