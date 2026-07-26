from __future__ import annotations

import copy
from typing import Any

from mycodingagent.tool_runtime import ToolRegistry
from mycodingagent.tool_runtime.base import Tool

from multiAgent.models import AgentRole
from multiAgent.store import MultiAgentStore
from multiAgent.tools import control_tools_for_role


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
    if role == AgentRole.EXECUTE:
        return set(READ_TOOLS | WRITE_TOOLS | COMMAND_TOOLS)
    if role == AgentRole.TEST:
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
            prepared = add_step_id_to_schema(prepared)
        schemas.append(prepared)
    schemas.extend(schema_for_tool(tool) for tool in control_tools_for_role(store, role))
    return schemas


def add_step_id_to_schema(schema: dict[str, Any]) -> dict[str, Any]:
    parameters = schema.setdefault("parameters", {})
    properties = parameters.setdefault("properties", {})
    properties["step_id"] = {
        "type": "string",
        "description": "Current approved plan step_id. Must equal the current_step_id shown in context.",
    }
    required = parameters.setdefault("required", [])
    if isinstance(required, list) and "step_id" not in required:
        required.append("step_id")
    return schema


def schema_for_tool(tool: Tool) -> dict[str, Any]:
    base = tool.get_schema()
    return {
        "type": "function",
        "name": base["name"],
        "description": base["description"],
        "parameters": base["input_schema"],
    }
