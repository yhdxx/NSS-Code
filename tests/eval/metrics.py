from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Iterable


def mean(values: Iterable[float | int | bool]) -> float:
    items = [float(value) for value in values]
    return round(statistics.mean(items), 6) if items else 0.0


def percentile(values: Iterable[float | int], percentile_value: float) -> float:
    items = sorted(float(value) for value in values)
    if not items:
        return 0.0
    rank = max(0.0, min(1.0, percentile_value)) * (len(items) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return round(items[lower], 6)
    weight = rank - lower
    return round(items[lower] * (1 - weight) + items[upper] * weight, 6)


def bootstrap_mean_ci(
    values: Iterable[float | int | bool],
    *,
    confidence: float = 0.95,
    samples: int = 2_000,
    seed: int = 20260801,
) -> dict[str, float]:
    items = [float(value) for value in values]
    if not items:
        return {"mean": 0.0, "low": 0.0, "high": 0.0}
    if len(items) == 1:
        value = round(items[0], 6)
        return {"mean": value, "low": value, "high": value}
    rng = random.Random(seed)
    bootstrapped = [
        statistics.mean(rng.choice(items) for _ in items)
        for _ in range(max(100, samples))
    ]
    alpha = (1 - confidence) / 2
    return {
        "mean": mean(items),
        "low": percentile(bootstrapped, alpha),
        "high": percentile(bootstrapped, 1 - alpha),
    }


def cache_hit_rate(hit_tokens: int, miss_tokens: int) -> float | None:
    total = int(hit_tokens) + int(miss_tokens)
    if total <= 0:
        return None
    return round(int(hit_tokens) / total, 6)


def reduction_rate(baseline: float, candidate: float) -> float | None:
    if baseline <= 0:
        return None
    return round((baseline - candidate) / baseline, 6)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
