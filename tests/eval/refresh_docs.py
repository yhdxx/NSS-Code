"""Regenerate canonical evaluation documents from completed local artifacts.

This command is deliberately offline: it only reads existing JSON evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.eval.artifacts import DOCS_DIR, RUNS_DIR, render_metric_document, write_json
from tests.eval.metrics import bootstrap_mean_ci


CANONICAL_RUNS = {
    "context_virtualization": "standard-context-20260801",
    "runtime_context_virtualization": "standard-runtime-context-20260802",
    "prefix_cache": "standard-prefix-20260801",
    "long_term_memory": "standard-ltm-v2-20260801",
    "capability_routing": "standard-routing-batched-20260801",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _strengthen_summary(
    metric: str, summary: dict[str, Any], details: list[dict[str, Any]],
) -> None:
    if metric == "context_virtualization" and summary.get("status") == "passed":
        virtualized = summary.get("by_mode", {}).get("virtualized", {})
        reduction = 100 * float(virtualized.get("input_reduction_vs_raw", 0))
        summary["resume_conclusion"] = (
            "在 30 个合成长会话、每策略 3 次的受控证据恢复实验中，virtualized 保持 100% "
            f"锚点命中率，并相对 raw 减少 {reduction:.2f}% 输入 token；"
            "该结果不等同于真实开发任务端到端成功率。"
        )
    elif metric == "long_term_memory" and summary.get("status") == "passed":
        correct = summary.get("by_variant", {}).get("correct_memory", {})
        interval = correct.get("accuracy_ci95", {})
        summary["resume_conclusion"] = (
            "在 30 条用户偏好、项目事实与 Workflow 合成样本、每项 3 次中，模型在已提供正确检索结果时的"
            f"锚点命中率为 {100 * float(correct.get('accuracy', 0)):.2f}%（95% CI "
            f"{100 * float(interval.get('low', 0)):.2f}%–{100 * float(interval.get('high', 0)):.2f}%）；"
            "该实验不覆盖记忆抽取、存储和检索召回的端到端准确率。"
        )
    elif metric == "prefix_cache" and summary.get("status") == "passed":
        hit_rate = 100 * float(summary.get("token_weighted_hit_rate", 0))
        summary["resume_conclusion"] = (
            "30 个会话、每会话 1 次预热和 3 次正式测量中，服务商原生字段统计的 token 加权"
            f"前缀缓存命中率为 {hit_rate:.2f}%；system prompt 与工具 schema 固定，项目图谱未常驻 message。"
        )
    elif metric == "capability_routing" and summary.get("status") == "passed":
        fields = ("recall_at_1", "recall_at_3", "recall_at_5", "mrr", "ndcg_at_5")
        summary["metric_ci95"] = {
            field: bootstrap_mean_ci([row[field] for row in details])
            for field in fields
        }
    elif metric == "runtime_context_virtualization" and summary.get("status") == "passed":
        strategies = set(summary.get("strategies") or [])
        summary["quality_reference_strategy"] = "raw"
        summary["cost_baseline_strategy"] = "claude_compression_baseline"
        if "paired_reduction_vs_raw" in summary and "paired_delta_vs_raw_quality_reference" not in summary:
            summary["paired_delta_vs_raw_quality_reference"] = summary.pop("paired_reduction_vs_raw")
        if "claude_compression_baseline" not in strategies:
            summary["claude_baseline_status"] = "missing_in_this_run"
            summary["claude_baseline_quality_gate_passed"] = False
            summary["uncached_reduction_gate_passed"] = False
            summary["efficiency_claim_gate_passed"] = False
            summary["resume_conclusion"] = (
                "现有真实 Runtime 评测覆盖 raw、forced_virtualized、natural 三策略；Raw 只能作为无压缩质量参考，"
                "不能作为降本基线。该结果支持‘端到端恢复链路基本保持答案质量’，但缺少 Claude-style 压缩基线，"
                "不能判断或声明相对 Claude 压缩策略降本。"
            )


def refresh_completed_documents(
    *, runs_dir: Path = RUNS_DIR, docs_dir: Path = DOCS_DIR,
    canonical_runs: dict[str, str] | None = None,
) -> list[Path]:
    outputs: list[Path] = []
    for metric, run_id in (canonical_runs or CANONICAL_RUNS).items():
        run_dir = runs_dir / run_id / metric
        summary = _read_json(run_dir / "summary.json")
        metadata = _read_json(run_dir / "run_metadata.json")
        details = _read_jsonl(run_dir / "details.jsonl")
        payload = _read_json(run_dir / "report_payload.json")
        _strengthen_summary(metric, summary, details)
        report = render_metric_document(metric, summary, metadata, str(payload["command"]), details)
        write_json(run_dir / "summary.json", summary)
        (run_dir / "report.md").write_text(report, encoding="utf-8")
        docs_dir.mkdir(parents=True, exist_ok=True)
        output = docs_dir / f"{metric}.md"
        output.write_text(report, encoding="utf-8")
        outputs.append(output)
    return outputs


if __name__ == "__main__":
    for path in refresh_completed_documents():
        print(path)
