from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from mycodingagent.configuration.settings import _default_builtin_skills_root
from mycodingagent.tool_runtime.bash import Bash


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "mycodingagent"


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _dependency_graph() -> dict[str, set[str]]:
    modules = {
        _module_name(path): path
        for path in PACKAGE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    graph: dict[str, set[str]] = defaultdict(set)
    for module, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                target = name
                while target and target not in modules:
                    target = target.rpartition(".")[0]
                if target and target != module:
                    graph[module].add(target)
    return graph


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(module: str) -> None:
        index = len(indices)
        indices[module] = lowlinks[module] = index
        stack.append(module)
        on_stack.add(module)
        for target in graph.get(module, set()):
            if target not in indices:
                visit(target)
                lowlinks[module] = min(lowlinks[module], lowlinks[target])
            elif target in on_stack:
                lowlinks[module] = min(lowlinks[module], indices[target])
        if lowlinks[module] != indices[module]:
            return
        component: list[str] = []
        while True:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == module:
                break
        components.append(component)

    all_modules = set(graph)
    all_modules.update(target for targets in graph.values() for target in targets)
    for module in sorted(all_modules):
        if module not in indices:
            visit(module)
    return [component for component in components if len(component) > 1]


def test_core_runtime_has_no_import_cycles():
    assert _cycles(_dependency_graph()) == []


def test_root_contains_only_thin_entrypoint_for_runtime_code():
    removed_runtime_files = {
        "cache.py",
        "client.py",
        "cli_input.py",
        "config.py",
        "conversation_history.py",
        "runtime_context.py",
        "session_switch.py",
        "workspace_identity.py",
    }
    assert not any((ROOT / name).exists() for name in removed_runtime_files)
    entrypoint = (ROOT / "__main__.py").read_text(encoding="utf-8")
    assert "from mycodingagent.app.main import main" in entrypoint


def test_multi_agent_roles_have_dedicated_directories():
    agents = PACKAGE_ROOT / "multi_agent" / "agents"
    expected = {"router", "planner", "auditor", "optimizer", "executor", "validator"}
    assert expected == {path.name for path in agents.iterdir() if path.is_dir() and not path.name.startswith("__")}
    for role in expected:
        assert (agents / role / "prompts.py").exists()


def test_orchestration_does_not_import_llm_or_tool_implementations():
    orchestration = PACKAGE_ROOT / "multi_agent" / "orchestration"
    source = "\n".join(path.read_text(encoding="utf-8") for path in orchestration.glob("*.py"))
    assert "mycodingagent.llm_runtime" not in source
    assert "mycodingagent.tool_runtime" not in source


def test_skill_tools_depend_on_contract_not_runtime():
    source = (PACKAGE_ROOT / "tool_runtime" / "skill_tools.py").read_text(encoding="utf-8")
    assert "skill_runtime.contracts import SkillService" in source
    assert "skill_runtime.runtime import SkillRuntime" not in source


def test_working_context_tool_depends_on_control_contract():
    source = (PACKAGE_ROOT / "tool_runtime" / "memory_lookup.py").read_text(encoding="utf-8")
    assert "memory.contracts import ContextEpochControl" in source
    assert "def __init__(self, context_control: ContextEpochControl)" in source


def test_context_epoch_manager_depends_on_store_protocol():
    source = (PACKAGE_ROOT / "memory" / "context_epoch.py").read_text(encoding="utf-8")
    assert "class ContextEpochStore(Protocol)" in source
    assert "SQLiteMemoryStore" not in source


def test_capability_discovery_does_not_import_mcp_implementation():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PACKAGE_ROOT / "capability_discovery").glob("*.py")
    )
    assert "mycodingagent.mcp_integration" not in source


def test_moved_modules_resolve_project_resources_from_repository_root(tmp_path):
    assert _default_builtin_skills_root() == ROOT / "skills"
    assert Bash(sandbox_root=tmp_path)._find_sandbox_dockerfile() == ROOT / "Dockerfile.sandbox"
