from __future__ import annotations

from typing import Any, Protocol


class MCPServerView(Protocol):
    name: str
    description: str
    tags: tuple[str, ...]
    aliases: tuple[str, ...]
    abbreviations: tuple[str, ...]
    synonyms: tuple[str, ...]
    keywords: tuple[str, ...]
    available: bool
    tools_count: int
    resources_count: int
    prompts_count: int


class SkillCapabilitySource(Protocol):
    records: dict[str, Any]
    router_retrieval_top_k: int

    async def build_tools_for_prompt_async(
        self,
        prompt: str,
        core_tool_schemas: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...

    def search_records_for_capability(self, query: str, *, top_k: int) -> list[Any]: ...


class MCPServerSource(Protocol):
    def server_count(self) -> int: ...

    def available_count(self) -> int: ...

    def list_servers(self) -> list[MCPServerView]: ...
