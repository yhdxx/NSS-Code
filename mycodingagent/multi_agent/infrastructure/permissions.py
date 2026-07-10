from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mycodingagent.tool_runtime import ToolRegistry


class ToolPermissionError(RuntimeError):
    pass


READ_ONLY_TOOLS = frozenset({"ReadFile", "Glob", "Grep"})
EXECUTION_TOOLS = frozenset({"ReadFile", "Glob", "Grep", "WriteFile", "EditFile"})
VALIDATION_TOOLS = frozenset({"ReadFile", "Glob", "Grep", "Bash"})
WRITE_TOOLS = frozenset({"WriteFile", "EditFile"})


@dataclass(frozen=True)
class ToolAccessPolicy:
    allowed_tools: frozenset[str]
    workspace_root: Path
    allowed_paths: tuple[str, ...] = ()
    allow_validation_bash: bool = False

    def schemas(self, registry: ToolRegistry) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for tool in registry.list_tools():
            if tool.name not in self.allowed_tools:
                continue
            base = tool.get_schema()
            schemas.append(
                {
                    "name": base["name"],
                    "description": base["description"],
                    "parameters": base["input_schema"],
                }
            )
        return schemas

    def authorize(self, tool_name: str, arguments: dict[str, Any]) -> None:
        if tool_name not in self.allowed_tools:
            raise ToolPermissionError(f"tool {tool_name!r} is not allowed for this agent role")
        if tool_name in WRITE_TOOLS:
            self._authorize_write_path(str(arguments.get("file_path") or ""))
        if tool_name == "Bash":
            if not self.allow_validation_bash:
                raise ToolPermissionError("Bash is not enabled for this agent role")
            command = str(arguments.get("command") or "").strip()
            if not is_validation_command(command):
                raise ToolPermissionError("validator Bash calls are limited to one test/build/static-check command")

    def _authorize_write_path(self, raw_path: str) -> None:
        if not raw_path:
            raise ToolPermissionError("write tool requires file_path")
        if not self.allowed_paths:
            raise ToolPermissionError("write agent has no assigned path scope")
        target = normalize_workspace_path(raw_path, self.workspace_root)
        allowed = [normalize_workspace_path(path, self.workspace_root) for path in self.allowed_paths]
        if not any(target == scope or scope in target.parents for scope in allowed):
            allowed_text = ", ".join(str(path) for path in allowed)
            raise ToolPermissionError(f"path {target} is outside assigned scope: {allowed_text}")


def normalize_workspace_path(raw_path: str, workspace_root: Path) -> Path:
    root = workspace_root.resolve()
    text = raw_path.strip()
    if text == "/workspace":
        return root
    if text.startswith("/workspace/"):
        text = text[len("/workspace/") :]
    path = Path(text)
    if not path.is_absolute():
        path = root / path
    return path.resolve(strict=False)


def is_validation_command(command: str) -> bool:
    if not command or any(token in command for token in ("\n", ";", "&&", "||", "|", ">", "<", "`")):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if not tokens:
        return False
    executable = Path(tokens[0]).name
    if executable in {"pytest", "ruff", "mypy", "tox", "npm", "pnpm", "yarn", "cargo", "go", "mvn", "gradle", "gradlew", "make"}:
        return _allowed_validation_subcommand(executable, tokens[1:])
    if executable in {"python", "python3"}:
        return len(tokens) >= 3 and tokens[1] == "-m" and tokens[2] in {
            "pytest",
            "unittest",
            "compileall",
            "mypy",
            "ruff",
        }
    if executable == "git":
        return len(tokens) >= 2 and tokens[1] in {"status", "diff"}
    return False


def _allowed_validation_subcommand(executable: str, args: list[str]) -> bool:
    if executable in {"pytest", "ruff", "mypy", "tox"}:
        return True
    if executable in {"npm", "pnpm", "yarn"}:
        return bool(args) and args[0] in {"test", "build", "lint", "typecheck", "run"}
    if executable == "cargo":
        return bool(args) and args[0] in {"test", "check", "clippy", "build"}
    if executable == "go":
        return bool(args) and args[0] in {"test", "vet", "build"}
    if executable in {"mvn", "gradle", "gradlew"}:
        return any(arg in {"test", "check", "build", "verify"} for arg in args)
    if executable == "make":
        return bool(args) and args[0] in {"test", "check", "lint", "build"}
    return False
