from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mycodingagent.tool_runtime import base as base_module
from mycodingagent.tool_runtime.base import (
    OUT_OF_WORKSPACE_WRITE_MESSAGE,
    is_path_denied,
    is_path_readable,
    resolve_read_path,
    resolve_write_path,
)


@pytest.fixture
def patch_sandbox(monkeypatch):
    def _patch(*, access_mode="global_read", allowlist=(), denylist=(), root="/ws/proj"):
        sandbox = replace(
            base_module.CONFIG.sandbox,
            access_mode=access_mode,
            read_allowlist=tuple(allowlist),
            read_denylist=tuple(denylist),
            root=Path(root),
        )
        monkeypatch.setattr(base_module, "CONFIG", replace(base_module.CONFIG, sandbox=sandbox))
        return Path(root)

    return _patch


def test_workspace_only_read_denies_outside(patch_sandbox):
    root = patch_sandbox(access_mode="workspace_only")
    assert resolve_read_path("a.txt", root)[0] is not None
    path, error = resolve_read_path("/etc/hosts", root)
    assert path is None and "沙箱之外" in error


def test_workspace_only_write_denies_outside_with_message(patch_sandbox):
    root = patch_sandbox(access_mode="workspace_only")
    assert resolve_write_path("a.txt", root)[0] is not None
    path, error = resolve_write_path("/etc/hosts", root)
    assert path is None and error == OUT_OF_WORKSPACE_WRITE_MESSAGE


def test_global_read_allows_outside_read_denies_outside_write(patch_sandbox):
    root = patch_sandbox(access_mode="global_read")
    assert resolve_read_path("/etc/hosts", root)[0] is not None
    path, error = resolve_write_path("/etc/hosts", root)
    assert path is None and error == OUT_OF_WORKSPACE_WRITE_MESSAGE


def test_global_write_allows_outside_write(patch_sandbox):
    root = patch_sandbox(access_mode="global_write")
    assert resolve_write_path("/etc/hosts", root)[0] is not None


def test_allowlist_grants_read_only(patch_sandbox):
    root = patch_sandbox(access_mode="workspace_only", allowlist=("/outside",))
    assert resolve_read_path("/outside/f.txt", root)[0] is not None
    path, error = resolve_write_path("/outside/f.txt", root)
    assert path is None and error == OUT_OF_WORKSPACE_WRITE_MESSAGE


def test_denylist_blocks_read_and_write(patch_sandbox):
    root = patch_sandbox(access_mode="global_read", denylist=("/secret",))
    path, error = resolve_read_path("/secret/x.txt", root)
    assert path is None and "不可读" in error
    path, error = resolve_write_path("/secret/x.txt", root)
    assert path is None and error == OUT_OF_WORKSPACE_WRITE_MESSAGE


def test_workspace_always_allowed_even_when_denylist_covers_it(patch_sandbox):
    root = patch_sandbox(access_mode="global_read", denylist=("/ws",))
    assert resolve_read_path("a.txt", root)[0] is not None
    assert resolve_write_path("a.txt", root)[0] is not None


def test_isolated_root_stays_inside(patch_sandbox):
    root = patch_sandbox(access_mode="global_read", root="/ws/proj")
    worktree = Path("/ws/worktree")
    assert resolve_read_path("a.txt", worktree)[0] is not None
    path, error = resolve_read_path("/etc/hosts", worktree)
    assert path is None and "沙箱之外" in error
    path, error = resolve_write_path("/etc/hosts", worktree)
    assert path is None and error == OUT_OF_WORKSPACE_WRITE_MESSAGE


def test_is_path_readable_and_denied_for_traversal(patch_sandbox):
    root = patch_sandbox(access_mode="global_read", denylist=("/secret",))
    assert is_path_readable(Path("/etc/hosts"), root) is True
    assert is_path_readable(Path("/secret/x.txt"), root) is False
    assert is_path_denied(Path("/secret"), root) is True
    assert is_path_denied(root, root) is False
