from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from capabilities.models import CapabilityRecommendation, CapabilityResult
from capabilities.retrieval import LexicalServerSignal
from mcp_client import MCPClientManager
from skills.lrfu_cache import LRFUCache


@dataclass(frozen=True)
class CapabilityRouterConfig:
    top_n: int = 10
    mcp_top_n: int = 5
    lrfu_decay: float = 0.95
    lrfu_weight: float = 0.35
    lexical_weight: float = 1.0


class CapabilityRouter:
    def __init__(
        self,
        *,
        skill_runtime: Any | None = None,
        mcp_manager: MCPClientManager | None = None,
        config: CapabilityRouterConfig | None = None,
    ) -> None:
        self.skill_runtime = skill_runtime
        self.mcp_manager = mcp_manager
        self.config = config or CapabilityRouterConfig()
        self._server_lrfu = LRFUCache(decay=self.config.lrfu_decay, max_entries=1000)
        self._round = 0
        self._lexical_signal = LexicalServerSignal()

    async def route(self, prompt: str) -> CapabilityResult:
        self._round += 1
        recommendations: list[CapabilityRecommendation] = []
        recommendations.extend(await self._skill_recommendations(prompt))
        recommendations.extend(self._mcp_recommendations(prompt))
        recommendations.sort(key=lambda item: (-item.score, item.kind, item.name))
        if self.mcp_manager is None:
            total = 0
            connected = 0
        else:
            total = self.mcp_manager.server_count()
            connected = self.mcp_manager.available_count()
        return CapabilityResult(
            recommendations=tuple(recommendations[: self.config.top_n]),
            mcp_server_total_count=total,
            mcp_available_count=connected,
            discovery_tools_available=self.mcp_manager is not None,
        )

    def record_mcp_server_use(self, server: str, *, reward: float = 1.0) -> None:
        self._round += 1
        self._server_lrfu.touch(server, current_round=self._round, reward=reward)

    async def build_tools_for_prompt(
        self,
        prompt: str,
        core_tool_schemas: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self.skill_runtime is None:
            return core_tool_schemas
        build = getattr(self.skill_runtime, "build_tools_for_prompt_async", None)
        if not callable(build):
            return core_tool_schemas
        return await build(prompt, core_tool_schemas)

    async def _skill_recommendations(self, prompt: str) -> list[CapabilityRecommendation]:
        runtime = self.skill_runtime
        if runtime is None or not getattr(runtime, "records", None):
            return []
        search = getattr(runtime, "_search_records", None)
        if not callable(search):
            return []
        try:
            results = search(prompt, top_k=min(5, getattr(runtime, "router_retrieval_top_k", 5)))
        except Exception:
            return []
        recommendations: list[CapabilityRecommendation] = []
        for result in results[:5]:
            record = result.record
            recommendations.append(
                CapabilityRecommendation(
                    kind="skill",
                    name=record.tool_name,
                    description=record.description,
                    score=float(result.score or 0.0),
                    reasons=("skill retrieval",),
                    metadata={"source_path": str(record.source_path)},
                )
            )
        return recommendations

    def _mcp_recommendations(self, prompt: str) -> list[CapabilityRecommendation]:
        if self.mcp_manager is None:
            return []
        servers = self.mcp_manager.list_servers()
        lexical = self._lexical_signal.score(prompt, servers)
        by_name = {
            item.server.name: CapabilityRecommendation(
                kind="mcp_server",
                name=item.server.name,
                description=item.server.description,
                score=item.score * self.config.lexical_weight,
                reasons=item.reasons or ("lexical match",),
                metadata={
                    "tags": item.server.tags,
                    "available": item.server.available,
                    "tools_count": item.server.tools_count,
                    "resources_count": item.server.resources_count,
                    "prompts_count": item.server.prompts_count,
                },
            )
            for item in lexical
        }
        lrfu_candidates = self._server_lrfu.top_candidates(limit=self.config.mcp_top_n, current_round=self._round)
        max_lrfu = max((item.score for item in lrfu_candidates), default=0.0)
        server_by_name = {server.name: server for server in servers}
        for candidate in lrfu_candidates:
            server = server_by_name.get(candidate.skill_name)
            if server is None:
                continue
            lrfu_score = (candidate.score / max_lrfu if max_lrfu > 0 else 0.0) * self.config.lrfu_weight
            existing = by_name.get(server.name)
            if existing is None:
                by_name[server.name] = CapabilityRecommendation(
                    kind="mcp_server",
                    name=server.name,
                    description=server.description,
                    score=lrfu_score,
                    reasons=("recently used MCP server",),
                    metadata={"tags": server.tags, "available": server.available},
                )
                continue
            by_name[server.name] = CapabilityRecommendation(
                kind=existing.kind,
                name=existing.name,
                description=existing.description,
                score=existing.score + lrfu_score,
                reasons=(*existing.reasons, "recently used MCP server"),
                metadata=existing.metadata,
            )
        ordered = sorted(by_name.values(), key=lambda item: (-item.score, item.name))
        return ordered[: self.config.mcp_top_n]
