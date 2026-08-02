from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

from tests.eval.artifacts import write_jsonl
from tests.eval.metrics import (
    bootstrap_mean_ci,
    bootstrap_reduction_ci,
    mean,
    percentile,
    reduction_rate,
)


QUALITY_REFERENCE_STRATEGY = "raw"
COST_BASELINE_STRATEGY = "claude_compression_baseline"
VIRTUALIZED_STRATEGIES = ("forced_virtualized", "natural")
STRATEGIES = (QUALITY_REFERENCE_STRATEGY, COST_BASELINE_STRATEGY, *VIRTUALIZED_STRATEGIES)
RECOVERY_TOOLS = {"BatchRecoverContext", "SearchRecoverableContext", "SearchSessionHistory"}
CLAUDE_BASELINE_RECENT_MESSAGE_COUNT = 20


def run_runtime_context_virtualization_benchmark(
    dataset: Path,
    *,
    model: str,
    base_url: str,
    api_key: str,
    repeats: int,
    limit: int | None,
    run_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases = _read_jsonl(dataset)
    if limit:
        cases = cases[:limit]
    if not api_key or not base_url or not model:
        return {
            "module": "runtime_context_virtualization",
            "status": "not_run",
            "reason": "missing API key, base URL, or model",
            "case_count": len(cases),
        }, []
    details = asyncio.run(
        _run_cases(
            cases,
            model=model,
            base_url=base_url,
            api_key=api_key,
            repeats=repeats,
            checkpoint=run_dir / "details.in_progress.jsonl",
            benchmark_salt=run_dir.parent.name,
        )
    )
    return _summary(cases, details, repeats), details


async def _run_cases(
    cases: list[dict[str, Any]],
    *,
    model: str,
    base_url: str,
    api_key: str,
    repeats: int,
    checkpoint: Path,
    benchmark_salt: str,
) -> list[dict[str, Any]]:
    details = _read_jsonl(checkpoint) if checkpoint.exists() else []
    completed = {(row.get("case_id"), row.get("strategy"), row.get("repeat")) for row in details}
    for repeat in range(repeats):
        for ordinal, case in enumerate(cases, start=1):
            for strategy in STRATEGIES:
                key = (case["case_id"], strategy, repeat)
                if key in completed:
                    continue
                row = await _run_one_case(
                    case,
                    strategy=strategy,
                    repeat=repeat,
                    ordinal=ordinal,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    benchmark_salt=benchmark_salt,
                )
                details.append(row)
                write_jsonl(checkpoint, details)
    return details


async def _run_one_case(
    case: dict[str, Any],
    *,
    strategy: str,
    repeat: int,
    ordinal: int,
    model: str,
    base_url: str,
    api_key: str,
    benchmark_salt: str,
) -> dict[str, Any]:
    import httpx
    from openai import AsyncOpenAI

    from mycodingagent.configuration import CONFIG
    from mycodingagent.llm_runtime import client as agent_client
    from mycodingagent.llm_runtime.system_prompt import PromptFeatures, build_system_prompt
    from mycodingagent.memory import ContextCompressor, MemoryRuntime, SQLiteMemoryStore
    from mycodingagent.tool_runtime import create_default_registry

    started = time.perf_counter()
    context_window = _context_window_for_strategy(strategy)
    with tempfile.TemporaryDirectory(prefix=f"mca_runtime_ctx_{strategy}_{ordinal:02d}_") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        state = root / "state"
        workspace.mkdir()
        state.mkdir()
        db_path = state / "sessions.sqlite3"
        memory = MemoryRuntime(
            store=SQLiteMemoryStore(db_path),
            compressor=ContextCompressor(context_window=context_window),
            model=model,
            workspace_root=str(workspace),
        )
        memory.set_work_mode("general")
        session_id = memory.start_session(model)
        if strategy == COST_BASELINE_STRATEGY:
            messages = _build_claude_compression_baseline_messages(case, benchmark_salt=benchmark_salt)
        else:
            messages = _build_seed_messages(memory, session_id, case, benchmark_salt=benchmark_salt)
        memory.save_messages_now(session_id, messages)
        await memory.drain()
        if strategy == "forced_virtualized":
            memory.force_context_virtualized(session_id)
        registry = create_default_registry(memory_runtime=memory)
        tools = agent_client.format_openai_tools(registry.get_all_schemas("openai"))
        api_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=httpx.AsyncClient(trust_env=False),
        )
        try:
            prompt = (
                case["final_query"]
                + "\nUse visible evidence directly when it is complete. "
                + "If the evidence is virtualized or hidden behind a context_id, recover it first."
                + f"\nBenchmark run salt: {benchmark_salt}."
            )
            text, output_messages = await agent_client.ask_deepseek(
                api_client,
                prompt,
                registry,
                tools,
                messages=messages,
                memory_runtime=memory,
                core_tool_schemas=registry.get_all_schemas("openai"),
                work_mode="general",
            )
            await memory.drain()
            token_records = _token_usage_records(db_path, session_id)
            tool_calls = _tool_calls(output_messages)
            tool_names = [row["name"] for row in tool_calls]
            recovery_call_count = sum(name in RECOVERY_TOOLS for name in tool_names)
            final_mode = _context_mode_value(memory.context_mode(session_id))
            recovery_required = (
                bool(case.get("requires_recoverable_tool_output"))
                and final_mode == "virtualized"
            )
            passed = _contains(text, case["expected_answer_contains"])
            row = {
                "case_id": case["case_id"],
                "category": case.get("category"),
                "strategy": strategy,
                "repeat": repeat,
                "status": "passed",
                "passed": passed,
                "duration_seconds": round(time.perf_counter() - started, 3),
                "context_window": context_window,
                "final_context_mode": final_mode,
                "recovery_required": recovery_required,
                "recovery_call_count": recovery_call_count,
                "recovery_success": bool(recovery_required and recovery_call_count > 0 and passed),
                "false_recovery": bool(not recovery_required and recovery_call_count > 0),
                "batch_recover_calls": sum(name == "BatchRecoverContext" for name in tool_names),
                "search_recoverable_calls": sum(name == "SearchRecoverableContext" for name in tool_names),
                "search_session_calls": sum(name == "SearchSessionHistory" for name in tool_names),
                "tool_call_count": len(tool_calls),
                "tool_names": tool_names,
                "invalid_tool_calls": _tool_error_count(output_messages),
                "prompt_tokens": sum(int(row.get("prompt_tokens") or 0) for row in token_records),
                "completion_tokens": sum(int(row.get("completion_tokens") or 0) for row in token_records),
                "total_tokens": sum(int(row.get("total_tokens") or 0) for row in token_records),
                "prompt_cache_hit_tokens": sum(int(row.get("prompt_cache_hit_tokens") or 0) for row in token_records),
                "prompt_cache_miss_tokens": sum(int(row.get("prompt_cache_miss_tokens") or 0) for row in token_records),
                "cache_hit_rate": _cache_hit_rate(token_records),
                "request_count": len(token_records),
                "prompt_hash_change_count": _change_count(row.get("prompt_hash") for row in token_records),
                "tools_hash_change_count": _change_count(row.get("tools_hash") for row in token_records),
                "runtime_context_hash_change_count": _change_count(
                    (row.get("metadata") or {}).get("runtime_context_hash") for row in token_records
                ),
                "rendered_prompt_hash_change_count": _change_count(
                    (row.get("metadata") or {}).get("rendered_prompt_hash") for row in token_records
                ),
                "token_records": token_records,
                "context_store": _context_store_counts(db_path, session_id),
                "answer": text[-1000:],
            }
        except Exception as exc:
            row = {
                "case_id": case["case_id"],
                "category": case.get("category"),
                "strategy": strategy,
                "repeat": repeat,
                "status": "failed",
                "passed": False,
                "duration_seconds": round(time.perf_counter() - started, 3),
                "context_window": context_window,
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            await memory.close()
            await api_client.close()
    return row


def _build_seed_messages(
    memory: Any,
    session_id: str,
    case: dict[str, Any],
    *,
    benchmark_salt: str,
) -> list[dict[str, Any]]:
    from mycodingagent.llm_runtime.system_prompt import PromptFeatures, build_system_prompt

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": build_system_prompt(
                PromptFeatures(
                    skills_enabled=False,
                    mcp_enabled=False,
                    memory_enabled=True,
                    project_graph_enabled=True,
                )
            ),
        },
        {"role": "user", "content": case["initial_user"] + f" Benchmark run salt: {benchmark_salt}."},
    ]
    tool_call_id = f"eval_probe_{case['case_id']}"
    arguments = json.dumps(case["tool_arguments"], ensure_ascii=False, sort_keys=True)
    output_id = memory.save_tool_output(
        session_id=session_id,
        tool_call_id=tool_call_id,
        tool_name=case["tool_name"],
        arguments=arguments,
        output=case["tool_output"],
        metadata={"intent": "load hidden virtualization benchmark evidence"},
    )
    messages.extend(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {"name": case["tool_name"], "arguments": arguments},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": case["tool_output"],
                "metadata": {
                    "output_id": output_id,
                    "context_id": output_id,
                    "tool_name": case["tool_name"],
                    "intent": "load hidden virtualization benchmark evidence",
                },
            },
            {"role": "assistant", "content": "Recorded the hidden evidence without repeating its values."},
        ]
    )
    for turn in range(1, int(case["filler_turn_count"]) + 1):
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Interleaved request {turn}: acknowledge topic "
                    f"{case['category']} without using the hidden evidence."
                ),
            }
        )
        if turn in set(case.get("large_noise_turns") or []):
            noise_call_id = f"eval_noise_{case['case_id']}_{turn}"
            noise_args = json.dumps(
                {
                    "path": f"/workspace/logs/{case['noise_unit']}_{turn}.txt",
                    "intent": "load irrelevant benchmark noise",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            noise_output = _noise_blob(str(case["noise_unit"]), turn)
            noise_output_id = memory.save_tool_output(
                session_id=session_id,
                tool_call_id=noise_call_id,
                tool_name="ReadFile",
                arguments=noise_args,
                output=noise_output,
                metadata={"intent": "load irrelevant benchmark noise"},
            )
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": noise_call_id,
                                "type": "function",
                                "function": {"name": "ReadFile", "arguments": noise_args},
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": noise_call_id,
                        "content": noise_output,
                        "metadata": {
                            "output_id": noise_output_id,
                            "context_id": noise_output_id,
                            "tool_name": "ReadFile",
                            "intent": "load irrelevant benchmark noise",
                        },
                    },
                    {"role": "assistant", "content": f"Acknowledged interleaved request {turn}."},
                ]
            )
        else:
            messages.append({"role": "assistant", "content": f"Acknowledged interleaved request {turn}."})
    return messages


def _build_claude_compression_baseline_messages(
    case: dict[str, Any],
    *,
    benchmark_salt: str,
) -> list[dict[str, Any]]:
    from mycodingagent.llm_runtime.system_prompt import PromptFeatures, build_system_prompt

    recent_messages: list[dict[str, Any]] = []
    for turn in range(1, int(case["filler_turn_count"]) + 1):
        recent_messages.extend(
            [
                {
                    "role": "user",
                    "content": (
                        f"Interleaved request {turn}: acknowledge topic "
                        f"{case['category']} without using the hidden evidence."
                    ),
                },
                {"role": "assistant", "content": f"Acknowledged interleaved request {turn}."},
            ]
        )
    return [
        {
            "role": "system",
            "content": build_system_prompt(
                PromptFeatures(
                    skills_enabled=False,
                    mcp_enabled=False,
                    memory_enabled=True,
                    project_graph_enabled=True,
                )
            ),
        },
        {
            "role": "system",
            "content": _claude_compression_summary(case, benchmark_salt=benchmark_salt),
        },
        *recent_messages[-CLAUDE_BASELINE_RECENT_MESSAGE_COUNT:],
    ]


def _claude_compression_summary(case: dict[str, Any], *, benchmark_salt: str) -> str:
    critical_line = _first_nonempty_line(str(case.get("tool_output") or ""))
    return "\n".join(
        [
            "Claude-style compressed conversation state baseline.",
            "This baseline approximates a reverse-engineered Claude 4.6 compression strategy: "
            "preserve a concise session summary plus a recent-message window, without recoverable cold-context tools.",
            f"Benchmark run salt: {benchmark_salt}.",
            f"Earlier user request: {case['initial_user']}",
            f"Compressed hidden evidence summary: {critical_line}",
            "If the final user asks about the earlier hidden evidence, answer from this compressed summary.",
        ]
    )


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "暂未描述"


def _noise_blob(unit: str, turn: int) -> str:
    return "\n".join(
        f"{unit}_{turn}_{line:03d}: unrelated log payload for context pressure."
        for line in range(45)
    )


def _context_window_for_strategy(strategy: str) -> int:
    if strategy in {"raw", COST_BASELINE_STRATEGY}:
        return 1_000_000
    if strategy == "forced_virtualized":
        return 24_000
    if strategy == "natural":
        return 9_000
    raise ValueError(f"unknown strategy: {strategy}")


def _summary(cases: list[dict[str, Any]], rows: list[dict[str, Any]], repeats: int) -> dict[str, Any]:
    by_strategy = {strategy: _strategy_summary(rows, strategy) for strategy in STRATEGIES}
    raw_reference_delta = {
        strategy: _paired_reductions(rows, candidate=strategy)
        for strategy in (COST_BASELINE_STRATEGY, *VIRTUALIZED_STRATEGIES)
    }
    cost_baseline_reduction = {
        strategy: _paired_reductions(rows, baseline=COST_BASELINE_STRATEGY, candidate=strategy)
        for strategy in VIRTUALIZED_STRATEGIES
    }
    sufficient = len(cases) >= 30 and repeats >= 3 and len(rows) == len(cases) * repeats * len(STRATEGIES)
    api_completed = all(row.get("status") == "passed" for row in rows)
    raw_success = float(by_strategy["raw"].get("success_rate") or 0.0)
    claude_success = float(by_strategy[COST_BASELINE_STRATEGY].get("success_rate") or 0.0)
    forced_success = float(by_strategy["forced_virtualized"].get("success_rate") or 0.0)
    natural_success = float(by_strategy["natural"].get("success_rate") or 0.0)
    forced_uncached_reduction = cost_baseline_reduction["forced_virtualized"]["uncached_prompt_tokens"].get("mean")
    natural_uncached_reduction = cost_baseline_reduction["natural"]["uncached_prompt_tokens"].get("mean")
    quality_gate = forced_success >= raw_success - 0.05 and natural_success >= raw_success - 0.05
    claude_baseline_quality_gate = claude_success >= raw_success - 0.05
    cost_gate = (forced_uncached_reduction or 0) > 0 and (natural_uncached_reduction or 0) > 0
    status = "passed" if sufficient and api_completed else ("insufficient_sample" if rows else "not_run")
    summary = {
        "module": "runtime_context_virtualization",
        "status": status,
        "case_count": len(cases),
        "run_count": len(rows),
        "completed_run_count": sum(row.get("status") == "passed" for row in rows),
        "repeats": repeats,
        "strategies": list(STRATEGIES),
        "quality_reference_strategy": QUALITY_REFERENCE_STRATEGY,
        "cost_baseline_strategy": COST_BASELINE_STRATEGY,
        "by_strategy": by_strategy,
        "paired_delta_vs_raw_quality_reference": raw_reference_delta,
        "paired_reduction_vs_claude_compression_baseline": cost_baseline_reduction,
        "quality_gate_passed": bool(sufficient and api_completed and quality_gate),
        "claude_baseline_quality_gate_passed": bool(sufficient and api_completed and claude_baseline_quality_gate),
        "uncached_reduction_gate_passed": bool(sufficient and api_completed and cost_gate),
        "efficiency_claim_gate_passed": bool(
            sufficient and api_completed and quality_gate and claude_baseline_quality_gate and cost_gate
        ),
        "reason": "" if sufficient and api_completed else "requires 30 cases, 3 repeats, 4 strategies, and no failed API calls",
    }
    if sufficient and api_completed:
        if quality_gate and claude_baseline_quality_gate and cost_gate:
            summary["resume_conclusion"] = (
                "真实 Runtime 虚拟化在 30 条长会话轨迹、四策略、每策略 3 次中基本保持答案质量，"
                "且相对 Claude-style 压缩基线降低了未缓存输入成本。"
            )
        elif quality_gate and claude_baseline_quality_gate:
            summary["resume_conclusion"] = (
                "真实 Runtime 虚拟化在 30 条长会话轨迹、四策略、每策略 3 次中基本保持答案质量，"
                "但相对 Claude-style 压缩基线的未缓存输入成本未下降；不可表述为相对 Claude 压缩策略降本。"
            )
        elif quality_gate:
            summary["resume_conclusion"] = (
                "真实 Runtime 虚拟化基本保持答案质量，但 Claude-style 压缩基线未通过质量门禁，"
                "本轮不能判断相对 Claude 压缩策略的成本收益。"
            )
        else:
            summary["resume_conclusion"] = (
                "真实 Runtime 虚拟化未通过质量门禁；不可作为效果提升或端到端降本证据。"
            )
    return summary


def _strategy_summary(rows: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
    selected = [row for row in rows if row.get("strategy") == strategy]
    successful_api = [row for row in selected if row.get("status") == "passed"]
    required = [row for row in successful_api if row.get("recovery_required")]
    not_required = [row for row in successful_api if not row.get("recovery_required")]
    prompt = [row.get("prompt_tokens", 0) for row in successful_api]
    uncached = [row.get("prompt_cache_miss_tokens", 0) for row in successful_api]
    total = [row.get("total_tokens", 0) for row in successful_api]
    duration = [row.get("duration_seconds", 0) for row in successful_api]
    hit_tokens = sum(int(row.get("prompt_cache_hit_tokens") or 0) for row in successful_api)
    miss_tokens = sum(int(row.get("prompt_cache_miss_tokens") or 0) for row in successful_api)
    return {
        "run_count": len(selected),
        "api_completed_count": len(successful_api),
        "success_rate": mean(bool(row.get("passed")) for row in successful_api) if successful_api else None,
        "success_rate_ci95": bootstrap_mean_ci(bool(row.get("passed")) for row in successful_api) if successful_api else None,
        "final_virtualized_rate": mean(row.get("final_context_mode") == "virtualized" for row in successful_api) if successful_api else None,
        "recovery_call_rate": mean((row.get("recovery_call_count") or 0) > 0 for row in successful_api) if successful_api else None,
        "recovery_success_rate": mean(bool(row.get("recovery_success")) for row in required) if required else None,
        "false_recovery_rate": mean(bool(row.get("false_recovery")) for row in not_required) if not_required else None,
        "prompt_tokens_mean": mean(prompt) if prompt else None,
        "prompt_tokens_p50": percentile(prompt, .5) if prompt else None,
        "prompt_tokens_p95": percentile(prompt, .95) if prompt else None,
        "uncached_prompt_tokens_mean": mean(uncached) if uncached else None,
        "uncached_prompt_tokens_p50": percentile(uncached, .5) if uncached else None,
        "uncached_prompt_tokens_p95": percentile(uncached, .95) if uncached else None,
        "total_tokens_mean": mean(total) if total else None,
        "duration_mean_seconds": mean(duration) if duration else None,
        "duration_p95_seconds": percentile(duration, .95) if duration else None,
        "cache_hit_rate_token_weighted": _cache_hit_rate_from_counts(hit_tokens, miss_tokens),
        "request_count_mean": mean(row.get("request_count", 0) for row in successful_api) if successful_api else None,
        "tool_calls_mean": mean(row.get("tool_call_count", 0) for row in successful_api) if successful_api else None,
        "invalid_tool_calls_mean": mean(row.get("invalid_tool_calls", 0) for row in successful_api) if successful_api else None,
    }


def _paired_reductions(
    rows: list[dict[str, Any]],
    *,
    candidate: str,
    baseline: str = QUALITY_REFERENCE_STRATEGY,
) -> dict[str, Any]:
    by_strategy = {
        strategy: {
            (row.get("case_id"), row.get("repeat")): row
            for row in rows
            if row.get("strategy") == strategy and row.get("status") == "passed"
        }
        for strategy in (baseline, candidate)
    }
    keys = sorted(set(by_strategy[baseline]) & set(by_strategy[candidate]), key=str)
    fields = {
        "prompt_tokens": "prompt_tokens",
        "uncached_prompt_tokens": "prompt_cache_miss_tokens",
        "total_tokens": "total_tokens",
        "duration_seconds": "duration_seconds",
        "tool_calls": "tool_call_count",
    }
    return {
        name: bootstrap_reduction_ci(
            [by_strategy[baseline][key].get(field, 0) for key in keys],
            [by_strategy[candidate][key].get(field, 0) for key in keys],
        )
        for name, field in fields.items()
    } | {"paired_run_count": len(keys)}


def _token_usage_records(db_path: Path, session_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT request_index, prompt_tokens, prompt_cache_hit_tokens, prompt_cache_miss_tokens,
                   completion_tokens, total_tokens, model, prompt_hash, tools_hash, metadata_json
            FROM session_token_usage
            WHERE session_id = ?
            ORDER BY request_index
            """,
            (session_id,),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        metadata_raw = payload.pop("metadata_json", "{}")
        try:
            payload["metadata"] = json.loads(metadata_raw or "{}")
        except json.JSONDecodeError:
            payload["metadata"] = {"parse_error": True}
        result.append(payload)
    return result


def _context_store_counts(db_path: Path, session_id: str) -> dict[str, int]:
    tables = {
        "recoverable_contexts": "recoverable_contexts",
        "context_snapshots": "session_context_snapshots",
        "context_epochs": "context_epochs",
        "historical_turns": "historical_turns",
    }
    with sqlite3.connect(db_path) as conn:
        return {
            name: int(
                conn.execute(f"SELECT COUNT(*) FROM {table} WHERE session_id = ?", (session_id,)).fetchone()[0]
            )
            for name, table in tables.items()
        }


def _tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for message in messages:
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            rows.append(
                {
                    "id": str(call.get("id") or ""),
                    "name": str(function.get("name") or ""),
                    "arguments": str(function.get("arguments") or ""),
                }
            )
    return rows


def _tool_error_count(messages: list[dict[str, Any]]) -> int:
    count = 0
    for message in messages:
        if message.get("role") != "tool":
            continue
        content = str(message.get("content") or "")
        if bool((message.get("metadata") or {}).get("is_error")) or content.startswith(("错误", "Tool execution error", "Error:")):
            count += 1
    return count


def _contains(answer: str, expected: list[str]) -> bool:
    return all(item in answer for item in expected)


def _cache_hit_rate(records: list[dict[str, Any]]) -> float | None:
    return _cache_hit_rate_from_counts(
        sum(int(row.get("prompt_cache_hit_tokens") or 0) for row in records),
        sum(int(row.get("prompt_cache_miss_tokens") or 0) for row in records),
    )


def _cache_hit_rate_from_counts(hit_tokens: int, miss_tokens: int) -> float | None:
    total = hit_tokens + miss_tokens
    if total <= 0:
        return None
    return round(hit_tokens / total, 6)


def _change_count(values: Any) -> int:
    items = [item for item in values if item]
    if not items:
        return 0
    return sum(left != right for left, right in zip(items, items[1:]))


def _context_mode_value(mode: Any) -> str:
    return str(getattr(mode, "value", mode))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
