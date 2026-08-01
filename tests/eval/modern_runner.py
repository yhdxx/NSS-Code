"""Versioned evaluation entrypoint.

Real API commands are explicit by design; unit tests must never invoke them.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from pathlib import Path
from typing import Any

from tests.eval.artifacts import (
    DOCS_DIR, RUNS_DIR, complete_metric_run, initialize_not_run_documents, make_run_id,
    metric_run_dir, write_json,
)
from tests.eval.dataset_generators import generate_all
from tests.eval.metrics import bootstrap_mean_ci, mean, percentile, reduction_rate
from tests.eval.prefix_cache_benchmark import run_prefix_cache_benchmark
from tests.eval.run_context import build_run_metadata

DATASETS = Path("tests/eval/datasets")


def _config() -> tuple[str, str, str]:
    from mycodingagent.configuration import CONFIG

    return CONFIG.api.model, CONFIG.api.base_url, CONFIG.api.deepseek_api_key


def _schemas() -> list[dict[str, Any]]:
    from mycodingagent.tool_runtime import create_default_registry
    from mycodingagent.llm_runtime.client import format_openai_tools

    return format_openai_tools(create_default_registry().get_all_schemas("openai"))


def _run_metadata(run_id: str, dataset: Path | None, repeats: int, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    model, base_url, _key = _config()
    return build_run_metadata(
        run_id=run_id, model=model, base_url=base_url, repeats=repeats,
        tool_schemas=_schemas(), dataset_path=dataset, extra=extra,
    ).to_dict()


def _start(metric: str, run_id: str | None, dataset: Path | None, repeats: int, *, extra: dict[str, Any] | None = None) -> tuple[str, Path, dict[str, Any]]:
    actual_id = run_id or make_run_id(metric)
    run_dir = metric_run_dir(RUNS_DIR, actual_id, metric)
    metadata = _run_metadata(actual_id, dataset, repeats, extra)
    return actual_id, run_dir, metadata


def defer_metric(metric: str, *, reason: str, run_id: str | None = None) -> Path:
    actual_id, run_dir, metadata = _start(metric, run_id, None, 0, extra={"deferred_by_user": True})
    complete_metric_run(
        metric=metric, run_dir=run_dir,
        summary={"module": metric, "status": "deferred_by_user", "reason": reason},
        metadata=metadata, command=f"python3 -m tests.eval.modern_runner defer-{metric.replace('_', '-')}",
    )
    return run_dir


def run_prefix_cache(*, dataset: Path, run_id: str | None, repeats: int, limit: int | None) -> tuple[dict[str, Any], Path]:
    actual_id, run_dir, metadata = _start("prefix_cache", run_id, dataset, repeats)
    model, base_url, api_key = _config()
    summary, details = run_prefix_cache_benchmark(
        dataset, model=model, base_url=base_url, api_key=api_key, tool_schemas=_schemas(), repeats=repeats, limit=limit,
    )
    complete_metric_run(
        metric="prefix_cache", run_dir=run_dir, summary=summary, metadata=metadata, details=details,
        command=f"python3 -m tests.eval.modern_runner run-prefix-cache --dataset {dataset} --repeats {repeats}",
    )
    return summary, run_dir


def run_context(*, dataset: Path, run_id: str | None, repeats: int, limit: int | None) -> tuple[dict[str, Any], Path]:
    actual_id, run_dir, metadata = _start("context_virtualization", run_id, dataset, repeats)
    cases = _read_jsonl(dataset)[:limit] if limit else _read_jsonl(dataset)
    model, base_url, api_key = _config()
    summary, details = asyncio.run(_run_context(cases, model, base_url, api_key, repeats))
    complete_metric_run(
        metric="context_virtualization", run_dir=run_dir, summary=summary, metadata=metadata, details=details,
        command=f"python3 -m tests.eval.modern_runner run-context --dataset {dataset} --repeats {repeats}",
    )
    return summary, run_dir


async def _run_context(cases: list[dict[str, Any]], model: str, base_url: str, api_key: str, repeats: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not api_key or not base_url or not model:
        return {"module": "context_virtualization", "status": "not_run", "reason": "missing API key, base URL, or model", "case_count": len(cases)}, []
    from openai import AsyncOpenAI
    import httpx

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=httpx.AsyncClient(trust_env=False))
    except Exception as exc:
        return {"module": "context_virtualization", "status": "blocked", "reason": f"client initialization failed: {type(exc).__name__}: {exc}", "case_count": len(cases)}, []
    details: list[dict[str, Any]] = []
    try:
        for case in cases:
            for mode in ("raw", "virtualized", "recent_only"):
                prompt = _context_prompt(case, mode)
                for repeat in range(repeats):
                    started = time.perf_counter()
                    try:
                        response = await client.chat.completions.create(
                            model=model, messages=[{"role": "system", "content": "Answer from visible evidence; be concise."}, {"role": "user", "content": prompt}], stream=False,
                        )
                        answer = response.choices[0].message.content or ""
                        usage = _usage(response)
                        details.append({
                            "case_id": case["case_id"], "mode": mode, "repeat": repeat, "status": "passed",
                            "passed": _contains(answer, case["expected_answer_contains"]), "answer": answer[:1000],
                            "prompt_chars": len(prompt), "prompt_tokens": usage["prompt_tokens"],
                            "total_tokens": usage["total_tokens"], "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                        })
                    except Exception as exc:
                        details.append({"case_id": case["case_id"], "mode": mode, "repeat": repeat, "status": "failed", "passed": False, "error": f"{type(exc).__name__}: {exc}", "duration_ms": round((time.perf_counter() - started) * 1000, 3)})
    finally:
        await client.close()
    return _context_summary(cases, details, repeats), details


def _context_prompt(case: dict[str, Any], mode: str) -> str:
    if mode == "recent_only":
        messages = case["messages"][-20:]
    elif mode == "virtualized":
        messages = [
            {"role": item.get("role"), "content": ("[virtualized tool output]" if item.get("role") == "tool" else item.get("content", ""))}
            for item in case["messages"]
        ]
    else:
        messages = case["messages"]
    return json.dumps(messages, ensure_ascii=False) + "\nQuestion: " + case["final_query"]


def _context_summary(cases: list[dict[str, Any]], rows: list[dict[str, Any]], repeats: int) -> dict[str, Any]:
    successful = [row for row in rows if row.get("status") == "passed"]
    modes = {}
    raw_token_mean = mean(row["prompt_tokens"] for row in successful if row["mode"] == "raw") if successful else 0.0
    for mode in ("raw", "virtualized", "recent_only"):
        selected = [row for row in successful if row["mode"] == mode]
        tokens = [row["prompt_tokens"] for row in selected]
        modes[mode] = {
            "run_count": len(selected), "success_rate": mean(row["passed"] for row in selected) if selected else None,
            "success_rate_ci95": bootstrap_mean_ci([row["passed"] for row in selected]) if selected else None,
            "prompt_tokens_mean": mean(tokens) if tokens else None, "prompt_tokens_p50": percentile(tokens, .5) if tokens else None,
            "prompt_tokens_p95": percentile(tokens, .95) if tokens else None,
            "input_reduction_vs_raw": reduction_rate(raw_token_mean, mean(tokens)) if tokens else None,
        }
    status = "passed" if len(successful) == len(rows) and len(cases) >= 30 and repeats >= 3 else ("failed" if rows else "not_run")
    return {"module": "context_virtualization", "status": status, "case_count": len(cases), "run_count": len(rows), "completed_run_count": len(successful), "by_mode": modes, "reason": "" if status == "passed" else "requires 30 cases, 3 repeats, and no failed API calls"}


def run_long_term_memory(*, dataset: Path, run_id: str | None, repeats: int, limit: int | None) -> tuple[dict[str, Any], Path]:
    actual_id, run_dir, metadata = _start("long_term_memory", run_id, dataset, repeats)
    cases = _read_jsonl(dataset)[:limit] if limit else _read_jsonl(dataset)
    model, base_url, api_key = _config()
    summary, details = asyncio.run(_run_long_term_memory(cases, model, base_url, api_key, repeats))
    complete_metric_run(metric="long_term_memory", run_dir=run_dir, summary=summary, metadata=metadata, details=details, command=f"python3 -m tests.eval.modern_runner run-long-term-memory --dataset {dataset} --repeats {repeats}")
    return summary, run_dir


async def _run_long_term_memory(cases: list[dict[str, Any]], model: str, base_url: str, api_key: str, repeats: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not api_key or not base_url or not model:
        return {"module": "long_term_memory", "status": "not_run", "reason": "missing API key, base URL, or model", "case_count": len(cases)}, []
    from openai import AsyncOpenAI
    import httpx

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=httpx.AsyncClient(trust_env=False))
    except Exception as exc:
        return {"module": "long_term_memory", "status": "blocked", "reason": f"client initialization failed: {type(exc).__name__}: {exc}", "case_count": len(cases)}, []
    details: list[dict[str, Any]] = []
    variants = {"without_memory": "", "correct_memory": "Retrieved memory (follow it): {value}", "distractor_memory": "Retrieved memory (possibly noisy): {value}"}
    try:
        for case in cases:
            for variant, template in variants.items():
                memory = case["expected_workflow"] if variant == "correct_memory" else case.get("distractor_memory", "")
                prompt = (template.format(value=memory) + "\n" if template else "") + case["validation_query"]
                for repeat in range(repeats):
                    started = time.perf_counter()
                    try:
                        response = await client.chat.completions.create(model=model, messages=[{"role": "system", "content": "Answer the request faithfully and concisely."}, {"role": "user", "content": prompt}], stream=False)
                        answer = response.choices[0].message.content or ""
                        details.append({"case_id": case["case_id"], "memory_type": case["memory_type"], "variant": variant, "repeat": repeat, "status": "passed", "passed": _memory_match(answer, case["expected_workflow"]), "answer": answer[:1000], "duration_ms": round((time.perf_counter() - started) * 1000, 3)})
                    except Exception as exc:
                        details.append({"case_id": case["case_id"], "memory_type": case["memory_type"], "variant": variant, "repeat": repeat, "status": "failed", "passed": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        await client.close()
    completed = [row for row in details if row["status"] == "passed"]
    by_variant = {}
    for variant in variants:
        values = [row["passed"] for row in completed if row["variant"] == variant]
        by_variant[variant] = {"run_count": len(values), "accuracy": mean(values) if values else None, "accuracy_ci95": bootstrap_mean_ci(values) if values else None}
    by_type = {}
    for type_name in sorted({case["memory_type"] for case in cases}):
        by_type[type_name] = {variant: mean(row["passed"] for row in completed if row["variant"] == variant and row["memory_type"] == type_name) for variant in variants}
    status = "passed" if len(cases) >= 30 and repeats >= 3 and len(completed) == len(details) else ("failed" if details else "not_run")
    return {"module": "long_term_memory", "status": status, "case_count": len(cases), "run_count": len(details), "by_variant": by_variant, "by_memory_type": by_type, "reason": "" if status == "passed" else "requires 30 cases, 3 repeats, and no failed API calls"}, details


def run_capability_routing(*, dataset: Path, run_id: str | None) -> tuple[dict[str, Any], Path]:
    """Run local embedding retrieval; it deliberately fails closed when BGE is unavailable."""
    actual_id, run_dir, metadata = _start("capability_routing", run_id, dataset, 1)
    case = _read_jsonl(dataset)[0]
    started = time.perf_counter()
    details: list[dict[str, Any]] = []
    try:
        from mycodingagent.skill_runtime.embeddings import BgeHttpEmbeddingService
        service = BgeHttpEmbeddingService(timeout=60)
        texts = [item["description"] for item in case["capabilities"]]
        vectors = service.embed_many(texts)
        for query in case["queries"]:
            query_vector = service.embed_many([query["query"]])[0]
            ranked = sorted(range(len(vectors)), key=lambda index: _cosine(query_vector, vectors[index]), reverse=True)[:10]
            ids = [case["capabilities"][index]["id"] for index in ranked]
            expected = set(query["expected_ids"])
            details.append({"case_id": query["query_id"], "status": "passed", "top_ids": ids, "recall_at_1": bool(expected & set(ids[:1])), "recall_at_3": bool(expected & set(ids[:3])), "recall_at_5": bool(expected & set(ids[:5])), "mrr": _mrr(ids, expected), "ndcg_at_5": _ndcg(ids, expected), "unrelated_top_5": sum(item not in set(query["acceptable_ids"]) for item in ids[:5])})
        summary = {"module": "capability_routing", "status": "passed", "capability_count": len(case["capabilities"]), "query_count": len(details), "recall_at_1": mean(row["recall_at_1"] for row in details), "recall_at_3": mean(row["recall_at_3"] for row in details), "recall_at_5": mean(row["recall_at_5"] for row in details), "mrr": mean(row["mrr"] for row in details), "ndcg_at_5": mean(row["ndcg_at_5"] for row in details), "avg_unrelated_top_5": mean(row["unrelated_top_5"] for row in details), "duration_seconds": round(time.perf_counter() - started, 3), "reason": "Embedding retrieval core only; full MCP execution routing is separately integration-tested."}
    except Exception as exc:
        summary = {"module": "capability_routing", "status": "blocked", "reason": f"{type(exc).__name__}: {exc}", "capability_count": len(case["capabilities"]), "query_count": len(case["queries"])}
    complete_metric_run(metric="capability_routing", run_dir=run_dir, summary=summary, metadata=metadata, details=details, command=f"python3 -m tests.eval.modern_runner run-capability-routing --dataset {dataset}")
    return summary, run_dir


def run_multi_agent(*, dataset: Path, run_id: str | None, repeats: int, limit: int | None, project_size: str | None) -> tuple[dict[str, Any], Path]:
    actual_id, run_dir, metadata = _start("multi_agent", run_id, dataset, repeats)
    from tests.eval.runner import _run_multi_agent_case

    cases = _read_jsonl(dataset)
    if project_size:
        cases = [case for case in cases if case.get("project_size") == project_size]
    if limit:
        cases = cases[:limit]
    details: list[dict[str, Any]] = []
    for repeat in range(repeats):
        for ordinal, case in enumerate(cases, 1):
            for mode in ("direct", "multi_agent"):
                row = asyncio.run(_run_multi_agent_case(case, mode=mode, ordinal=ordinal))
                row["repeat"] = repeat
                row.setdefault("status", "passed" if row.get("passed") else "failed")
                details.append(row)
                # Persist after every expensive run so interruption does not erase evidence.
                from tests.eval.artifacts import write_jsonl
                write_jsonl(run_dir / "details.in_progress.jsonl", details)
    summary = _multi_agent_summary(cases, details, repeats)
    complete_metric_run(metric="multi_agent", run_dir=run_dir, summary=summary, metadata=metadata, details=details, command=f"python3 -m tests.eval.modern_runner run-multi-agent --dataset {dataset} --repeats {repeats}")
    return summary, run_dir


def _multi_agent_summary(cases: list[dict[str, Any]], rows: list[dict[str, Any]], repeats: int) -> dict[str, Any]:
    by_mode = {}
    for mode in ("direct", "multi_agent"):
        selected = [row for row in rows if row.get("mode") == mode]
        pass_values = [bool(row.get("passed")) for row in selected]
        durations = [float(row.get("duration_seconds", 0)) for row in selected]
        tokens = [int(row.get("total_tokens", 0)) for row in selected]
        by_mode[mode] = {
            "run_count": len(selected), "success_rate": mean(pass_values), "success_rate_ci95": bootstrap_mean_ci(pass_values),
            "duration_mean_seconds": mean(durations), "duration_p50_seconds": percentile(durations, .5), "duration_p95_seconds": percentile(durations, .95),
            "total_tokens_mean": mean(tokens), "tool_calls_mean": mean(row.get("tool_call_count", 0) for row in selected),
            "failed_or_timeout_count": sum(row.get("status") in {"failed", "timeout"} or not row.get("passed") for row in selected),
        }
    status = "passed" if len(cases) >= 30 and repeats >= 3 and len(rows) == len(cases) * repeats * 2 else "insufficient_sample"
    return {"module": "multi_agent", "status": status, "case_count": len(cases), "run_count": len(rows), "repeats": repeats, "by_mode": by_mode, "reason": "" if status == "passed" else "requires 30 cases and 3 repeats per mode"}


def write_index() -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# myCodingAgent 评测索引", "", "每个指标都有独立、可审计的测试文档。`not_run`、`blocked`、`unavailable` 和 `deferred_by_user` 均不构成效果证据。", ""]
    for path in sorted(DOCS_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        status = next((line.replace("- 状态：", "").strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("- 状态：")), "unknown")
        lines.append(f"- [{path.stem}]({path.name})：{status}")
    output = Path("docs/eval_report.md")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    return {"prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0), "total_tokens": int(getattr(usage, "total_tokens", 0) or 0)}


def _contains(answer: str, expected: list[str]) -> bool:
    return all(item in answer for item in expected)


def _memory_match(answer: str, expected: str) -> bool:
    anchors = [part for part in expected.replace("。", "，").split("，") if len(part) >= 4]
    return bool(anchors) and sum(anchor in answer for anchor in anchors) >= max(1, math.ceil(len(anchors) / 2))


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return numerator / denominator if denominator else 0.0


def _mrr(ids: list[str], expected: set[str]) -> float:
    return next((1 / index for index, item in enumerate(ids, 1) if item in expected), 0.0)


def _ndcg(ids: list[str], expected: set[str]) -> float:
    dcg = sum(1 / math.log2(index + 1) for index, item in enumerate(ids[:5], 1) if item in expected)
    ideal = sum(1 / math.log2(index + 1) for index in range(1, min(5, len(expected)) + 1))
    return dcg / ideal if ideal else 0.0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run versioned effectiveness evaluations. Real API commands are explicit.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate-datasets")
    sub.add_parser("init-docs")
    for name, default, repeats in [
        ("run-prefix-cache", "prefix_cache_cases.jsonl", 3),
        ("run-context", "context_virtualization_cases.jsonl", 3),
        ("run-long-term-memory", "long_term_workflow_cases.jsonl", 3),
        ("run-capability-routing", "capability_routing_1200_cases.jsonl", 1),
        ("run-multi-agent", "multi_agent_tasks.jsonl", 3),
    ]:
        item = sub.add_parser(name)
        item.add_argument("--dataset", default=str(DATASETS / default))
        item.add_argument("--run-id")
        item.add_argument("--repeats", type=int, default=repeats)
        item.add_argument("--limit", type=int)
        if name == "run-multi-agent":
            item.add_argument("--project-size", choices=["small", "medium", "large"])
    for metric in ("project-graph", "code-general-ab"):
        item = sub.add_parser(f"defer-{metric}")
        item.add_argument("--run-id")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "generate-datasets":
        print(json.dumps(generate_all(), ensure_ascii=False, indent=2, sort_keys=True)); return 0
    if args.command == "init-docs":
        initialize_not_run_documents(); print(write_index()); return 0
    if args.command == "run-prefix-cache":
        result, directory = run_prefix_cache(dataset=Path(args.dataset), run_id=args.run_id, repeats=max(1, args.repeats), limit=args.limit)
    elif args.command == "run-context":
        result, directory = run_context(dataset=Path(args.dataset), run_id=args.run_id, repeats=max(1, args.repeats), limit=args.limit)
    elif args.command == "run-long-term-memory":
        result, directory = run_long_term_memory(dataset=Path(args.dataset), run_id=args.run_id, repeats=max(1, args.repeats), limit=args.limit)
    elif args.command == "run-capability-routing":
        result, directory = run_capability_routing(dataset=Path(args.dataset), run_id=args.run_id)
    elif args.command == "run-multi-agent":
        result, directory = run_multi_agent(dataset=Path(args.dataset), run_id=args.run_id, repeats=max(1, args.repeats), limit=args.limit, project_size=args.project_size)
    elif args.command.startswith("defer-"):
        metric = args.command.removeprefix("defer-").replace("-", "_")
        directory = defer_metric(metric, reason="用户正在修改项目图谱逻辑；图谱与 Code/General 实测已显式延期。", run_id=args.run_id)
        result = {"status": "deferred_by_user"}
    elif args.command == "report":
        print(write_index()); return 0
    else:
        return 2
    print(json.dumps({"result": result, "run_dir": str(directory)}, ensure_ascii=False, indent=2, sort_keys=True))
    write_index()
    return 0 if result.get("status") in {"passed", "not_run", "blocked", "deferred_by_user", "unavailable"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
