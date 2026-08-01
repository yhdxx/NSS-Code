from pathlib import Path

from mycodingagent.code_intelligence import ProjectGraphService, WorkspaceCodeIndex
from mycodingagent.code_intelligence.agentignore import AgentIgnore


def create_graph(tmp_path: Path) -> tuple[WorkspaceCodeIndex, ProjectGraphService]:
    state = tmp_path.parent / f"{tmp_path.name}-graph-state"
    state.mkdir()
    index = WorkspaceCodeIndex(tmp_path, state / "index.sqlite3")
    return index, ProjectGraphService(tmp_path, state / "graph.sqlite3", index)


def test_agentignore_supports_comments_globs_directories_and_negation(tmp_path):
    (tmp_path / ".agentignore").write_text(
        "# generated files\n"
        "build/\n"
        "*.log\n"
        "/cache/*.json\n"
        "!build/keep.py\n",
        encoding="utf-8",
    )

    matcher = AgentIgnore(tmp_path)

    assert matcher.is_ignored("build/output.py")
    assert matcher.is_ignored("nested/build/output.py")
    assert not matcher.is_ignored("build/keep.py")
    assert matcher.is_ignored("debug.log")
    assert matcher.is_ignored("nested/debug.log")
    assert matcher.is_ignored("cache/data.json")
    assert not matcher.is_ignored("nested/cache/data.json")


def test_agentignore_excludes_files_from_index_and_project_graph(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "generated").mkdir()
    (tmp_path / ".agentignore").write_text("generated/\n*.log\n", encoding="utf-8")
    (tmp_path / "src" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (tmp_path / "generated" / "hidden.py").write_text("def hidden(): pass\n", encoding="utf-8")
    (tmp_path / "debug.log").write_text("ignored", encoding="utf-8")
    index, graph = create_graph(tmp_path)

    architecture = graph.architecture("")
    root_units = graph.dependency_graph(architecture["module"]["id"])["units"]

    assert index.status()["indexed_files"] == 1
    assert "generated" not in {module["path"] for module in architecture["modules"]}
    assert "debug.log" not in {unit["path"] for unit in root_units}


def test_duplicate_qualified_symbols_receive_unique_unit_ids(tmp_path):
    (tmp_path / "model.py").write_text(
        "class Model:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return 1\n\n"
        "    @value.setter\n"
        "    def value(self, new):\n"
        "        pass\n",
        encoding="utf-8",
    )
    _index, graph = create_graph(tmp_path)

    units = graph.dependency_graph("project")["units"]
    value_units = [unit for unit in units if unit["name"] == "value"]

    assert len(value_units) == 2
    assert len({unit["id"] for unit in value_units}) == 2


def test_clean_graph_does_not_rebuild_after_initial_status(tmp_path):
    (tmp_path / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    _index, graph = create_graph(tmp_path)
    progress: list[str] = []
    graph.set_progress_callback(progress.append)

    graph.status()
    completed = list(progress)
    graph.architecture("")

    assert progress == completed
    assert any(message.startswith("项目图谱完成") for message in progress)
