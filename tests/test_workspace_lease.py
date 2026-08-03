from __future__ import annotations

import pytest

from mycodingagent.workspace.lease import WorkspaceLease, WorkspaceLeaseError


def test_workspace_lease_blocks_second_process_owner(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = WorkspaceLease(workspace, tmp_path / "state", heartbeat_seconds=0.01)
    second = WorkspaceLease(workspace, tmp_path / "state", heartbeat_seconds=0.01)
    first.acquire()
    try:
        with pytest.raises(WorkspaceLeaseError):
            second.acquire()
        assert first.owner_metadata()["workspace"] == str(workspace)
    finally:
        first.release()

    second.acquire()
    second.release()


def test_workspace_lease_atexit_cleanup_allows_reacquire(tmp_path, monkeypatch):
    callbacks = []

    def register(callback):
        callbacks.append(callback)

    def unregister(callback):
        callbacks.remove(callback)

    monkeypatch.setattr("mycodingagent.workspace.lease.atexit.register", register)
    monkeypatch.setattr("mycodingagent.workspace.lease.atexit.unregister", unregister)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = WorkspaceLease(workspace, tmp_path / "state", heartbeat_seconds=0.01)
    second = WorkspaceLease(workspace, tmp_path / "state", heartbeat_seconds=0.01)

    first.acquire()
    assert callbacks

    callbacks[0]()

    second.acquire()
    second.release()


def test_workspace_lease_reports_lock_storage_error(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lease = WorkspaceLease(workspace, tmp_path / "state")

    def fail_acquire():
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(lease._lock, "acquire", fail_acquire)

    with pytest.raises(WorkspaceLeaseError, match="state.*writable"):
        lease.acquire()


def test_workspace_lease_releases_lock_when_metadata_write_fails(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lease = WorkspaceLease(workspace, tmp_path / "state")

    def fail_metadata():
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(lease, "_write_metadata", fail_metadata)

    with pytest.raises(WorkspaceLeaseError, match="metadata"):
        lease.acquire()

    assert not lease._lock.is_locked
