from __future__ import annotations

import asyncio
import subprocess

from mycodingagent.multi_agent.worktree import WorktreeManager


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_worktree_delivers_tracked_and_new_files(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "test@example.com")
    _git(repository, "config", "user.name", "Test")
    (repository / "tracked.txt").write_text("before\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-m", "initial")
    manager = WorktreeManager(repository, tmp_path / "state")

    handle = asyncio.run(manager.create())
    (handle.path / "tracked.txt").write_text("after\n", encoding="utf-8")
    (handle.path / "new.txt").write_text("new\n", encoding="utf-8")
    delivery = asyncio.run(manager.deliver(handle))

    assert delivery.delivered is True
    assert delivery.changed is True
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "after\n"
    assert (repository / "new.txt").read_text(encoding="utf-8") == "new\n"
    assert not handle.path.exists()


def test_worktree_requires_clean_source(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "test@example.com")
    _git(repository, "config", "user.name", "Test")
    (repository / "tracked.txt").write_text("before\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-m", "initial")
    (repository / "tracked.txt").write_text("dirty\n", encoding="utf-8")

    try:
        asyncio.run(WorktreeManager(repository, tmp_path / "state").create())
    except ValueError as exc:
        assert "clean" in str(exc)
    else:
        raise AssertionError("dirty workspace should be rejected")
