from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def workspace_root_text(root: Path | str) -> str:
    return str(Path(root).expanduser().resolve(strict=False))


def workspace_label(root: Path | str) -> str:
    path = Path(root).expanduser().resolve(strict=False)
    return path.name or str(path)


def workspace_fingerprint(root: Path | str) -> str:
    path = Path(root).expanduser().resolve(strict=False)
    git_fingerprint = _git_fingerprint(path)
    if git_fingerprint:
        return git_fingerprint
    markers: list[str] = []
    for name in ("pyproject.toml", "package.json", "requirements.txt", ".gitignore"):
        marker = path / name
        if marker.exists() and marker.is_file():
            try:
                markers.append(f"{name}:{hashlib.sha256(marker.read_bytes()).hexdigest()}")
            except OSError:
                markers.append(name)
    raw = "\n".join(markers) if markers else str(path)
    return "dir:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _git_fingerprint(path: Path) -> str:
    try:
        root = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
    except Exception:
        return ""
    try:
        remote = subprocess.check_output(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
    except Exception:
        remote = ""
    raw = f"git:{root}:{remote}"
    return "git:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
