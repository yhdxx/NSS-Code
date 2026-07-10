from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from commands import CommandContext
from config import MultiCodingConfig
from multi_agent.controller import MultiCodingController
from multi_agent.hooks import CollectingRuntimeEventHook, StaticArchitectureApprovalHook
from multi_agent.models import AgentResult, AgentRole, WorkItem, WorkflowResult, WorkflowStatus
from multi_agent.orchestrator import (
    MultiCodingOrchestrator,
    architecture_approval_required,
    path_scopes_overlap,
    select_runnable_batch,
)
from multi_agent.permissions import (
    READ_ONLY_TOOLS,
    ToolAccessPolicy,
    ToolPermissionError,
    is_validation_command,
)
from tools import ToolRegistry
from tools.read_file import ReadFile
from tools.write_file import WriteFile


def load_app_main():
    path = Path(__file__).resolve().parents[1] / "__main__.py"
    spec = importlib.util.spec_from_file_location("mycodingagent_entrypoint", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeOrchestrator:
    async def run(self, prompt, messages):
        updated = list(messages or [])
        updated.extend(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "done"},
            ]
        )
        return WorkflowResult(status=WorkflowStatus.COMPLETED, response="done"), updated


class FakeRunner:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = []

    async def run(self, request):
        self.calls.append(request)
        system = request.system_prompt
        if "main routing agent" in system:
            return AgentResult(text='{"query":"add feature","needs_planning":true,"reason":"code change"}')
        if "Determine what project areas" in system:
            return AgentResult(
                text='{"audit_scopes":[{"name":"src","paths":["src"],"goals":["inspect module"]}]}'
            )
        if "Refine the proposed audit scopes" in system:
            return AgentResult(
                text='{"subtasks":[{"name":"src","paths":["src"],"goals":["inspect module"]}]}'
            )
        if "Inspect only the assigned scope" in system:
            return AgentResult(
                text=json.dumps(
                    {
                        "summary": "source module",
                        "modules": [{"name": "src", "paths": ["src"], "purpose": "feature code"}],
                        "functions": [],
                        "call_edges": [],
                        "risks": [],
                        "files_read": [],
                        "missing_scope": [],
                    }
                )
            )
        if "Merge child audit reports" in system:
            return AgentResult(
                text=json.dumps(
                    {
                        "summary": "merged audit",
                        "modules": [{"name": "src", "paths": ["src"], "purpose": "feature code"}],
                        "functions": [],
                        "call_edges": [],
                        "risks": [],
                        "files_read": [],
                        "missing_scope": [],
                    }
                )
            )
        if "Decide whether architecture optimization" in system:
            return AgentResult(text='{"needs_optimization":false,"reason":"small change"}')
        if "Convert the query" in system:
            return AgentResult(
                text=json.dumps(
                    {
                        "work_items": [
                            {
                                "task_id": "task-1",
                                "title": "Implement feature",
                                "objective": "create source module",
                                "allowed_paths": ["src/example.py"],
                                "dependencies": [],
                                "acceptance_criteria": ["file exists"],
                            }
                        ]
                    }
                )
            )
        if request.role == AgentRole.EXECUTOR:
            payload = json.loads(request.user_prompt)
            item = payload["work_item"]
            if item["task_id"] == "task-1":
                target = self.root / "src" / "example.py"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("def example():\n    return True\n", encoding="utf-8")
                changed = ["src/example.py"]
            else:
                target = self.root / "PROJECT_FRAMEWORK.md"
                target.write_text("# Framework\n\n- src/example.py: example()\n", encoding="utf-8")
                changed = ["PROJECT_FRAMEWORK.md"]
            return AgentResult(text=json.dumps({"summary": "implemented", "changed_files": changed}))
        if "read-only validation agent" in system:
            return AgentResult(
                text=json.dumps(
                    {
                        "passed": True,
                        "summary": "checks passed",
                        "checks": [{"name": "files", "status": "passed", "evidence": "present"}],
                        "failures": [],
                        "blocked": [],
                    }
                )
            )
        if "Summarize the completed multi-agent" in system:
            return AgentResult(text="Implemented the feature and validation passed.")
        raise AssertionError(f"unexpected request: {request.role} {system[:80]}")


def test_controller_persistent_enable_disable_and_run():
    controller = MultiCodingController(FakeOrchestrator(), MultiCodingConfig())
    controller.enable()
    assert controller.enabled is True
    assert "enabled" in controller.status_text()

    text, messages = asyncio.run(controller.run("task", []))
    assert text == "done"
    assert messages[-1]["content"] == "done"
    controller.disable()
    assert controller.enabled is False


def test_multicoding_command_controls_persistent_mode(capsys):
    app_main = load_app_main()
    controller = MultiCodingController(FakeOrchestrator(), MultiCodingConfig())
    context = CommandContext(
        memory_runtime=None,
        skill_runtime=None,
        messages=[],
        multicoding_controller=controller,
    )
    registry = app_main.build_command_registry()

    async def scenario():
        result = await registry.execute("/multicoding", context)
        assert result.handled is True
        assert controller.enabled is True
        await registry.execute("/multicoding status", context)
        await registry.execute("/multicoding off", context)

    asyncio.run(scenario())
    assert controller.enabled is False
    output = capsys.readouterr().out
    assert "多智能体模式已启用" in output
    assert "multicoding=enabled" in output
    assert "多智能体模式已关闭" in output


def test_tool_policy_enforces_read_only_and_scoped_writes(tmp_path):
    registry = ToolRegistry()
    registry.register(ReadFile(sandbox_root=tmp_path))
    registry.register(WriteFile(sandbox_root=tmp_path))

    read_policy = ToolAccessPolicy(READ_ONLY_TOOLS, tmp_path)
    schemas = read_policy.schemas(registry)
    assert schemas[0]["parameters"]["properties"]["file_path"]
    with pytest.raises(ToolPermissionError):
        read_policy.authorize("WriteFile", {"file_path": "src/a.py"})

    write_policy = ToolAccessPolicy(
        frozenset({"WriteFile"}),
        tmp_path,
        allowed_paths=("src",),
    )
    write_policy.authorize("WriteFile", {"file_path": "src/a.py"})
    with pytest.raises(ToolPermissionError):
        write_policy.authorize("WriteFile", {"file_path": "tests/a.py"})


def test_validation_command_allowlist():
    assert is_validation_command("pytest -q")
    assert is_validation_command("python3 -m pytest tests/test_multicoding.py")
    assert is_validation_command("npm run build")
    assert not is_validation_command("rm -rf .")
    assert not is_validation_command("pytest -q && rm -rf .")


def test_scheduler_parallelizes_disjoint_paths_and_serializes_overlaps(tmp_path):
    items = (
        WorkItem("a", "A", "A", ("src/a.py",)),
        WorkItem("b", "B", "B", ("src/b.py",)),
        WorkItem("c", "C", "C", ("src",)),
    )
    batch = select_runnable_batch(items, set(), 3, tmp_path)
    assert [item.task_id for item in batch] == ["a", "b"]
    assert path_scopes_overlap(("src/a.py",), ("src",), tmp_path)
    assert not path_scopes_overlap(("src/a.py",), ("tests/a.py",), tmp_path)


def test_orchestrator_runs_planned_workflow_and_updates_framework(tmp_path):
    runner = FakeRunner(tmp_path)
    events = CollectingRuntimeEventHook()
    orchestrator = MultiCodingOrchestrator(
        api_client=None,
        registry=ToolRegistry(),
        tools=[],
        core_tool_schemas=[],
        workspace_root=tmp_path,
        config=MultiCodingConfig(
            audit_parallelism=2,
            execution_parallelism=2,
            max_repair_rounds=1,
            max_agent_tool_rounds=5,
        ),
        event_hook=events,
        approval_hook=StaticArchitectureApprovalHook(True),
        runner=runner,
    )

    result, messages = asyncio.run(orchestrator.run("Implement feature", []))

    assert result.status == WorkflowStatus.COMPLETED
    assert result.verification is not None and result.verification.passed
    assert (tmp_path / "src" / "example.py").exists()
    assert (tmp_path / "PROJECT_FRAMEWORK.md").exists()
    assert "src/example.py" in result.changed_files
    assert "PROJECT_FRAMEWORK.md" in result.changed_files
    assert messages[-2]["role"] == "user"
    assert messages[-1]["role"] == "assistant"
    assert any(event.phase == "complete" for event in events.events)


def test_architecture_approval_required_for_structural_changes():
    from multi_agent.models import ArchitectureProposal

    assert architecture_approval_required(
        ArchitectureProposal(summary="split module", module_changes=("split service",))
    )
    assert not architecture_approval_required(
        ArchitectureProposal(summary="rename local variable", function_changes=("rename local",))
    )
