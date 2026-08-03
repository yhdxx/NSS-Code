import asyncio
from pathlib import Path
from threading import Event

from mycodingagent.code_intelligence import ProjectGraphRuntime, ProjectGraphService, WorkspaceCodeIndex
from mycodingagent.code_intelligence.agentignore import AgentIgnore
from mycodingagent.work_mode import WorkMode, WorkModeManager


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
    (tmp_path / "README.md").write_text("# docs\n", encoding="utf-8")
    index, graph = create_graph(tmp_path)
    graph.refresh()

    architecture = graph.architecture("")
    root_units = graph.dependency_graph(architecture["module"]["id"])["units"]

    assert index.status()["indexed_files"] == 1
    assert "generated" not in {module["path"] for module in architecture["modules"]}
    assert "README.md" not in {module["path"] for module in architecture["modules"]}
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
    graph.refresh()

    units = graph.dependency_graph("project")["units"]
    value_units = [unit for unit in units if unit["name"] == "value"]

    assert len(value_units) == 2
    assert len({unit["id"] for unit in value_units}) == 2


def test_clean_graph_does_not_rebuild_after_initial_status(tmp_path):
    (tmp_path / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    _index, graph = create_graph(tmp_path)
    progress: list[str] = []

    graph.refresh(progress.append)
    completed = list(progress)
    graph.architecture("")

    assert progress == completed
    assert any(message.startswith("项目图谱完成") for message in progress)


def test_bootstrap_is_depth_limited_and_hash_ignores_description(tmp_path):
    (tmp_path / "src" / "pkg" / "deep").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "deep" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    _index, graph = create_graph(tmp_path)
    graph.refresh()

    bootstrap = graph.architecture("", depth=3, bootstrap=True)
    paths = {module["path"] for module in bootstrap["modules"]}
    before_hash = bootstrap["navigation_hash"]
    src_module = next(module for module in bootstrap["modules"] if module["path"] == "src")

    graph.update_description(src_module["id"], "source root", src_module["content_hash"])
    after_hash = graph.architecture("", depth=3, bootstrap=True)["navigation_hash"]

    assert {"src", "src/pkg"}.issubset(paths)
    assert "src/pkg/deep" not in paths
    assert before_hash == after_hash


def test_update_descriptions_batches_multiple_targets(tmp_path):
    (tmp_path / "a.py").write_text("def a(): pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def b(): pass\n", encoding="utf-8")
    _index, graph = create_graph(tmp_path)
    graph.refresh()
    units = graph.dependency_graph("project")["units"]

    result = graph.update_descriptions(
        [
            {"target": units[0]["id"], "description": "first unit", "content_hash": units[0]["content_hash"]},
            {"target": units[1]["id"], "description": "second unit", "content_hash": units[1]["content_hash"]},
        ]
    )

    refreshed = {unit["id"]: unit for unit in graph.dependency_graph("project")["units"]}
    assert result["status"] == "updated"
    assert result["updated"] == 2
    assert refreshed[units[0]["id"]]["description"] == "first unit"
    assert refreshed[units[1]["id"]]["description"] == "second unit"


def test_general_mode_marks_dirty_without_graph_io_or_background_refresh(tmp_path):
    (tmp_path / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    index, graph = create_graph(tmp_path)
    manager = WorkModeManager(WorkMode.GENERAL)

    async def exercise() -> None:
        runtime = ProjectGraphRuntime(graph, index, manager, debounce_seconds=0.01)
        runtime.mark_dirty(tmp_path / "main.py")
        await asyncio.sleep(0.03)
        assert runtime.dirty
        assert runtime._background_task is None
        await runtime.close()

    asyncio.run(exercise())

    assert not graph.db_path.exists()
    assert not index.db_path.exists()


def test_code_mode_background_refresh_is_debounced_and_silent(tmp_path, monkeypatch, capsys):
    source = tmp_path / "main.py"
    source.write_text("def main(): pass\n", encoding="utf-8")
    index, graph = create_graph(tmp_path)
    manager = WorkModeManager(WorkMode.GENERAL)
    refresh_calls = 0
    original_refresh = graph.refresh

    def counting_refresh(progress=None):
        nonlocal refresh_calls
        refresh_calls += 1
        return original_refresh(progress)

    monkeypatch.setattr(graph, "refresh", counting_refresh)

    async def exercise() -> None:
        runtime = ProjectGraphRuntime(graph, index, manager, debounce_seconds=0.01)
        progress: list[str] = []
        await runtime.activate(progress.append)
        assert manager.current is WorkMode.CODE
        capsys.readouterr()
        source.write_text("def main():\n    return 1\n", encoding="utf-8")
        runtime.mark_dirty(source)
        runtime.mark_dirty(source)
        await asyncio.sleep(0.1)
        assert not runtime.dirty
        assert capsys.readouterr().out == ""
        await runtime.close()
        assert any(message.startswith("项目图谱完成") for message in progress)

    asyncio.run(exercise())

    assert refresh_calls == 2


def test_change_during_background_refresh_is_processed_without_parallel_refresh(tmp_path, monkeypatch):
    source = tmp_path / "main.py"
    source.write_text("def main(): pass\n", encoding="utf-8")
    index, graph = create_graph(tmp_path)
    manager = WorkModeManager(WorkMode.GENERAL)

    async def exercise() -> None:
        runtime = ProjectGraphRuntime(graph, index, manager, debounce_seconds=0)
        await runtime.activate()
        original_refresh = graph.refresh
        started = Event()
        release = Event()
        active = 0
        max_active = 0
        calls = 0

        def blocking_refresh(progress=None):
            nonlocal active, max_active, calls
            calls += 1
            active += 1
            max_active = max(max_active, active)
            if calls == 1:
                started.set()
                release.wait(timeout=2)
            try:
                return original_refresh(progress)
            finally:
                active -= 1

        monkeypatch.setattr(graph, "refresh", blocking_refresh)
        runtime.mark_dirty(source)
        assert await asyncio.to_thread(started.wait, 2)
        source.write_text("def main():\n    return 2\n", encoding="utf-8")
        runtime.mark_dirty(source)
        release.set()
        await runtime.ensure_fresh()

        assert calls == 2
        assert max_active == 1
        assert not runtime.dirty
        await runtime.close()

    asyncio.run(exercise())


def test_deactivation_does_not_start_another_refresh_for_new_changes(tmp_path, monkeypatch):
    source = tmp_path / "main.py"
    source.write_text("def main(): pass\n", encoding="utf-8")
    index, graph = create_graph(tmp_path)
    manager = WorkModeManager(WorkMode.GENERAL)

    async def exercise() -> None:
        runtime = ProjectGraphRuntime(graph, index, manager, debounce_seconds=0)
        await runtime.activate()
        original_refresh = graph.refresh
        started = Event()
        release = Event()
        calls = 0

        def blocking_refresh(progress=None):
            nonlocal calls
            calls += 1
            started.set()
            release.wait(timeout=2)
            return original_refresh(progress)

        monkeypatch.setattr(graph, "refresh", blocking_refresh)
        runtime.mark_dirty(source)
        assert await asyncio.to_thread(started.wait, 2)
        deactivation = asyncio.create_task(runtime.deactivate())
        await asyncio.sleep(0)
        source.write_text("def main():\n    return 3\n", encoding="utf-8")
        runtime.mark_dirty(source)
        release.set()
        await deactivation

        assert calls == 1
        assert manager.current is WorkMode.GENERAL
        assert runtime.dirty
        await runtime.close()

    asyncio.run(exercise())
