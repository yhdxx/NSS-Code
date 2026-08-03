from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mycodingagent.plan_runtime.models import InteractionMode


MCP_TOOL_NAMES = frozenset(
    {
        "list_mcp_servers",
        "search_mcp_servers",
        "list_mcp_tools",
        "search_mcp_tools",
        "list_mcp_resources",
        "search_mcp_resources",
        "list_mcp_prompts",
        "search_mcp_prompts",
        "call_mcp_tool",
        "read_mcp_resource",
        "get_mcp_prompt",
    }
)


@dataclass(frozen=True)
class TurnToolPolicy:
    interaction_mode: InteractionMode
    has_active_plan: bool = False

    def allows(self, tool: Any) -> bool:
        name = str(getattr(tool, "name", ""))
        if self.interaction_mode is InteractionMode.PLAN:
            if name in MCP_TOOL_NAMES or name in {"Bash", "WriteFile", "EditFile", "update_plan_step"}:
                return False
            return getattr(tool, "category", "read") != "write" or name == "UpdateProjectDescription"
        if name == "create_plan":
            return False
        if name == "update_plan_step":
            return self.has_active_plan
        return True

    def runtime_payload(self) -> dict[str, Any]:
        if self.interaction_mode is InteractionMode.PLAN:
            return {
                "workspace_write": "denied",
                "bash": "denied",
                "mcp": "denied",
                "skills": "allowed",
                "context_operations": "allowed",
                "project_description_updates": "allowed",
                "create_plan": "allowed",
                "update_plan_step": "denied",
                "enforcement": "runtime_execution_gate",
            }
        return {
            "workspace_write": "allowed",
            "bash": "allowed_with_existing_policy",
            "mcp": "allowed_with_existing_policy",
            "create_plan": "denied",
            "update_plan_step": "allowed" if self.has_active_plan else "denied",
            "enforcement": "runtime_execution_gate",
        }
