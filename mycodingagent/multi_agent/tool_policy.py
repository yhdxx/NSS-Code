from __future__ import annotations

import copy
from typing import Any

from mycodingagent.tool_runtime import ToolRegistry
from mycodingagent.tool_runtime.base import Tool

from mycodingagent.multi_agent.models import AgentRole
from mycodingagent.multi_agent.store import MultiAgentStore
from mycodingagent.multi_agent.tools import control_tools_for_role


READ_TOOLS = {
    "ReadFile",
    "Glob",
    "Grep",
    "SearchSessionHistory",
    "SearchRecoverableContext",
    "BatchRecoverContext",
}
WRITE_TOOLS = {"WriteFile", "EditFile"}
COMMAND_TOOLS = {"Bash"}


def tool_names_for_role(role: AgentRole) -> set[str]:
    if role == AgentRole.PLAN:
        return set(READ_TOOLS)
    if role == AgentRole.PLAN_REVIEW:
        return set(READ_TOOLS)
    if role == AgentRole.SCHEDULING:
        return set(READ_TOOLS)
    if role == AgentRole.EXECUTE:
        return set(READ_TOOLS | WRITE_TOOLS | COMMAND_TOOLS)
    if role == AgentRole.TEST:
        return set(READ_TOOLS | COMMAND_TOOLS)
    if role == AgentRole.FINAL_TEST:
        return set(READ_TOOLS | COMMAND_TOOLS)
    if role == AgentRole.EXECUTE_REVIEW:
        return set(READ_TOOLS | COMMAND_TOOLS)
    return set()


def schemas_for_role(
    *,
    role: AgentRole,
    registry: ToolRegistry,
    store: MultiAgentStore,
) -> list[dict[str, Any]]:
    allowed = tool_names_for_role(role)
    schemas: list[dict[str, Any]] = []
    for schema in registry.get_all_schemas("openai"):
        if schema.get("name") not in allowed:
            continue
        prepared = copy.deepcopy(schema)
        if role == AgentRole.EXECUTE:
            prepared = add_task_id_to_schema(prepared)
            if prepared.get("name") == "Bash":
                prepared = add_declared_write_files_to_bash_schema(prepared)
        schemas.append(prepared)
    schemas.extend(schema_for_tool(tool) for tool in control_tools_for_role(store, role))
    return schemas


def add_task_id_to_schema(schema: dict[str, Any]) -> dict[str, Any]:
    parameters = schema.setdefault("parameters", {})
    properties = parameters.setdefault("properties", {})
    properties["task_id"] = {
        "type": "string",
        "description": "Current dispatched task_id. Must equal the task_id shown in execute context.",
    }
    required = parameters.setdefault("required", [])
    if isinstance(required, list) and "task_id" not in required:
        required.append("task_id")
    return schema


def add_step_id_to_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return add_task_id_to_schema(schema)


def add_declared_write_files_to_bash_schema(schema: dict[str, Any]) -> dict[str, Any]:
    parameters = schema.setdefault("parameters", {})
    properties = parameters.setdefault("properties", {})
    properties["declared_write_files"] = {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "Files this Bash command may modify. Use [] only for clearly read-only commands. "
            "Writable Bash commands that modify undeclared source files will be rejected and reverted."
        ),
    }
    required = parameters.setdefault("required", [])
    if isinstance(required, list) and "declared_write_files" not in required:
        required.append("declared_write_files")
    return schema


def schema_for_tool(tool: Tool) -> dict[str, Any]:
    base = tool.get_schema()
    return {
        "type": "function",
        "name": base["name"],
        "description": base["description"],
        "parameters": base["input_schema"],
    }
