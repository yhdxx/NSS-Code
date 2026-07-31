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
