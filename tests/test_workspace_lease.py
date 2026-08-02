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
