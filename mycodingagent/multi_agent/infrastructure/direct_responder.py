from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from mycodingagent.llm_runtime import client as agent_client
from mycodingagent.tool_runtime import ToolRegistry


class LLMDirectResponder:
    def __init__(
        self,
        *,
        api_client: AsyncOpenAI,
        registry: ToolRegistry,
        tools: list[dict[str, Any]],
        core_tool_schemas: list[dict[str, Any]],
        skill_runtime: Any = None,
        workspace_tracker: Any = None,
        memory_runtime: Any = None,
        capability_router: Any = None,
    ) -> None:
        self.api_client = api_client
        self.registry = registry
        self.tools = tools
        self.core_tool_schemas = core_tool_schemas
        self.skill_runtime = skill_runtime
        self.workspace_tracker = workspace_tracker
        self.memory_runtime = memory_runtime
        self.capability_router = capability_router

    async def respond(
        self,
        prompt: str,
        messages: list[dict[str, Any]] | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        return await agent_client.ask_deepseek(
            self.api_client,
            prompt,
            self.registry,
            self.tools,
            messages,
            skill_runtime=self.skill_runtime,
            core_tool_schemas=self.core_tool_schemas,
            workspace_tracker=self.workspace_tracker,
            memory_runtime=self.memory_runtime,
            capability_router=self.capability_router,
        )
