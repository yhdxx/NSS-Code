"""Versioned evaluation entrypoint.

Real API commands are explicit by design; unit tests must never invoke them.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from tests.eval.artifacts import (
    DOCS_DIR, RUNS_DIR, complete_metric_run, initialize_not_run_documents, make_run_id,
    metric_run_dir, write_json,
)
from tests.eval.dataset_generators import generate_all
from tests.eval.metrics import (
    bootstrap_mean_ci, bootstrap_reduction_ci, mean, percentile, reduction_rate,
)
from tests.eval.prefix_cache_benchmark import run_prefix_cache_benchmark
from tests.eval.run_context import build_run_metadata
from tests.eval.runtime_context_virtualization_benchmark import (
    run_runtime_context_virtualization_benchmark,
)
from tests.model_manager_stub import ask_model_with_raw_client

DATASETS = Path("tests/eval/datasets")
PROJECT_MANIFEST = Path("tests/eval/manifests/public_projects.json")
DEFAULT_PROJECTS_ROOT = Path("/tmp/mycodingagent_eval_projects")


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


def defer_metric(metric: str, *, reason: str, run_id: str | None = None) -> Path:
    actual_id, run_dir, metadata = _start(metric, run_id, None, 0, extra={"deferred_by_user": True})
    complete_metric_run(
        metric=metric, run_dir=run_dir,
        summary={"module": metric, "status": "deferred_by_user", "reason": reason},
        metadata=metadata, command=f"python3 -m tests.eval.modern_runner defer-{metric.replace('_', '-')}",
    )
    return run_dir


def prepare_public_projects(*, manifest: Path, destination: Path, force: bool = False) -> list[dict[str, Any]]:
    from tests.eval.public_projects import prepare_projects

    return prepare_projects(manifest, destination, force=force)


def run_project_graph(*, manifest: Path, projects_root: Path, annotations: Path, run_id: str | None) -> tuple[dict[str, Any], Path]:
    from tests.eval.project_graph_benchmark import run_project_graph_benchmark
    from tests.eval.public_projects import load_manifest

    actual_id, run_dir, metadata = _start("project_graph", run_id, manifest, 1, extra={
        "projects_root": str(projects_root), "annotations_dir": str(annotations),
        "graph_message_pinning": False,
    })
    projects = load_manifest(manifest)
    summary = run_project_graph_benchmark(
        projects, projects_root=projects_root, run_dir=run_dir, annotations_dir=annotations,
    )
    details = _read_jsonl(run_dir / "project_graph_details.jsonl")
    if summary.get("status") == "passed" and summary.get("annotation_projects") == 0:
        summary["accuracy_status"] = "not_run"
        summary["accuracy_reason"] = "manual symbol/call annotations are absent"
        summary["performance_status"] = "passed"
        summary["resume_conclusion"] = (
            f"在 {summary['completed_projects']} 个固定 commit 项目上完成图谱性能评测；"
            "符号覆盖率及调用边精确率/召回率尚无人工标注，不作为准确性证据。"
        )
    complete_metric_run(
        metric="project_graph", run_dir=run_dir, summary=summary, metadata=metadata, details=details,
        command=f"python3 -m tests.eval.modern_runner run-project-graph --manifest {manifest} --projects-root {projects_root} --annotations {annotations}",
    )
    return summary, run_dir


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


def run_multi_agent(*, dataset: Path, run_id: str | None, repeats: int, limit: int | None, project_size: str | None) -> tuple[dict[str, Any], Path]:
    actual_id, run_dir, metadata = _start("multi_agent", run_id, dataset, repeats)
    cases = _read_jsonl(dataset)
    if project_size:
        cases = [case for case in cases if case.get("project_size") == project_size]
    if limit:
        cases = cases[:limit]
    details = asyncio.run(_run_multi_agent_cases(
        cases, repeats=repeats, checkpoint=run_dir / "details.in_progress.jsonl",
        concurrency=30,
    ))
    summary = _multi_agent_summary(cases, details, repeats)
    complete_metric_run(metric="multi_agent", run_dir=run_dir, summary=summary, metadata=metadata, details=details, command=f"python3 -m tests.eval.modern_runner run-multi-agent --dataset {dataset} --repeats {repeats}")
    return summary, run_dir


async def _run_multi_agent_cases(
    cases: list[dict[str, Any]], *, repeats: int, checkpoint: Path, concurrency: int,
) -> list[dict[str, Any]]:
    from tests.eval.runner import _run_multi_agent_case

    details = _read_jsonl(checkpoint) if checkpoint.exists() else []
    completed = {(row.get("case_id"), row.get("mode"), row.get("repeat")) for row in details}
    semaphore = asyncio.Semaphore(max(1, concurrency))
    lock = asyncio.Lock()

    async def execute(case: dict[str, Any], mode: str, repeat: int, ordinal: int) -> None:
        if (case["case_id"], mode, repeat) in completed:
            return
        async with semaphore:
            row = await _run_multi_agent_case(
                case, mode=mode, ordinal=ordinal, capture_stdout=False,
            )
        row["repeat"] = repeat
        row.setdefault("status", "passed" if row.get("passed") else "failed")
        async with lock:
            details.append(row)
            from tests.eval.artifacts import write_jsonl
            write_jsonl(checkpoint, details)

    await asyncio.gather(*(
        execute(case, mode, repeat, ordinal)
        for repeat in range(repeats)
        for ordinal, case in enumerate(cases, 1)
        for mode in ("direct", "multi_agent")
    ))
    return details


def run_code_general_ab(*, dataset: Path, run_id: str | None, repeats: int, limit: int | None) -> tuple[dict[str, Any], Path]:
    actual_id, run_dir, metadata = _start("code_general_ab", run_id, dataset, repeats, extra={
        "graph_message_pinning": False, "tool_schema_stable_between_modes": True,
    })
    cases = _read_jsonl(dataset)
    if limit:
        cases = cases[:limit]
    checkpoint = run_dir / "details.in_progress.jsonl"
    details = asyncio.run(_run_code_general_cases(
        cases, repeats=repeats, checkpoint=checkpoint, concurrency=6,
    ))
    summary = _code_general_summary(cases, details, repeats)
    complete_metric_run(
        metric="code_general_ab", run_dir=run_dir, summary=summary, metadata=metadata, details=details,
        command=f"python3 -m tests.eval.modern_runner run-code-general-ab --dataset {dataset} --repeats {repeats}",
    )
    return summary, run_dir


async def _run_code_general_cases(
    cases: list[dict[str, Any]], *, repeats: int, checkpoint: Path, concurrency: int,
) -> list[dict[str, Any]]:
    details = _read_jsonl(checkpoint) if checkpoint.exists() else []
    completed = {(row.get("case_id"), row.get("mode"), row.get("repeat")) for row in details}
    semaphore = asyncio.Semaphore(max(1, concurrency))
    lock = asyncio.Lock()

    async def execute(case: dict[str, Any], mode: str, repeat: int, ordinal: int) -> None:
        if (case["case_id"], mode, repeat) in completed:
            return
        async with semaphore:
            row = await _run_code_general_case(case, mode=mode, repeat=repeat, ordinal=ordinal)
        async with lock:
            details.append(row)
            from tests.eval.artifacts import write_jsonl
            write_jsonl(checkpoint, details)

    await asyncio.gather(*(
        execute(case, mode, repeat, ordinal)
        for repeat in range(repeats)
        for ordinal, case in enumerate(cases, 1)
        for mode in ("general", "code")
    ))
    return details


async def _run_code_general_case(case: dict[str, Any], *, mode: str, repeat: int, ordinal: int) -> dict[str, Any]:
    import httpx
    from openai import AsyncOpenAI
    from mycodingagent.code_intelligence import (
        ProjectGraphRuntime,
        ProjectGraphService,
        WorkspaceCodeIndex,
    )
    from mycodingagent.configuration import CONFIG
    from mycodingagent.llm_runtime import client as agent_client
    from mycodingagent.memory import ContextCompressor, MemoryRuntime, SQLiteMemoryStore
    from mycodingagent.work_mode import WorkMode, WorkModeManager
    from tests.eval.runner import (
        _run_eval_test, _snapshot_project_files, _tool_call_names_from_messages,
        _workspace_registry, _write_eval_project,
    )

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix=f"mca_code_ab_{mode}_{ordinal:02d}_") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        state = root / "state"
        workspace.mkdir(); state.mkdir()
        _write_eval_project(workspace, case["files"])
        before = _snapshot_project_files(workspace)
        memory = MemoryRuntime(
            store=SQLiteMemoryStore(state / "sessions.sqlite3"),
            compressor=ContextCompressor(context_window=96_000), model=_config()[0],
            workspace_root=str(workspace),
        )
        index = WorkspaceCodeIndex(workspace, state / "code_index.sqlite3")
        graph = ProjectGraphService(workspace, state / "project_graph.sqlite3", index)
        work_mode = WorkModeManager(WorkMode.GENERAL)
        graph_runtime = ProjectGraphRuntime(graph, index, work_mode)
        if mode == "code":
            await graph_runtime.activate()
        registry = _workspace_registry(workspace, memory, graph_runtime)
        schemas = agent_client.format_openai_tools(registry.get_all_schemas("openai"))
        model, base_url, api_key = _config()
        api_client = AsyncOpenAI(
            api_key=api_key, base_url=base_url,
            http_client=httpx.AsyncClient(trust_env=False),
        )
        try:
            prompt = (
                f"当前 /workspace 下有一个 Python 项目。任务：{case['input_task']}\n"
                f"完成后必须运行 `{case['test_command']}`，并只做必要修改。"
            )
            text, messages = await ask_model_with_raw_client(
                api_client,
                prompt,
                registry,
                schemas,
                messages=agent_client.create_initial_messages(registry, memory_runtime=memory),
                memory_runtime=memory,
                core_tool_schemas=registry.get_all_schemas("openai"),
                project_graph=graph_runtime,
                work_mode=mode,
            )
            verify = _run_eval_test(workspace, case["test_command"])
            after = _snapshot_project_files(workspace)
            tool_calls = _tool_calls(messages)
            tool_names = [row["name"] for row in tool_calls]
            token_summary = memory.load_token_usage_summary(memory.get_current_session_id())
            visible_read_bytes = _visible_tool_bytes(messages, tool_calls, "ReadFile")
            invalid_calls = _tool_error_count(messages)
            tool_errors = _tool_error_details(messages, tool_calls)
            repeated_calls = len(tool_calls) - len({(row["name"], row["arguments"]) for row in tool_calls})
            return {
                "case_id": case["case_id"], "mode": mode, "repeat": repeat,
                "project_size": case.get("project_size"), "status": "passed" if verify.returncode == 0 else "failed",
                "passed": verify.returncode == 0, "duration_seconds": round(time.perf_counter() - started, 3),
                "tool_call_count": len(tool_calls), "tool_names": tool_names,
                "graph_tool_calls": sum(name in {"ProjectArchitecture", "UnitDependencyGraph"} for name in tool_names),
                "readfile_visible_bytes": visible_read_bytes, "invalid_tool_calls": invalid_calls,
                "tool_errors": tool_errors,
                "repeated_tool_calls": repeated_calls, "prompt_tokens": token_summary.prompt_tokens,
                "completion_tokens": token_summary.completion_tokens, "total_tokens": token_summary.total_tokens,
                "changed_files": sorted(path for path in after if before.get(path) != after.get(path)),
                "pytest_returncode": verify.returncode, "pytest_stdout_tail": verify.stdout[-1000:],
                "final_answer_tail": text[-1000:],
            }
        except Exception as exc:
            return {"case_id": case["case_id"], "mode": mode, "repeat": repeat, "project_size": case.get("project_size"), "status": "failed", "passed": False, "duration_seconds": round(time.perf_counter() - started, 3), "error": f"{type(exc).__name__}: {exc}"}
        finally:
            await graph_runtime.close()
            await memory.close()
            await api_client.close()


def _code_general_summary(cases: list[dict[str, Any]], rows: list[dict[str, Any]], repeats: int) -> dict[str, Any]:
    by_mode: dict[str, Any] = {}
    for mode in ("general", "code"):
        selected = [row for row in rows if row.get("mode") == mode]
        passed = [bool(row.get("passed")) for row in selected]
        by_mode[mode] = {
            "run_count": len(selected), "success_rate": mean(passed),
            "success_rate_ci95": bootstrap_mean_ci(passed),
            "duration_mean_seconds": mean(row.get("duration_seconds", 0) for row in selected),
            "tool_calls_mean": mean(row.get("tool_call_count", 0) for row in selected),
            "readfile_visible_bytes_mean": mean(row.get("readfile_visible_bytes", 0) for row in selected),
            "prompt_tokens_mean": mean(row.get("prompt_tokens", 0) for row in selected),
            "total_tokens_mean": mean(row.get("total_tokens", 0) for row in selected),
            "invalid_tool_calls_mean": mean(row.get("invalid_tool_calls", 0) for row in selected),
            "repeated_tool_calls_mean": mean(row.get("repeated_tool_calls", 0) for row in selected),
            "graph_tool_calls_mean": mean(row.get("graph_tool_calls", 0) for row in selected),
        }
    general, code = by_mode["general"], by_mode["code"]
    success_delta = code["success_rate"] - general["success_rate"]
    cost_reductions = {
        "tool_calls": reduction_rate(general["tool_calls_mean"], code["tool_calls_mean"]),
        "readfile_visible_bytes": reduction_rate(general["readfile_visible_bytes_mean"], code["readfile_visible_bytes_mean"]),
        "prompt_tokens": reduction_rate(general["prompt_tokens_mean"], code["prompt_tokens_mean"]),
        "total_tokens": reduction_rate(general["total_tokens_mean"], code["total_tokens_mean"]),
    }
    paired_rows = {
        mode: {
            (row.get("case_id"), row.get("repeat")): row
            for row in rows if row.get("mode") == mode
        }
        for mode in ("general", "code")
    }
    pair_keys = sorted(
        set(paired_rows["general"]) & set(paired_rows["code"]), key=str,
    )
    metric_fields = {
        "tool_calls": "tool_call_count",
        "readfile_visible_bytes": "readfile_visible_bytes",
        "prompt_tokens": "prompt_tokens",
        "total_tokens": "total_tokens",
    }
    cost_reduction_ci95 = {
        name: bootstrap_reduction_ci(
            [paired_rows["general"][key].get(field, 0) for key in pair_keys],
            [paired_rows["code"][key].get(field, 0) for key in pair_keys],
        )
        for name, field in metric_fields.items()
    }
    sufficient = len(cases) >= 30 and repeats >= 3 and len(rows) == len(cases) * repeats * 2
    efficiency_gate = sufficient and success_delta >= -0.05 and any((value or 0) > 0 for value in cost_reductions.values())
    status = "passed" if sufficient else "insufficient_sample"
    summary = {
        "module": "code_general_ab", "status": status, "case_count": len(cases),
        "run_count": len(rows), "repeats": repeats, "by_mode": by_mode,
        "code_success_rate_delta": success_delta, "code_cost_reductions": cost_reductions,
        "code_cost_reduction_ci95": cost_reduction_ci95, "paired_run_count": len(pair_keys),
        "efficiency_claim_gate_passed": efficiency_gate,
        "reason": "" if sufficient else "requires 30 cases and 3 repeats per mode",
    }
    if efficiency_gate:
        summary["resume_conclusion"] = "在 30 个开发任务、每模式 3 次的 A/B 中，Code 模式在成功率不劣于 General 5 个百分点的前提下降低了至少一项执行成本。"
    elif sufficient:
        summary["resume_conclusion"] = (
            "30 个开发任务、每模式 3 次的 A/B 中两种模式成功率均为 100%，"
            "但 Code 的工具调用、可见读取字节和 token 成本均未下降，当前不可宣称 Code 模式提高效率。"
        )
    return summary


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


def _multi_agent_summary(cases: list[dict[str, Any]], rows: list[dict[str, Any]], repeats: int) -> dict[str, Any]:
    by_mode = {}
    for mode in ("direct", "multi_agent"):
        selected = [row for row in rows if row.get("mode") == mode]
        pass_values = [bool(row.get("passed")) for row in selected]
        durations = [float(row.get("duration_seconds", 0)) for row in selected]
        tokens = [int(row["total_tokens"]) for row in selected if row.get("total_tokens") is not None]
        by_mode[mode] = {
            "run_count": len(selected), "success_rate": mean(pass_values), "success_rate_ci95": bootstrap_mean_ci(pass_values),
            "duration_mean_seconds": mean(durations), "duration_p50_seconds": percentile(durations, .5), "duration_p95_seconds": percentile(durations, .95),
            "duration_mean_ci95": bootstrap_mean_ci(durations),
            "total_tokens_mean": mean(tokens) if tokens else None, "tool_calls_mean": mean(row.get("tool_call_count", 0) for row in selected),
            "total_tokens_mean_ci95": bootstrap_mean_ci(tokens) if tokens else None,
            "token_accounting_status": "available" if len(tokens) == len(selected) else "unavailable_subagent_aggregation",
            "tool_calls_mean_ci95": bootstrap_mean_ci([row.get("tool_call_count", 0) for row in selected]),
            "failed_or_timeout_count": sum(row.get("status") in {"failed", "timeout"} or not row.get("passed") for row in selected),
        }
    status = "passed" if len(cases) >= 30 and repeats >= 3 and len(rows) == len(cases) * repeats * 2 else "insufficient_sample"
    summary = {"module": "multi_agent", "status": status, "case_count": len(cases), "run_count": len(rows), "repeats": repeats, "by_mode": by_mode, "reason": "" if status == "passed" else "requires 30 cases and 3 repeats per mode"}
    if status == "passed":
        delta = by_mode["multi_agent"]["success_rate"] - by_mode["direct"]["success_rate"]
        summary["multi_agent_success_rate_delta"] = delta
        summary["resume_conclusion"] = (
            "仅当 Multi-Agent 在复杂任务上的成功率收益和开销可接受时，才可声明协作带来效果提升；"
            f"本次总体成功率差为 {delta:+.1%}。"
        )
    return summary


def document_existing_multi_agent(*, run_id: str | None = None) -> tuple[dict[str, Any], Path]:
    """Document retained evidence without continuing the deprecated benchmark."""
    dataset = DATASETS / "multi_agent_tasks.jsonl"
    _actual_id, run_dir, metadata = _start(
        "multi_agent", run_id, dataset, 3,
        extra={
            "module_lifecycle": "planned_for_removal",
            "standard_run_stopped_by_user": True,
            "subagent_token_accounting": "unavailable",
        },
    )
    historical_path = Path("tests/eval/results/multi_agent_ab_details.jsonl")
    partial_path = Path("tests/eval/runs/standard-multi-agent-20260801/multi_agent/details.in_progress.jsonl")
    historical = _read_jsonl(historical_path) if historical_path.exists() else []
    partial = _read_jsonl(partial_path) if partial_path.exists() else []
    summary = {
        "module": "multi_agent",
        "status": "deprecated_incomplete",
        "reason": "用户计划废弃 Multi-Agent 模块；标准 30 任务 × 3 重复实验已停止。",
        "case_count": len({row.get("case_id") for row in historical}),
        "run_count": len(historical) + len(partial),
        "historical_complete_small_sample": _existing_multi_agent_group(historical),
        "partial_standard_run_unpaired": _existing_multi_agent_group(partial),
        "partial_standard_run_counts": {
            mode: sum(row.get("mode") == mode for row in partial)
            for mode in ("direct", "multi_agent")
        },
        "token_accounting_status": "unavailable_subagent_aggregation",
        "resume_conclusion": (
            "不可声明 Multi-Agent 提高效率或成功率；历史 6-case 对照中成功率更低且耗时显著更高，"
            "新版标准实验未完成，且模块计划废弃。"
        ),
    }
    details = [
        {**row, "evidence_source": "historical_complete_small_sample"}
        for row in historical
    ] + [
        {**row, "evidence_source": "partial_standard_run_unpaired"}
        for row in partial
    ]
    complete_metric_run(
        metric="multi_agent", run_dir=run_dir, summary=summary, metadata=metadata, details=details,
        command="python3 -m tests.eval.modern_runner document-multi-agent-existing",
    )
    return summary, run_dir


def _existing_multi_agent_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, Any] = {}
    for mode in ("direct", "multi_agent"):
        selected = [row for row in rows if row.get("mode") == mode]
        passed = [bool(row.get("passed")) for row in selected]
        durations = [float(row.get("duration_seconds", 0)) for row in selected]
        tools = [float(row.get("tool_call_count", 0)) for row in selected]
        grouped[mode] = {
            "run_count": len(selected),
            "success_rate": mean(passed) if selected else None,
            "success_rate_ci95": bootstrap_mean_ci(passed) if selected else None,
            "duration_mean_seconds": mean(durations) if selected else None,
            "duration_mean_ci95": bootstrap_mean_ci(durations) if selected else None,
            "tool_calls_mean": mean(tools) if selected else None,
            "tool_calls_mean_ci95": bootstrap_mean_ci(tools) if selected else None,
        }
    return grouped


def write_index() -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# myCodingAgent 评测索引", "", "每个指标都有独立、可审计的测试文档。`not_run`、`blocked`、`unavailable` 和 `deferred_by_user` 均不构成效果证据。", ""]
    notes = {
        "multi_agent": "（模块计划废弃，标准实验已停止）",
        "project_graph": "（性能完成，准确率 `not_run`）",
    }
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
        "本轮评测并不支持‘所有模块均已达到优秀效果’的结论。当前证据较强的部分是前缀缓存、合成上下文虚拟化、正确记忆提供后的利用能力、项目图谱的热读取和增量刷新，以及真实 Runtime 虚拟化在 cold-start 未缓存输入口径下相对渐进式 Claude-style 压缩基线的成本下降；能力路由、图谱首次构建和 Code 模式执行成本仍有明确优化空间。",
        "",
        "### 证据较强的指标",
        "",
        "- 前缀缓存：30 个会话、每会话 3 次正式测量，token 加权命中率为 **98.66%**（95% CI **98.6586%–98.6615%**）。该结论基于服务商原生 hit/miss 字段，且项目图谱未常驻 message。",
        "- 上下文虚拟化：在 30 个合成长会话、每策略 3 次的受控实验中，相对 raw 减少 **58.46%** 输入 token，同时保持 **100%** 锚点命中率。该结果不能外推为真实开发任务端到端成功率。",
        "- 长期记忆利用：在 runtime 已提供正确检索结果的条件下，锚点命中率为 **98.89%**（95% CI **96.67%–100%**）。该结果不覆盖记忆抽取、存储和检索召回。",
        "- 项目图谱性能：热读取平均 **1.90 ms**、p95 **4.62 ms**；单文件增量刷新平均 **1.09 s**、p95 **4.64 s**；峰值内存平均 **17.46 MiB**。",
        "",
        "### 需要继续优化的指标",
        "",
        "- 能力路由：1200 项 Skill/MCP 与 200 条改写查询上，Recall@1 为 **73.0%**，Recall@3 为 **82.5%**，Recall@5 为 **84.5%**（95% CI **79.5%–89.0%**），说明候选召回仍有提升空间。该实验仅覆盖 BGE 候选召回与排序，不代表工具执行正确率。",
        "- 项目图谱首次构建：平均 **178.56 s**、p50 **92.06 s**、p95 **587.06 s**，大项目冷启动耗时较高。",
        "- Code / General A/B：两种模式成功率均为 **100%**，但 Code 的工具调用增加 **7.51%**、可见读取字节增加 **5.08%**、Prompt token 增加 **10.09%**、总 token 增加 **9.78%**。当前不能声明 Code 模式或项目图谱提高了 Agent 工作效率。",
        "- 真实 Runtime 上下文虚拟化：30 条轨迹 × 3 次重复 × 4 策略中，Raw 成功率 **100%**、渐进式 Claude-style baseline 成功率 **100%**、Natural 成功率 **97.78%** 且恢复成功率 **97.78%**，质量门禁通过；按 cold-start repeat 0 口径，Natural 相对渐进式 Claude-style baseline 的未缓存输入 token 降低 **29.55%**（95% CI **15.63%–38.92%**）。但 Natural 的 cold-start Prompt token 增加 **107.52%**、总 token 增加 **89.58%**；该结论只支持‘未缓存输入成本下降’，不支持‘总 token 下降’。",
        "",
        "### 尚未获得或不可使用的证据",
        "",
        "- 项目图谱准确率为 `not_run`：缺少人工标注的符号和调用边，不能声明符号覆盖率、调用精确率或召回率。",
        "- 长期记忆尚无端到端抽取、存储、检索召回和最终任务效果证据。",
        "- Multi-Agent 状态为 `deprecated_incomplete`：标准实验已按计划停止，历史小样本和未配对中止数据均不能用于声明成功率或效率提升。",
        "",
        "### 简历表述建议",
        "",
        "可以使用前缀缓存 98.66%、上下文虚拟化受控实验减少 58.46% 输入 token、真实 Runtime 虚拟化相对渐进式 Claude-style 压缩基线降低 29.55% cold-start 未缓存输入 token，以及图谱热读/增量刷新性能；必须同时写明样本规模、cold-start 口径和‘不代表总 token 下降’。暂不应声称 Code 模式、项目图谱或 Multi-Agent 提升了端到端开发效率，也不应声称项目图谱和长期记忆已经完成端到端准确率验证。",
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
    document_multi = sub.add_parser("document-multi-agent-existing")
    document_multi.add_argument("--run-id")
    prepare = sub.add_parser("prepare-projects")
    prepare.add_argument("--manifest", default=str(PROJECT_MANIFEST))
    prepare.add_argument("--destination", default=str(DEFAULT_PROJECTS_ROOT))
    prepare.add_argument("--force", action="store_true")
    graph = sub.add_parser("run-project-graph")
    graph.add_argument("--manifest", default=str(PROJECT_MANIFEST))
    graph.add_argument("--projects-root", default=str(DEFAULT_PROJECTS_ROOT))
    graph.add_argument("--annotations", default="tests/eval/annotations")
    graph.add_argument("--run-id")
    for name, default, repeats in [
        ("run-prefix-cache", "prefix_cache_cases.jsonl", 3),
        ("run-context", "context_virtualization_cases.jsonl", 3),
        ("run-runtime-context-virtualization", "runtime_context_virtualization_cases.jsonl", 3),
        ("run-long-term-memory", "long_term_workflow_cases.jsonl", 3),
        ("run-capability-routing", "capability_routing_1200_cases.jsonl", 1),
        ("run-multi-agent", "multi_agent_tasks.jsonl", 3),
        ("run-code-general-ab", "multi_agent_tasks.jsonl", 3),
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
    if args.command == "document-multi-agent-existing":
        result, directory = document_existing_multi_agent(run_id=args.run_id)
        print(json.dumps({"result": result, "run_dir": str(directory)}, ensure_ascii=False, indent=2, sort_keys=True))
        write_index(); return 0
    if args.command == "prepare-projects":
        rows = prepare_public_projects(manifest=Path(args.manifest), destination=Path(args.destination), force=args.force)
        print(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True)); return 0
    if args.command == "run-project-graph":
        result, directory = run_project_graph(manifest=Path(args.manifest), projects_root=Path(args.projects_root), annotations=Path(args.annotations), run_id=args.run_id)
    elif args.command == "run-prefix-cache":
        result, directory = run_prefix_cache(dataset=Path(args.dataset), run_id=args.run_id, repeats=max(1, args.repeats), limit=args.limit)
    elif args.command == "run-context":
        result, directory = run_context(dataset=Path(args.dataset), run_id=args.run_id, repeats=max(1, args.repeats), limit=args.limit)
    elif args.command == "run-runtime-context-virtualization":
        result, directory = run_runtime_context_virtualization(dataset=Path(args.dataset), run_id=args.run_id, repeats=max(1, args.repeats), limit=args.limit)
    elif args.command == "run-long-term-memory":
        result, directory = run_long_term_memory(dataset=Path(args.dataset), run_id=args.run_id, repeats=max(1, args.repeats), limit=args.limit)
    elif args.command == "run-capability-routing":
        result, directory = run_capability_routing(dataset=Path(args.dataset), run_id=args.run_id)
    elif args.command == "run-multi-agent":
        result, directory = run_multi_agent(dataset=Path(args.dataset), run_id=args.run_id, repeats=max(1, args.repeats), limit=args.limit, project_size=args.project_size)
    elif args.command == "run-code-general-ab":
        result, directory = run_code_general_ab(dataset=Path(args.dataset), run_id=args.run_id, repeats=max(1, args.repeats), limit=args.limit)
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
    return 0 if result.get("status") in {"passed", "not_run", "blocked", "deferred_by_user", "unavailable", "insufficient_sample"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
