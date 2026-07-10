from __future__ import annotations

import hashlib
from pathlib import Path

from mycodingagent.multi_agent.infrastructure.permissions import normalize_workspace_path


IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".skill_runtime",
    "build",
    "dist",
}


def capture_workspace_state(root: Path) -> dict[str, str]:
    resolved_root = root.resolve()
    state: dict[str, str] = {}
    for path in resolved_root.rglob("*"):
        if not path.is_file() or any(part in IGNORED_DIRECTORIES for part in path.relative_to(resolved_root).parts):
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        state[path.relative_to(resolved_root).as_posix()] = digest
    return state


def changed_paths(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {
        path
        for path in before.keys() | after.keys()
        if before.get(path) != after.get(path)
    }


def outside_scopes(paths: set[str], scopes: tuple[str, ...], root: Path) -> set[str]:
    if not paths:
        return set()
    normalized_scopes = [normalize_workspace_path(scope, root) for scope in scopes]
    outside: set[str] = set()
    for path in paths:
        target = normalize_workspace_path(path, root)
        if not any(target == scope or scope in target.parents for scope in normalized_scopes):
            outside.add(path)
    return outside
