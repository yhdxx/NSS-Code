from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


CapabilityKind = Literal["skill", "mcp_server"]


@dataclass(frozen=True)
class CapabilityRecommendation:
    kind: CapabilityKind
    name: str
    description: str = ""
    score: float = 0.0
    reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["score"] = round(self.score, 4)
        if self.kind == "skill":
            payload["skill_name"] = self.name
            payload["recommended_action"] = "invoke_skill"
            payload["invoke_tool"] = "invoke_skill"
        return payload


@dataclass(frozen=True)
class CapabilityResult:
    recommendations: tuple[CapabilityRecommendation, ...] = ()
    mcp_server_total_count: int = 0
    mcp_available_count: int = 0
    discovery_tools_available: bool = False
    note: str = (
        "Capability recommendations are not restrictions. "
        "Use list_servers/search_servers to discover omitted MCP servers when needed."
    )

    def to_runtime_payload(self) -> dict[str, Any]:
        return {
            "mcp_server_total_count": self.mcp_server_total_count,
            "mcp_available_count": self.mcp_available_count,
            "discovery_tools_available": self.discovery_tools_available,
            "mcp_discovery_pagination": {"default_limit": 20, "max_limit": 100},
            "mcp_tool_execution_available": self.discovery_tools_available,
            "mcp_resource_read_available": self.discovery_tools_available,
            "mcp_prompt_get_available": self.discovery_tools_available,
            "mcp_read_tool_calls_auto_allowed": True,
            "mcp_write_tool_calls_require_approval": True,
            "mcp_approval_required_for_non_read": True,
            "mcp_tool_intent_required": True,
            "recommendations_are_restrictions": False,
            "skill_recommendation_usage": "Call invoke_skill with recommendation.skill_name when a recommended SKILL should be applied.",
            "recommendations": [item.to_payload() for item in self.recommendations],
            "note": self.note,
        }
