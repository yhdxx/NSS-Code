from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PublicProject:
    project_id: str
    url: str
    commit: str
    language: str
    size: str
    license: str


def load_manifest(path: Path) -> list[PublicProject]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        PublicProject(
            project_id=item["id"],
            url=item["url"],
            commit=item["commit"],
            language=item["language"],
            size=item["size"],
            license=item["license"],
        )
        for item in payload["projects"]
    ]


def prepare_projects(manifest_path: Path, destination: Path, *, force: bool = False) -> list[dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    results = []
    for project in load_manifest(manifest_path):
        target = destination / project.project_id
        if target.exists() and force:
            shutil.rmtree(target)
        if not target.exists():
            _run(["git", "clone", "--filter=blob:none", "--no-checkout", project.url, str(target)])
        _run(["git", "fetch", "--depth=1", "origin", project.commit], cwd=target)
        _run(["git", "checkout", "--detach", project.commit], cwd=target)
        actual = _run(["git", "rev-parse", "HEAD"], cwd=target).stdout.strip()
        if actual != project.commit:
            raise RuntimeError(f"commit mismatch for {project.project_id}: {actual}")
        results.append({
            "project_id": project.project_id,
            "path": str(target),
            "commit": actual,
            "language": project.language,
            "size": project.size,
            "license": project.license,
        })
    return results


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stderr[-1000:]}")
    return result
