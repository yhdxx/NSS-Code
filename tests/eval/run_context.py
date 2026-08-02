from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tests.eval.metrics import sha256_file, stable_json_hash


DEFAULT_SEED = 20260801


@dataclass(frozen=True)
class EvalRunMetadata:
    run_id: str
    generated_at: str
    git_commit: str
    git_dirty: bool
    model: str
    base_url: str
    python: str
    platform: str
    random_seed: int = DEFAULT_SEED
    repeats: int = 3
    tool_schema_hash: str = ""
    dataset_path: str = ""
    dataset_sha256: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_run_metadata(
    *,
    run_id: str,
    model: str = "",
    base_url: str = "",
    repeats: int = 3,
    tool_schemas: Any = None,
    dataset_path: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> EvalRunMetadata:
    commit = _git_output(["rev-parse", "HEAD"])
    dirty = bool(_git_output(["status", "--porcelain"]))
    return EvalRunMetadata(
        run_id=run_id,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        git_commit=commit,
        git_dirty=dirty,
        model=model or "",
        base_url=base_url or "",
        python=platform.python_version(),
        platform=platform.platform(),
        repeats=max(1, repeats),
        tool_schema_hash=stable_json_hash(tool_schemas) if tool_schemas is not None else "",
        dataset_path=str(dataset_path or ""),
        dataset_sha256=sha256_file(dataset_path) if dataset_path and dataset_path.exists() else "",
        extra=extra or {},
    )


def write_run_metadata(run_dir: Path, metadata: EvalRunMetadata) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "run_metadata.json"
    path.write_text(json.dumps(metadata.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def _git_output(args: list[str]) -> str:
    try:
        return subprocess.run(
            ["git", *args], check=False, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
