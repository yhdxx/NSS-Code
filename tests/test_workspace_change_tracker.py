from pathlib import Path

from mycodingagent.tool_runtime.file_state_cache import FileStateCache
from mycodingagent.tool_runtime.workspace_change_tracker import WorkspaceChangeTracker


def test_workspace_change_tracker_notifies_subscriber_for_unread_external_file(tmp_path):
    tracker = WorkspaceChangeTracker(tmp_path, FileStateCache())
    events: list[tuple[Path, bool]] = []
    tracker.subscribe(lambda path, deleted: events.append((path, deleted)))
    source = tmp_path / "new.py"
    source.write_text("value = 1\n", encoding="utf-8")

    tracker._record_change(source, False)

    assert events == [(source, False)]
    assert tracker.consume_external_changes() == ([], 0)


def test_workspace_change_tracker_notifies_subscriber_for_agent_write(tmp_path):
    tracker = WorkspaceChangeTracker(tmp_path, FileStateCache())
    events: list[tuple[Path, bool]] = []
    tracker.subscribe(lambda path, deleted: events.append((path, deleted)))
    source = tmp_path / "edited.py"
    source.write_text("value = 2\n", encoding="utf-8")

    tracker.mark_agent_write(str(source))

    assert events == [(source.resolve(), False)]
