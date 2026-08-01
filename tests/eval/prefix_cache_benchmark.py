from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from tests.eval.metrics import bootstrap_mean_ci, cache_hit_rate, mean, percentile


def run_prefix_cache_benchmark(
    dataset_path: Path,
    *,
    model: str,
    base_url: str,
    api_key: str,
    tool_schemas: list[dict[str, Any]],
    repeats: int = 3,
    limit: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases = _read_jsonl(dataset_path)
    if limit is not None:
        cases = cases[:limit]
    return asyncio.run(_run(cases, model=model, base_url=base_url, api_key=api_key, tool_schemas=tool_schemas, repeats=repeats))


async def _run(
    cases: list[dict[str, Any]], *, model: str, base_url: str, api_key: str,
    tool_schemas: list[dict[str, Any]], repeats: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from openai import AsyncOpenAI
    import httpx

    if not api_key or not base_url or not model:
        reason = "missing API key, base URL, or model"
        return {"module": "prefix_cache", "status": "not_run", "reason": reason, "case_count": len(cases)}, []
    try:
        client = AsyncOpenAI(
            api_key=api_key, base_url=base_url,
            http_client=httpx.AsyncClient(trust_env=False),
        )
    except Exception as exc:
        return {
            "module": "prefix_cache", "status": "blocked",
            "reason": f"client initialization failed: {type(exc).__name__}: {exc}",
            "case_count": len(cases),
        }, []
    rows: list[dict[str, Any]] = []
    common_system = (
        "You are the fixed-prefix cache evaluation agent. Keep answers under ten words.\n"
        + "Stable runtime policy payload without project-graph message pinning. " * 400
    )
    try:
        for case in cases:
            messages = [
                {"role": "system", "content": common_system},
            ]
            for ordinal in range(repeats + 1):
                started = time.perf_counter()
                try:
                    response = await client.chat.completions.create(
                        model=model,
                        messages=[*messages, {"role": "user", "content": f"{case['prompt']} measurement={ordinal}"}],
                        tools=tool_schemas or None,
                        stream=False,
                        max_tokens=16,
                    )
                    usage = response.usage
                    payload = usage.model_dump(exclude_none=False) if hasattr(usage, "model_dump") else vars(usage or {})
                    cache = extract_cache_usage(payload)
                    rows.append({
                        "case_id": case["case_id"], "ordinal": ordinal,
                        "warmup": ordinal == 0,
                        "status": cache["status"],
                        "cache_fields_present": cache["status"] == "passed",
                        "prompt_cache_hit_tokens": cache["hit_tokens"],
                        "prompt_cache_miss_tokens": cache["miss_tokens"],
                        "cache_hit_rate": cache["hit_rate"],
                        "prompt_tokens": int(payload.get("prompt_tokens") or 0),
                        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    })
                except Exception as exc:
                    rows.append({
                        "case_id": case["case_id"], "ordinal": ordinal, "warmup": ordinal == 0,
                        "status": "failed", "error": f"{type(exc).__name__}: {exc}",
                        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    })
    finally:
        await client.close()
    measured = [row for row in rows if not row.get("warmup")]
    available = [row for row in measured if row.get("cache_hit_rate") is not None]
    if not measured:
        status, reason = "not_run", "no measured requests"
    elif len(available) != len(measured):
        status, reason = "unavailable", "provider omitted cache hit/miss fields for one or more measured requests"
    else:
        status, reason = "passed", ""
    rates = [row["cache_hit_rate"] for row in available]
    total_hit = sum(int(row["prompt_cache_hit_tokens"]) for row in available)
    total_miss = sum(int(row["prompt_cache_miss_tokens"]) for row in available)
    summary = {
        "module": "prefix_cache", "status": status, "reason": reason,
        "case_count": len(cases), "repeats": repeats, "warmup_excluded": True,
        "run_count": len(measured), "available_run_count": len(available),
        "token_weighted_hit_rate": cache_hit_rate(total_hit, total_miss) if available else None,
        "mean_session_hit_rate": mean(rates) if rates else None,
        "p50_session_hit_rate": percentile(rates, 0.5) if rates else None,
        "p95_session_hit_rate": percentile(rates, 0.95) if rates else None,
        "hit_rate_ci95": bootstrap_mean_ci(rates) if rates else None,
    }
    if status == "passed" and len(cases) >= 30 and repeats >= 3:
        summary["resume_conclusion"] = f"30 会话、每会话 {repeats} 次测量中，token 加权前缀缓存命中率为 {summary['token_weighted_hit_rate']:.1%}。"
    return summary, rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def extract_cache_usage(payload: dict[str, Any]) -> dict[str, Any]:
    hit_present = "prompt_cache_hit_tokens" in payload and payload.get("prompt_cache_hit_tokens") is not None
    miss_present = "prompt_cache_miss_tokens" in payload and payload.get("prompt_cache_miss_tokens") is not None
    if not (hit_present and miss_present):
        return {"status": "unavailable", "hit_tokens": None, "miss_tokens": None, "hit_rate": None}
    hit = int(payload.get("prompt_cache_hit_tokens") or 0)
    miss = int(payload.get("prompt_cache_miss_tokens") or 0)
    return {"status": "passed", "hit_tokens": hit, "miss_tokens": miss, "hit_rate": cache_hit_rate(hit, miss)}
