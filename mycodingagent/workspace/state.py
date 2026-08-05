from __future__ import annotations

from pathlib import Path


def workspace_metadata_dir(workspace_root: Path | str) -> Path:
    """Return the project-owned metadata directory inside the workspace."""
    return Path(workspace_root).expanduser().resolve(strict=False) / ".mycodingagent"


def workspace_state_dir(workspace_root: Path | str) -> Path:
    path = workspace_metadata_dir(workspace_root) / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_state_path(workspace_root: Path | str, filename: str) -> Path:
    return workspace_state_dir(workspace_root) / filename
