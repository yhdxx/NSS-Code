import asyncio

from mycodingagent.code_intelligence.agentignore import AgentIgnore
from mycodingagent.code_intelligence.dynamic_dependency import DynamicDependencyRuntime
from mycodingagent.tool_runtime.project_graph import QueryUnitDependencyTool, UpdateUnitDescriptionTool


def test_agentignore_supports_comments_globs_directories_and_negation(tmp_path):
    (tmp_path / ".agentignore").write_text(
        "# generated files\nbuild/\n*.log\n/cache/*.json\n!build/keep.py\n",
        encoding="utf-8",
    )
    matcher = AgentIgnore(tmp_path)
    assert matcher.is_ignored("build/output.py")
    assert matcher.is_ignored("nested/build/output.py")
    assert not matcher.is_ignored("build/keep.py")
    assert matcher.is_ignored("debug.log")
    assert matcher.is_ignored("cache/data.json")


def test_dynamic_dependency_resolves_callers_callees_and_descriptions(tmp_path):
    (tmp_path / "caller.py").write_text(
        "from target import run\n\ndef invoke():\n    return run()\n",
        encoding="utf-8",
    )
    (tmp_path / "target.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    runtime = DynamicDependencyRuntime(tmp_path, tmp_path / "state.sqlite3")

    target = runtime.query("target.py::run")
    assert target["callers"][0]["unit_name"] == "caller.py::invoke"
    assert target["callers"][0]["path"] == "caller.py"
    assert runtime.update_description("target.py::run", "executes target operation")["status"] == "updated"
    assert runtime.query("target.py::run")["unit"]["description"] == "executes target operation"
    caller = runtime.query("caller.py::invoke")
    assert "callees" not in caller


def test_dynamic_tools_have_new_contract(tmp_path):
    (tmp_path / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    runtime = DynamicDependencyRuntime(tmp_path, tmp_path / "state.sqlite3")

    async def exercise():
        description = await UpdateUnitDescriptionTool(runtime).execute(
            UpdateUnitDescriptionTool.params_model(unit_name="main.py::main", description="entry point")
        )
        dependency = await QueryUnitDependencyTool(runtime).execute(
            QueryUnitDependencyTool.params_model(unit_name="main.py::main")
        )
        assert description.output == "修改成功"
        assert '"unit_name": "main.py::main"' in dependency.output

    asyncio.run(exercise())
