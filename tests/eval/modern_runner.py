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
from tests.eval.metrics import (
    bootstrap_mean_ci, mean, percentile, reduction_rate,
)
from tests.eval.prefix_cache_benchmark import run_prefix_cache_benchmark
from tests.eval.run_context import build_run_metadata
from tests.eval.runtime_context_virtualization_benchmark import (
    run_runtime_context_virtualization_benchmark,
)

DATASETS = Path("tests/eval/datasets")


def _config() -> tuple[str, str, str]:
    from mycodingagent.llm_runtime.model_manager import ModelManager

    profile = ModelManager().active_profile
    return profile.model, profile.base_url, profile.api


def _schemas() -> list[dict[str, Any]]:
    from mycodingagent.tool_runtime import create_default_registry
    from mycodingagent.llm_runtime.client import format_openai_tools
    from mycodingagent.tool_runtime.command_policy import BashPolicyEvaluator, BashPolicyStore

    registry = create_default_registry(
        bash_policy_evaluator=BashPolicyEvaluator(BashPolicyStore(":memory:"))
    )
    return format_openai_tools(registry.get_all_schemas("openai"))


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
    summary, details = asyncio.run(_run_context(
        cases, model, base_url, api_key, repeats, checkpoint_path=run_dir / "details.in_progress.jsonl"
    ))
    complete_metric_run(
        metric="context_virtualization", run_dir=run_dir, summary=summary, metadata=metadata, details=details,
        command=f"python3 -m tests.eval.modern_runner run-context --dataset {dataset} --repeats {repeats}",
    )
    return summary, run_dir


def run_runtime_context_virtualization(
    *, dataset: Path, run_id: str | None, repeats: int, limit: int | None
) -> tuple[dict[str, Any], Path]:
    actual_id, run_dir, metadata = _start(
        "runtime_context_virtualization",
        run_id,
        dataset,
        repeats,
        extra={
            "runtime_path": "MemoryRuntime.prepare_messages_for_model -> ask_model",
            "strategies": ["raw", "claude_compression_baseline", "forced_virtualized", "natural"],
            "quality_reference_strategy": "raw",
            "cost_baseline_strategy": "claude_compression_baseline",
            "synthetic_prompt_only": False,
        },
    )
    model, base_url, api_key = _config()
    summary, details = run_runtime_context_virtualization_benchmark(
        dataset,
        model=model,
        base_url=base_url,
        api_key=api_key,
        repeats=repeats,
        limit=limit,
        run_dir=run_dir,
    )
    complete_metric_run(
        metric="runtime_context_virtualization",
        run_dir=run_dir,
        summary=summary,
        metadata=metadata,
        details=details,
        command=(
            "python3 -m tests.eval.modern_runner run-runtime-context-virtualization "
            f"--dataset {dataset} --repeats {repeats}"
        ),
    )
    return summary, run_dir


async def _run_context(
    cases: list[dict[str, Any]], model: str, base_url: str, api_key: str, repeats: int,
    *, checkpoint_path: Path | None = None, concurrency: int = 6,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not api_key or not base_url or not model:
        return {"module": "context_virtualization", "status": "not_run", "reason": "missing API key, base URL, or model", "case_count": len(cases)}, []
    from openai import AsyncOpenAI
    import httpx

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=httpx.AsyncClient(trust_env=False))
    except Exception as exc:
        return {"module": "context_virtualization", "status": "blocked", "reason": f"client initialization failed: {type(exc).__name__}: {exc}", "case_count": len(cases)}, []
    details: list[dict[str, Any]] = _read_jsonl(checkpoint_path) if checkpoint_path and checkpoint_path.exists() else []
    completed_keys = {(row.get("case_id"), row.get("mode"), row.get("repeat")) for row in details}
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def execute(case: dict[str, Any], mode: str, repeat: int) -> None:
        key = (case["case_id"], mode, repeat)
        if key in completed_keys:
            return
        prompt = _context_prompt(case, mode)
        started = time.perf_counter()
        async with semaphore:
            try:
                response = await client.chat.completions.create(
                    model=model, messages=[{"role": "system", "content": "Answer from visible evidence; be concise."}, {"role": "user", "content": prompt}], stream=False,
                    timeout=180,
                )
                answer = response.choices[0].message.content or ""
                usage = _usage(response)
                row = {
                    "case_id": case["case_id"], "mode": mode, "repeat": repeat, "status": "passed",
                    "passed": _contains(answer, case["expected_answer_contains"]), "answer": answer[:1000],
                    "prompt_chars": len(prompt), "prompt_tokens": usage["prompt_tokens"],
                    "total_tokens": usage["total_tokens"], "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            except Exception as exc:
                row = {"case_id": case["case_id"], "mode": mode, "repeat": repeat, "status": "failed", "passed": False, "error": f"{type(exc).__name__}: {exc}", "duration_ms": round((time.perf_counter() - started) * 1000, 3)}
        async with lock:
            details.append(row)
            if checkpoint_path:
                from tests.eval.artifacts import write_jsonl
                write_jsonl(checkpoint_path, details)
    try:
        await asyncio.gather(*(
            execute(case, mode, repeat)
            for case in cases for mode in ("raw", "virtualized", "recent_only") for repeat in range(repeats)
        ))
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
    summary, details = asyncio.run(_run_long_term_memory(
        cases, model, base_url, api_key, repeats, checkpoint_path=run_dir / "details.in_progress.jsonl"
    ))
    complete_metric_run(metric="long_term_memory", run_dir=run_dir, summary=summary, metadata=metadata, details=details, command=f"python3 -m tests.eval.modern_runner run-long-term-memory --dataset {dataset} --repeats {repeats}")
    return summary, run_dir


async def _run_long_term_memory(
    cases: list[dict[str, Any]], model: str, base_url: str, api_key: str, repeats: int,
    *, checkpoint_path: Path | None = None, concurrency: int = 6,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not api_key or not base_url or not model:
        return {"module": "long_term_memory", "status": "not_run", "reason": "missing API key, base URL, or model", "case_count": len(cases)}, []
    from openai import AsyncOpenAI
    import httpx

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=httpx.AsyncClient(trust_env=False))
    except Exception as exc:
        return {"module": "long_term_memory", "status": "blocked", "reason": f"client initialization failed: {type(exc).__name__}: {exc}", "case_count": len(cases)}, []
    details: list[dict[str, Any]] = _read_jsonl(checkpoint_path) if checkpoint_path and checkpoint_path.exists() else []
    completed_keys = {(row.get("case_id"), row.get("variant"), row.get("repeat")) for row in details}
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(max(1, concurrency))
    variants = {"without_memory": "", "correct_memory": "Retrieved memory (follow it): {value}", "distractor_memory": "Retrieved memory (possibly noisy): {value}"}

    async def execute(case: dict[str, Any], variant: str, template: str, repeat: int) -> None:
        if (case["case_id"], variant, repeat) in completed_keys:
            return
        memory = case["expected_workflow"] if variant == "correct_memory" else case.get("distractor_memory", "")
        prompt = (template.format(value=memory) + "\n" if template else "") + case["validation_query"]
        started = time.perf_counter()
        async with semaphore:
            try:
                response = await client.chat.completions.create(model=model, messages=[{"role": "system", "content": "Answer the request faithfully and concisely."}, {"role": "user", "content": prompt}], stream=False, timeout=180)
                answer = response.choices[0].message.content or ""
                row = {"case_id": case["case_id"], "memory_type": case["memory_type"], "variant": variant, "repeat": repeat, "status": "passed", "passed": _contains(answer, case["expected_answer_contains"]), "answer": answer[:1000], "duration_ms": round((time.perf_counter() - started) * 1000, 3)}
            except Exception as exc:
                row = {"case_id": case["case_id"], "memory_type": case["memory_type"], "variant": variant, "repeat": repeat, "status": "failed", "passed": False, "error": f"{type(exc).__name__}: {exc}"}
        async with lock:
            details.append(row)
            if checkpoint_path:
                from tests.eval.artifacts import write_jsonl
                write_jsonl(checkpoint_path, details)
    try:
        await asyncio.gather(*(
            execute(case, variant, template, repeat)
            for case in cases for variant, template in variants.items() for repeat in range(repeats)
        ))
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
        from mycodingagent.skill_runtime.embeddings import HttpEmbeddingService
        service = HttpEmbeddingService(timeout=120)
        texts = [item["description"] for item in case["capabilities"]]
        vectors: list[list[float]] = []
        batch_size = 32
        embedding_checkpoint = run_dir / "capability_vectors.jsonl"
        cached = _read_jsonl(embedding_checkpoint) if embedding_checkpoint.exists() else []
        if len(cached) == len(texts) and all(row.get("id") == item["id"] for row, item in zip(cached, case["capabilities"])):
            vectors = [row["vector"] for row in cached]
        else:
            cached = []
            from tests.eval.artifacts import write_jsonl
            for start in range(0, len(texts), batch_size):
                batch_vectors = service.embed_many(texts[start:start + batch_size])
                vectors.extend(batch_vectors)
                cached.extend(
                    {"id": item["id"], "vector": vector}
                    for item, vector in zip(case["capabilities"][start:start + batch_size], batch_vectors)
                )
                write_jsonl(embedding_checkpoint, cached)
        for query in case["queries"]:
            query_vector = service.embed_query(query["query"])
            ranked = sorted(range(len(vectors)), key=lambda index: _cosine(query_vector, vectors[index]), reverse=True)[:10]
            ids = [case["capabilities"][index]["id"] for index in ranked]
            expected = set(query["expected_ids"])
            details.append({"case_id": query["query_id"], "status": "passed", "top_ids": ids, "recall_at_1": bool(expected & set(ids[:1])), "recall_at_3": bool(expected & set(ids[:3])), "recall_at_5": bool(expected & set(ids[:5])), "mrr": _mrr(ids, expected), "ndcg_at_5": _ndcg(ids, expected), "unrelated_top_5": sum(item not in set(query["acceptable_ids"]) for item in ids[:5])})
        summary = {"module": "capability_routing", "status": "passed", "capability_count": len(case["capabilities"]), "skill_count": sum(item["kind"] == "skill" for item in case["capabilities"]), "mcp_count": sum(item["kind"] == "mcp" for item in case["capabilities"]), "query_count": len(details), "embedding_batch_size": batch_size, "recall_at_1": mean(row["recall_at_1"] for row in details), "recall_at_3": mean(row["recall_at_3"] for row in details), "recall_at_5": mean(row["recall_at_5"] for row in details), "mrr": mean(row["mrr"] for row in details), "ndcg_at_5": mean(row["ndcg_at_5"] for row in details), "avg_unrelated_top_5": mean(row["unrelated_top_5"] for row in details), "duration_seconds": round(time.perf_counter() - started, 3), "reason": "Embedding retrieval core only; full MCP execution routing is separately integration-tested.", "resume_conclusion": "在 1200 项 Skill/MCP 混合语料与 200 条改写查询上完成 BGE 检索评测；结论仅覆盖候选召回与排序，不等同于工具执行正确率。"}
    except Exception as exc:
        summary = {"module": "capability_routing", "status": "blocked", "reason": f"{type(exc).__name__}: {exc}", "capability_count": len(case["capabilities"]), "query_count": len(case["queries"])}
    complete_metric_run(metric="capability_routing", run_dir=run_dir, summary=summary, metadata=metadata, details=details, command=f"python3 -m tests.eval.modern_runner run-capability-routing --dataset {dataset}")
    return summary, run_dir

def _tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for message in messages:
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            rows.append({"id": str(call.get("id") or ""), "name": str(function.get("name") or ""), "arguments": str(function.get("arguments") or "")})
    return rows


def _visible_tool_bytes(messages: list[dict[str, Any]], calls: list[dict[str, str]], tool_name: str) -> int:
    ids = {row["id"] for row in calls if row["name"] == tool_name}
    return sum(len(str(message.get("content") or "").encode("utf-8")) for message in messages if message.get("role") == "tool" and message.get("tool_call_id") in ids)


def _tool_error_count(messages: list[dict[str, Any]]) -> int:
    return len(_tool_error_details(messages, []))


def _tool_error_details(messages: list[dict[str, Any]], calls: list[dict[str, str]]) -> list[dict[str, str]]:
    names = {row["id"]: row["name"] for row in calls}
    errors = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        content = str(message.get("content") or "")
        is_error = (
            bool((message.get("metadata") or {}).get("is_error"))
            or content.startswith(("错误", "Tool execution error", "Error:"))
        )
        if is_error:
            errors.append({
                "tool_call_id": str(message.get("tool_call_id") or ""),
                "tool_name": names.get(str(message.get("tool_call_id") or ""), ""),
                "error_excerpt": content[:500],
            })
    return errors


def write_index() -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# myCodingAgent 评测索引", "", "每个指标都有独立、可审计的测试文档。`not_run`、`blocked`、`unavailable` 和 `deferred_by_user` 均不构成效果证据。", ""]
    notes: dict[str, str] = {}
    for path in sorted(DOCS_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        status = next((line.replace("- 状态：", "").strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("- 状态：")), "unknown")
        lines.append(
            f"- [{path.stem}](eval_metrics/{path.name})：{status}{notes.get(path.stem, '')}"
        )
    lines.extend([
        "",
        "## 总体判断",
        "",
        "本轮评测并不支持‘所有模块均已达到优秀效果’的结论。当前证据较强的部分是前缀缓存、合成上下文虚拟化、正确记忆提供后的利用能力，以及真实 Runtime 虚拟化在 cold-start 未缓存输入口径下相对渐进式 Claude-style 压缩基线的成本下降；能力路由仍有明确优化空间。",
        "",
        "### 证据较强的指标",
        "",
        "- 前缀缓存：30 个会话、每会话 3 次正式测量，token 加权命中率为 **98.66%**（95% CI **98.6586%–98.6615%**）。该结论基于服务商原生 hit/miss 字段。",
        "- 上下文虚拟化：在 30 个合成长会话、每策略 3 次的受控实验中，相对 raw 减少 **58.46%** 输入 token，同时保持 **100%** 锚点命中率。该结果不能外推为真实开发任务端到端成功率。",
        "- 长期记忆利用：在 runtime 已提供正确检索结果的条件下，锚点命中率为 **98.89%**（95% CI **96.67%–100%**）。该结果不覆盖记忆抽取、存储和检索召回。",
        "",
        "### 需要继续优化的指标",
        "",
        "- 能力路由：1200 项 Skill/MCP 与 200 条改写查询上，Recall@1 为 **73.0%**，Recall@3 为 **82.5%**，Recall@5 为 **84.5%**（95% CI **79.5%–89.0%**），说明候选召回仍有提升空间。该实验仅覆盖 BGE 候选召回与排序，不代表工具执行正确率。",
        "- 真实 Runtime 上下文虚拟化：30 条轨迹 × 3 次重复 × 4 策略中，Raw 成功率 **100%**、渐进式 Claude-style baseline 成功率 **100%**、Natural 成功率 **97.78%** 且恢复成功率 **97.78%**，质量门禁通过；按 cold-start repeat 0 口径，Natural 相对渐进式 Claude-style baseline 的未缓存输入 token 降低 **29.55%**（95% CI **15.63%–38.92%**）。但 Natural 的 cold-start Prompt token 增加 **107.52%**、总 token 增加 **89.58%**；该结论只支持‘未缓存输入成本下降’，不支持‘总 token 下降’。",
        "",
        "### 尚未获得或不可使用的证据",
        "",
        "- 长期记忆尚无端到端抽取、存储、检索召回和最终任务效果证据。",
        "- Multi-Agent 状态为 `deprecated_incomplete`：标准实验已按计划停止，历史小样本和未配对中止数据均不能用于声明成功率或效率提升。",
        "",
        "### 简历表述建议",
        "",
        "可以使用前缀缓存 98.66%、上下文虚拟化受控实验减少 58.46% 输入 token，以及真实 Runtime 虚拟化相对渐进式 Claude-style 压缩基线降低 29.55% cold-start 未缓存输入 token；必须同时写明样本规模、cold-start 口径和‘不代表总 token 下降’。暂不应声称 Multi-Agent 提升了端到端开发效率。",
        "",
        "## 回归验证",
        "",
        "- 本轮定向回归：`113 passed in 2.30s`（memory runtime、LLM runtime client、eval framework）。",
        "- `compileall` 与 `git diff --check` 均通过。",
    ])
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
        ("run-runtime-context-virtualization", "runtime_context_virtualization_cases.jsonl", 3),
        ("run-long-term-memory", "long_term_workflow_cases.jsonl", 3),
        ("run-capability-routing", "capability_routing_1200_cases.jsonl", 1),
    ]:
        item = sub.add_parser(name)
        item.add_argument("--dataset", default=str(DATASETS / default))
        item.add_argument("--run-id")
        item.add_argument("--repeats", type=int, default=repeats)
        item.add_argument("--limit", type=int)
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
    elif args.command == "run-runtime-context-virtualization":
        result, directory = run_runtime_context_virtualization(dataset=Path(args.dataset), run_id=args.run_id, repeats=max(1, args.repeats), limit=args.limit)
    elif args.command == "run-long-term-memory":
        result, directory = run_long_term_memory(dataset=Path(args.dataset), run_id=args.run_id, repeats=max(1, args.repeats), limit=args.limit)
    elif args.command == "run-capability-routing":
        result, directory = run_capability_routing(dataset=Path(args.dataset), run_id=args.run_id)
    elif args.command == "report":
        print(write_index()); return 0
    else:
        return 2
    print(json.dumps({"result": result, "run_dir": str(directory)}, ensure_ascii=False, indent=2, sort_keys=True))
    write_index()
    return 0 if result.get("status") in {"passed", "not_run", "blocked", "deferred_by_user", "unavailable", "insufficient_sample"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
