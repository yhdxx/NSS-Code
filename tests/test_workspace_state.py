from pathlib import Path

from mycodingagent.workspace.state import workspace_metadata_dir, workspace_state_path


def test_workspace_state_is_nested_under_project(tmp_path):
    assert workspace_metadata_dir(tmp_path) == Path(tmp_path) / ".mycodingagent"
    state_path = workspace_state_path(tmp_path, "sessions.sqlite3")
    assert state_path == Path(tmp_path) / ".mycodingagent" / "state" / "sessions.sqlite3"
    assert state_path.parent.is_dir()
