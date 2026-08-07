from __future__ import annotations

from typing import Any, Protocol

DEFAULT_DYNAMIC_SKILL_LIST_LIMIT = 20
MAX_DYNAMIC_SKILL_LIST_LIMIT = 100


class SkillService(Protocol):
    async def search_skill_schemas(
        self,
        *,
        query: str,
        max_results: int,
        tool_names: list[str],
    ) -> dict[str, Any]: ...

    async def list_dynamic_skills(
        self,
        *,
        offset: int = 0,
        limit: int = DEFAULT_DYNAMIC_SKILL_LIST_LIMIT,
    ) -> dict[str, Any]: ...

    async def search_skill_references(
        self,
        *,
        query: str,
        skill_name: str,
        max_results: int,
    ) -> dict[str, Any]: ...

    async def get_skill_reference(
        self,
        *,
        skill_name: str,
        reference_path: str,
    ) -> dict[str, Any]: ...

    def get_record(self, tool_name: str) -> Any | None: ...

    def record_skill_invocation(self, tool_name: str) -> None: ...

    def list_references_for_skill(self, tool_name: str) -> list[dict[str, Any]]: ...


class ToolRegistrar(Protocol):
    def register(self, tool: Any) -> None: ...
