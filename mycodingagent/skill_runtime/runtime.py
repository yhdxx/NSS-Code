from __future__ import annotations

import time
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from mycodingagent.configuration import CONFIG
from mycodingagent.llm_runtime.providers import InferenceProvider
from mycodingagent.skill_runtime.discovery import discover_reference_records, discover_skill_records, normalize_tool_name
from mycodingagent.skill_runtime.dynamic_summary import DynamicSkillSummary
from mycodingagent.skill_runtime.embeddings import EmbeddingCache, create_embedding_service
from mycodingagent.skill_runtime.index import SkillSqlStore
from mycodingagent.skill_runtime.models import SearchResult, SkillRecord, SkillReferenceRecord, SkillSyncReport
from mycodingagent.skill_runtime.reviewers import review_skill_code, review_skill_prompt
from mycodingagent.skill_runtime.router import SkillRouter, SkillRouterConfig
from mycodingagent.skill_runtime.session_skill_cache import SessionSkillCache
from mycodingagent.skill_runtime.contracts import ToolRegistrar
from mycodingagent.tool_runtime.skill_tools import (
    ListDynamicSkillsTool,
    GetSkillReferenceTool,
    InvokeSkillTool,
    SearchSkillReferencesTool,
    SearchSkillTool,
    SkillTool,
)
from mycodingagent.skill_runtime.user_skill_cache import UserSkillCache
from mycodingagent.skill_runtime.vector_store import create_vector_store
from mycodingagent.skill_runtime.watcher import MultiSkillDirectoryWatcher

TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")

SEARCH_HINT = (
    "查询、列举、确认当前可用 Dynamic Skill 时，必须优先调用 list_dynamic_skills，禁止用 Bash、Glob、ReadFile "
    "直接检查 skills 目录或 .skill_runtime 数据库。需要按能力查找 SKILL 时，调用 search_skill 批量检索，"
    "search_skill 的 query 必须使用中文能力描述；如果用户使用英文或中英混合表达，先翻译/概括成中文再检索。"
    "最多尝试三次（防止死循环），且三次检索必须逐步放宽：具体任务 -> 同义词/能力类别 -> 上位领域。"
    "只有当 Dynamic Skill 能力摘要中明确描述了你需要的能力，且三次 search_skill 都没有找到对应 Skill 时，才允许调用 list_dynamic_skills；"
    "如果摘要描述中没有相关能力，禁止调用 list_dynamic_skills，以减少不必要 token 消耗。"
    "search_skill 或 list_dynamic_skills 返回准确 skill_name 后，需要应用该 SKILL 时直接调用 invoke_skill。"
)

SKILL_TIER_POLICY = (
    "Skill 分层规则：Skill 分为 fixed 和 Dynamic 两类。fixed 是少量稳定、每轮都可能需要的基础工作流；"
    "启动时只把它们的 skill_name、name、description 卡片放入 system prompt，任务匹配时可直接按名调用 invoke_skill，"
    "完整正文不会预先占用上下文。Dynamic 是可持续增长的专家工作流目录，不把全部 Skill 放进提示词，先用能力摘要判断"
    "是否可能相关，再按需调用 search_skill；命中后同样只通过 invoke_skill 加载完整正文。这样既保持固定前缀稳定、"
    "有利于模型缓存，又避免大量暂时无关的 Skill 消耗上下文。fixed 和 Dynamic 都不是自动执行，必须由任务相关性决定是否调用。"
)

CAPABILITY_SELECTION_POLICY = (
    "能力选择策略：\n"
    "你每轮收到用户请求后，必须先区分三类能力：Model 自身能力、Business Skill、Core Tool。\n"
    "Business Skill 是开发者定义的专家工作流，用于提供领域知识、标准流程、约束和最佳实践；"
    "Core Tool 只负责读写文件、搜索、执行命令等基础操作；Model 自身能力只用于常识问答、推理、总结、翻译和简单文本生成。\n"
    "决策顺序：\n"
    "1. 只有同时满足以下条件，才允许直接依赖 Model 自身能力回答：不需要任何 Tool；不需要任何 Business Skill；"
    "不需要访问本地代码、文件或命令；当前 Prompt 中不存在明显匹配的 Business Skill。\n"
    "2. 如果 Runtime Context recommendations、search_skill、list_dynamic_skills 或 fixed Skill 卡片已经识别出高度匹配的 Business Skill，"
    "必须优先调用固定工具 invoke_skill，并传入对应 skill_name；"
    "不得因为你自己知道如何完成，就跳过该 Skill；Business Skill 优先级高于 Model 自身能力和 Core Tool。\n"
    "3. 如果 fixed Skill 卡片中没有匹配项，但 Dynamic Skill 能力摘要表明任务可能存在相关 Skill，必须先调用 search_skill 检索；"
    "若摘要明确完全不覆盖用户需求，可以跳过 Skill 检索；若摘要因首次生成或模型错误而暂不可用，"
    "则在任务可能需要专家工作流时保守地调用 search_skill。"
    "调用 search_skill 时，query 必须使用中文表达；如果用户原始需求是英文或中英混合，先在 query 中翻译/概括为中文能力描述再检索。"
    "连续多次检索时，必须逐步放宽范围：第一次使用具体任务，第二次使用同义词和能力类别，第三次使用上位领域；不要越搜越窄。"
    "只有当 Dynamic Skill 能力摘要明确描述了需要的能力，且三次 search_skill 均未命中时，才允许调用 list_dynamic_skills；否则禁止调用 list_dynamic_skills。\n"
    "4. 只有不存在相关 Business Skill、Business Skill 明显无法完成任务，或 Skill 指令明确要求执行操作时，才直接调用 Core Tool。\n"
    "禁止行为：Business Skill 已存在时，禁止直接依赖 HTML/CSS/Python/Java 等自身知识完成整个任务；"
    "禁止直接调用 ReadFile、WriteFile、EditFile、Glob、Grep、Bash 等 Core Tool 替代 Business Skill 的专家工作流。\n"
    "典型规则：设计/实现/优化前端页面、组件、Web App、UI/UX 时，如果 skill_frontend_design 可用，必须先调用 "
    "invoke_skill(skill_name=\"skill_frontend_design\")；代码 Review 时如果 skill_review 可用，必须先调用 "
    "invoke_skill(skill_name=\"skill_review\")；后端面试时如果 skill_backend_interview 可用，必须先调用 "
    "invoke_skill(skill_name=\"skill_backend_interview\")。"
)

class SkillRuntime:
    def __init__(
        self,
        *,
        skills_root: Path | None = None,
        skill_roots: tuple[Path, ...] | list[Path] | None = None,
        registry: ToolRegistrar,
        summary_provider_getter: Callable[[], InferenceProvider] | None = None,
    ) -> None:
        self.skills_root = skills_root or CONFIG.skills.root
        self.skill_base_roots = tuple(skill_roots or CONFIG.skills.roots)
        self.fixed_roots = tuple(root / "fixed" for root in self.skill_base_roots)
        self.dynamic_roots = tuple(root / "Dynamic" for root in self.skill_base_roots)
        self.skill_roots = (*self.fixed_roots, *self.dynamic_roots)
        self._builtin_root = CONFIG.skills.builtin_root
        self.registry = registry
        self.small_count = CONFIG.skills.small_count
        self.prefetch_top_k = CONFIG.skills.prefetch_top_k
        self.search_top_k = CONFIG.skills.search_top_k
        self.min_score = CONFIG.skills.min_score
        index_dir = CONFIG.skills.index_dir or (self.skills_root / ".skill_runtime")
        self.user_skills_root = CONFIG.skills.user_root
        self.store = SkillSqlStore(index_dir / "skills.sqlite3")
        self.embedding_service = create_embedding_service()
        self.embedding_cache = EmbeddingCache(index_dir / "embeddings.sqlite3")
        self.vector_store = create_vector_store(self.embedding_service, self.embedding_cache)
        self.user_id = CONFIG.skills.user_id
        self.session_id = f"{int(time.time() * 1000)}-{uuid4().hex}"
        self.session_skill_call_round = 0
        self.router_retrieval_top_k = CONFIG.skills.router_retrieval_top_k
        self.router_cache_top_k = CONFIG.skills.router_cache_top_k
        self.session_activation_reward = CONFIG.skills.session_activation_reward
        self.skill_call_reward = CONFIG.skills.skill_call_reward
        self.router = SkillRouter(
            SkillRouterConfig(
                top_n=CONFIG.skills.router_top_n,
                retrieval_min_ratio=CONFIG.skills.router_retrieval_min_ratio,
                user_weight=CONFIG.skills.router_user_weight,
                session_weight=CONFIG.skills.router_session_weight,
                retrieval_weight=CONFIG.skills.router_retrieval_weight,
            )
        )
        self.user_skill_cache = UserSkillCache(
            index_dir / "user_skill_lrfu.sqlite3",
            decay=CONFIG.skills.lrfu_decay,
            reward=CONFIG.skills.skill_call_reward,
            max_entries=CONFIG.skills.user_skill_cache_max_entries,
        )
        self.user_skill_cache.start_session(user_id=self.user_id, session_id=self.session_id)
        self.session_skill_cache = SessionSkillCache(
            decay=CONFIG.skills.lrfu_decay,
            max_entries=CONFIG.skills.session_skill_cache_max_entries,
        )
        self.dynamic_skill_summary = DynamicSkillSummary(
            index_dir / "dynamic_skill_summary.json",
            provider_getter=summary_provider_getter,
        )
        self.records = self.store.load_all()
        self.references = self.store.load_references()
        self.search_skill_tool_instance = SearchSkillTool(self)
        self.list_dynamic_skills_tool_instance = ListDynamicSkillsTool(self)
        self.search_references_tool_instance = SearchSkillReferencesTool(self)
        self.get_reference_tool_instance = GetSkillReferenceTool(self)
        self.invoke_skill_instance = InvokeSkillTool(self)
        self._registered_skill_tools: set[str] = set()
        self._watcher = MultiSkillDirectoryWatcher(self.skill_roots)

    async def initialize(self) -> SkillSyncReport:
        self._watcher.start()
        report = await self.ensure_synced()
        self._ensure_vector_index_complete(report)
        await self.dynamic_skill_summary.refresh(self.dynamic_records)
        self.registry.register(self.search_skill_tool_instance)
        self.registry.register(self.list_dynamic_skills_tool_instance)
        self.registry.register(self.search_references_tool_instance)
        self.registry.register(self.get_reference_tool_instance)
        self.registry.register(self.invoke_skill_instance)
        return report

    def search_records_for_capability(self, query: str, *, top_k: int) -> list[SearchResult]:
        return self._search_records(query, top_k=top_k)

    def recommend_records_for_capability(self, query: str, *, top_k: int) -> list[SearchResult]:
        retrieval_results = self._search_records(
            query,
            top_k=max(top_k, self.router_retrieval_top_k),
        )
        user_candidates = self.user_skill_cache.top_candidates(
            user_id=self.user_id,
            limit=self.router_cache_top_k,
        )
        session_candidates = self.session_skill_cache.top_candidates(
            limit=self.router_cache_top_k,
            current_round=self.session_skill_call_round,
        )
        dynamic_records = self.dynamic_records
        selected = self.router.select(
            records=dynamic_records,
            retrieval_results=retrieval_results,
            user_candidates=user_candidates,
            session_candidates=session_candidates,
        )
        by_name = {result.record.tool_name: result for result in retrieval_results}
        recommendations: list[SearchResult] = []
        for rank, record in enumerate(selected[:top_k], start=1):
            retrieval_result = by_name.get(record.tool_name)
            if retrieval_result is not None:
                recommendations.append(
                    SearchResult(
                        record=record,
                        score=retrieval_result.score,
                        keyword_score=retrieval_result.keyword_score,
                        semantic_score=retrieval_result.semantic_score,
                        metadata={**retrieval_result.metadata, "router_source": "skill_router"},
                    )
                )
                continue
            recommendations.append(
                SearchResult(
                    record=record,
                    score=1.0 / rank,
                    keyword_score=0.0,
                    semantic_score=0.0,
                    metadata={"retriever": "skill_router_lrfu", "router_source": "skill_router"},
                )
            )
        return recommendations

    def close(self) -> None:
        try:
            self.user_skill_cache.commit_session(user_id=self.user_id, session_id=self.session_id)
        finally:
            self._watcher.stop()

    async def ensure_synced(self) -> SkillSyncReport:
        if not self._watcher.consume_dirty():
            return SkillSyncReport()
        return await self.sync()

    def _ensure_vector_index_complete(self, report: SkillSyncReport | None = None) -> None:
        try:
            stale_records = self.vector_store.stale_records(self.dynamic_records)
        except Exception:
            return
        if not stale_records:
            return

        batch_size = max(1, CONFIG.skills.vector_sync_batch_size)
        for index in range(0, len(stale_records), batch_size):
            batch = stale_records[index:index + batch_size]
            ok, _ = self._upsert_vector_batch_with_retry(batch)
            if not ok:
                continue
            if report is not None:
                report.embedding_cache_hits += getattr(self.vector_store, "last_cache_hits", 0)
                report.embedding_cache_misses += getattr(self.vector_store, "last_cache_misses", 0)
        if report is not None:
            report.changed = True

    def _upsert_vector_batch_with_retry(self, batch: list[SkillRecord]) -> tuple[bool, Exception | None]:
        max_retries = max(1, CONFIG.skills.vector_sync_max_retries)
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                self.vector_store.upsert(batch)
                return True, None
            except Exception as exc:
                last_exc = exc
                if attempt >= max_retries:
                    break
                wait_seconds = min(2 ** (attempt - 1), 8)
                time.sleep(wait_seconds)
        return False, last_exc

    async def sync(self) -> SkillSyncReport:
        fixed_discovered = discover_skill_records(self.fixed_roots, tier="fixed")
        dynamic_discovered = discover_skill_records(self.dynamic_roots, tier="dynamic")
        fixed_names = {record.tool_name for record in fixed_discovered}
        conflicts = [record for record in dynamic_discovered if record.tool_name in fixed_names]
        discovered = [
            *fixed_discovered,
            *(record for record in dynamic_discovered if record.tool_name not in fixed_names),
        ]
        stored = self.store.load_all()
        report = SkillSyncReport(
            rejected=[f"{record.source_path}: 与 fixed Skill 工具名冲突" for record in conflicts]
        )
        if conflicts:
            report.changed = True
        existing_sources = {str(record.source_path) for record in discovered}
        existing_tool_names = {record.tool_name for record in discovered}
        changed_records: list[SkillRecord] = []

        deleted = self.store.delete_missing_sources(existing_sources)
        deleted += self.store.delete_missing_tool_names(existing_tool_names)
        if deleted:
            report.changed = True
            report.deleted = deleted

        for record in discovered:
            previous = stored.get(record.tool_name)
            if previous and previous.content_hash == record.content_hash and str(previous.source_path) == str(record.source_path):
                continue

            rejection = await self._review(record)
            if rejection:
                self.store.reject(record.source_path, rejection, time.time())
                report.changed = True
                report.rejected.append(f"{record.source_path}: {rejection}")
                continue

            self.store.upsert(record)
            changed_records.append(record)
            report.changed = True
            if previous is None:
                report.added += 1
            else:
                report.updated += 1

        current_records = self.store.load_all()
        reference_report = self._sync_references(current_records)
        report.reference_added += reference_report[0]
        report.reference_updated += reference_report[1]
        report.reference_deleted += reference_report[2]
        if any(reference_report):
            report.changed = True
        changed_dynamic_records = [
            record for record in changed_records if record.metadata.get("tier", "dynamic") == "dynamic"
        ]
        dynamic_records = {
            name: record
            for name, record in current_records.items()
            if record.metadata.get("tier", "dynamic") == "dynamic"
        }
        if changed_dynamic_records:
            self.vector_store.upsert(changed_dynamic_records)
            report.embedding_cache_hits += getattr(self.vector_store, "last_cache_hits", 0)
            report.embedding_cache_misses += getattr(self.vector_store, "last_cache_misses", 0)
        if getattr(self.vector_store, "needs_full_sync", False):
            self.vector_store.upsert(list(dynamic_records.values()))
            report.embedding_cache_hits += getattr(self.vector_store, "last_cache_hits", 0)
            report.embedding_cache_misses += getattr(self.vector_store, "last_cache_misses", 0)
        if report.changed:
            dynamic_names = set(dynamic_records)
            self.vector_store.delete_missing(dynamic_names)
            self.embedding_cache.delete_missing(dynamic_names)
        self.records = current_records
        self.references = self.store.load_references()
        self._register_available_skill_tools()
        return report

    def get_record(self, tool_name: str) -> SkillRecord | None:
        return self.records.get(tool_name)

    @property
    def fixed_records(self) -> dict[str, SkillRecord]:
        return {
            name: record
            for name, record in self.records.items()
            if record.metadata.get("tier") == "fixed"
        }

    @property
    def dynamic_records(self) -> dict[str, SkillRecord]:
        return {
            name: record
            for name, record in self.records.items()
            if record.metadata.get("tier", "dynamic") == "dynamic"
        }

    def list_references_for_skill(self, tool_name: str) -> list[dict[str, Any]]:
        records = [
            record
            for record in self.references.values()
            if record.skill_tool_name == tool_name
        ]
        return [
            {
                "ref_id": record.ref_id,
                "reference_path": record.reference_path,
                "file_name": record.file_name,
                "source_path": str(record.source_path),
            }
            for record in sorted(records, key=lambda item: item.reference_path)
        ]

    def build_tools_for_prompt(self, prompt: str, core_tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _dedupe_schemas(core_tool_schemas + self._skill_management_schemas())

    async def build_tools_for_prompt_async(
        self,
        prompt: str,
        core_tool_schemas: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        await self.ensure_synced()
        return self.build_tools_for_prompt(prompt, core_tool_schemas)

    async def search_skill_schemas(self, *, query: str, max_results: int, tool_names: list[str] | None = None) -> dict[str, Any]:
        await self.ensure_synced()
        limit = max(1, min(max_results or self.search_top_k, self.search_top_k))
        results = self._search_records(
            query,
            top_k=limit,
            preferred_names=tool_names,
        )
        skills = [_skill_payload_from_record(item.record) for item in results]
        return {
            "hint": SEARCH_HINT,
            "count": len(skills),
            "next_step": "需要应用其中某个工作流时，使用准确的 skill_name 调用 invoke_skill。",
            "skills": [
                {
                    **skill,
                    "score": round(result.score, 4),
                    "keyword_score": round(result.keyword_score, 4),
                    "semantic_score": round(result.semantic_score, 4),
                    "retriever": result.metadata.get("retriever", "milvus_hnsw_bm25_rrf"),
                    "source_path": str(result.record.source_path),
                }
                for skill, result in zip(skills, results)
            ],
        }

    async def list_dynamic_skills(self) -> dict[str, Any]:
        await self.ensure_synced()
        records = sorted(self.dynamic_records.values(), key=lambda record: record.tool_name)
        return {
            "count": len(records),
            "tools": [
                {
                    "name": record.tool_name,
                    "description": record.description,
                    "source": self._source_kind(record.source_path),
                    "source_path": str(record.source_path),
                }
                for record in records
            ],
            "next_step": "使用准确的 skill_name 调用 invoke_skill 应用工作流。",
        }

    async def search_skill_references(self, *, query: str = "", skill_name: str = "", max_results: int = 5) -> dict[str, Any]:
        await self.ensure_synced()
        query = query.strip()
        resolved_skill = self._resolve_skill_tool_name(skill_name) if skill_name else ""
        if skill_name and not resolved_skill:
            return {
                "error": f"未找到 SKILL 工具：{skill_name}",
                "hint": "使用 list_dynamic_skills 查看准确的可用 Dynamic Skill 名称。",
                "count": 0,
                "references": [],
            }
        limit = max(1, min(max_results or 5, 20))
        references = [
            reference
            for reference in self.references.values()
            if not resolved_skill or reference.skill_tool_name == resolved_skill
        ]
        if query:
            results = _rank_references(
                query=query,
                references=references,
                skill_tool_name=resolved_skill,
                limit=limit,
            )
        else:
            results = [
                (reference, 0.0)
                for reference in sorted(references, key=lambda item: item.reference_path)[:limit]
            ]
            if not resolved_skill:
                return {
                    "count": 0,
                    "references": [],
                    "hint": "除非提供 skill_name，否则必须提供 query。要列出某个 Skill 的引用，只需提供 skill_name。",
                }
        return {
            "count": len(results),
            "references": [
                {
                    "ref_id": reference.ref_id,
                    "skill_name": reference.skill_name,
                    "skill_tool_name": reference.skill_tool_name,
                    "reference_path": reference.reference_path,
                    "file_name": reference.file_name,
                    "source_path": str(reference.source_path),
                    "score": round(score, 4),
                    "snippet": _reference_snippet(reference.content, query),
                }
                for reference, score in results
            ],
            "next_step": "使用 skill_name 和结果中的准确 reference_path 调用 Get_skill_reference，以读取完整引用。",
        }

    async def get_skill_reference(self, *, skill_name: str, reference_path: str) -> dict[str, Any]:
        await self.ensure_synced()
        skill_tool_name = self._resolve_skill_tool_name(skill_name)
        if not skill_tool_name:
            return {
                "error": f"未找到 SKILL 工具：{skill_name}",
                "hint": "使用 list_dynamic_skills 查看准确的可用 Dynamic Skill 名称。",
            }
        normalized_path = _normalize_reference_path(reference_path)
        if normalized_path is None:
            return {
                "error": f"引用路径无效：{reference_path}",
                "hint": "reference_path 必须位于 references/ 下，并且不能包含 '..'。",
            }
        ref_id = f"{skill_tool_name}:{normalized_path}"
        reference = self.references.get(ref_id)
        if reference is None:
            return {
                "error": f"未找到 SKILL 引用：{skill_tool_name} {normalized_path}",
                "hint": "使用 search_skill_references 或调用该 SKILL 工具查看可用的 reference_path。",
            }
        return {
            "ref_id": reference.ref_id,
            "skill_name": reference.skill_name,
            "skill_tool_name": reference.skill_tool_name,
            "reference_path": reference.reference_path,
            "source_path": str(reference.source_path),
            "content": reference.content,
        }

    def system_hint(self) -> str:
        parts = [SKILL_TIER_POLICY, CAPABILITY_SELECTION_POLICY, SEARCH_HINT]
        summary = self.dynamic_skill_summary.summary.strip()
        if summary:
            parts.append(_dynamic_skill_summary_hint(summary))
        return "\n\n".join(parts)

    def fixed_skill_hint(self, *, max_tokens: int | None = None) -> str:
        records = [self.fixed_records[name] for name in sorted(self.fixed_records)]
        if not records:
            return ""
        token_budget = max_tokens or CONFIG.skills.fixed_prompt_max_tokens
        parts = ["以下是当前会话固定可用的 Skill 卡片。只有任务确实匹配时才调用 invoke_skill，卡片不代表 Skill 已执行："]
        used_tokens = _estimate_card_tokens(parts[0])
        included = 0
        for record in records:
            card = (
                f"\n- skill_name: {record.tool_name}\n"
                f"  name: {record.name}\n"
                f"  description: {record.description[:800]}"
            )
            card_tokens = _estimate_card_tokens(card)
            if used_tokens + card_tokens > token_budget:
                break
            parts.append(card)
            used_tokens += card_tokens
            included += 1
        omitted = len(records) - included
        if omitted:
            parts.append(f"\n- 另有 {omitted} 个 fixed Skill 因固定卡片预算未展示")
        return "\n".join(parts)

    async def materialize_dynamic_skill(
        self,
        *,
        memory_uid: str,
        workflow: dict[str, Any],
        content: str,
    ) -> dict[str, str]:
        name = str(workflow.get("name") or "").strip()
        description = str(workflow.get("description") or "").strip()
        when_to_use = str(workflow.get("when_to_use") or "").strip()
        when_not_use = [str(item).strip() for item in list(workflow.get("when_not_use") or []) if str(item).strip()]
        if not name or not description or not when_to_use or not content.strip():
            return {"status": "failed", "error": "长期记忆工作流缺少生成 Dynamic Skill 所需字段"}

        tool_name = normalize_tool_name(name)
        skill_path = self.user_skills_root / "Dynamic" / tool_name / CONFIG.skills.markdown_filename
        if skill_path.exists():
            try:
                existing = skill_path.read_text(encoding="utf-8")
            except OSError as exc:
                return {"status": "failed", "error": f"读取现有 Dynamic Skill 失败：{exc}"}
            if f"memory_uid: {memory_uid}" not in existing:
                return {"status": "conflict", "error": f"Dynamic Skill 已存在且不属于 memory_uid={memory_uid}"}

        skill_path.parent.mkdir(parents=True, exist_ok=True)
        generated = _render_generated_dynamic_skill(
            name=name,
            description=description,
            when_to_use=when_to_use,
            when_not_use=when_not_use,
            content=content,
            memory_uid=memory_uid,
        )
        temporary_path = skill_path.with_suffix(".tmp")
        try:
            temporary_path.write_text(generated, encoding="utf-8")
            temporary_path.replace(skill_path)
        except OSError as exc:
            return {"status": "failed", "error": f"写入 Dynamic Skill 失败：{exc}"}

        await self.sync()
        record = self.records.get(tool_name)
        if record is None or record.metadata.get("tier") != "dynamic":
            return {"status": "failed", "error": "Dynamic Skill 写入后未能通过同步与审核"}
        return {"status": "materialized", "tool_name": tool_name, "path": str(skill_path)}

    def _skill_management_schemas(self) -> list[dict[str, Any]]:
        return [
            self.search_skill_tool_instance.get_schema(),
            self.list_dynamic_skills_tool_instance.get_schema(),
            self.search_references_tool_instance.get_schema(),
            self.get_reference_tool_instance.get_schema(),
            self.invoke_skill_instance.get_schema(),
        ]

    def _register_available_skill_tools(self) -> None:
        for tool_name in self.records:
            if tool_name in self._registered_skill_tools:
                continue
            self.registry.register(SkillTool(self, tool_name))
            self._registered_skill_tools.add(tool_name)

    def record_skill_invocation(self, tool_name: str) -> None:
        if tool_name not in self.records:
            return
        if tool_name not in self.dynamic_records:
            return
        self.session_skill_call_round += 1
        self.session_skill_cache.touch(
            tool_name,
            current_round=self.session_skill_call_round,
            reward=self.skill_call_reward,
        )
        self.user_skill_cache.record_skill_call(
            user_id=self.user_id,
            session_id=self.session_id,
            skill_name=tool_name,
            session_skill_call_round=self.session_skill_call_round,
        )

    def _search_records(
        self,
        query: str,
        *,
        top_k: int,
        preferred_names: list[str] | None = None,
    ) -> list[SearchResult]:
        records = self.dynamic_records
        results = self.vector_store.search(
            query,
            records=records,
            top_k=top_k,
            preferred_names=preferred_names,
        )
        return _merge_search_results(
            primary=results or [],
            fallback=_local_keyword_search(
                query,
                records=records,
                top_k=top_k,
                preferred_names=preferred_names,
            ),
            top_k=top_k,
        )

    def _source_kind(self, source_path: Path) -> str:
        source_path = source_path.resolve(strict=False)
        builtin_root = self._builtin_root.resolve(strict=False)
        if _is_relative_to(source_path, builtin_root):
            return "builtin"
        workspace_root = self.skills_root.resolve(strict=False)
        if _is_relative_to(source_path, workspace_root):
            return "workspace"
        for root in self.skill_roots:
            if _is_relative_to(source_path, root.resolve(strict=False)):
                return "extra"
        return "extra"

    def _sync_references(self, current_records: dict[str, SkillRecord]) -> tuple[int, int, int]:
        discovered_references = discover_reference_records(current_records)
        previous = self.store.load_references()
        existing_ref_ids = {record.ref_id for record in discovered_references}
        added = 0
        updated = 0
        for reference in discovered_references:
            previous_record = previous.get(reference.ref_id)
            if (
                previous_record is not None
                and previous_record.content_hash == reference.content_hash
                and str(previous_record.source_path) == str(reference.source_path)
            ):
                continue
            self.store.upsert_reference(reference)
            if previous_record is None:
                added += 1
            else:
                updated += 1
        deleted = self.store.delete_missing_references(existing_ref_ids)
        deleted += self.store.delete_references_for_missing_skills(set(current_records))
        return added, updated, deleted

    def _resolve_skill_tool_name(self, name: str) -> str:
        candidate = name.strip()
        if not candidate:
            return ""
        normalized = normalize_tool_name(candidate)
        if candidate in self.records:
            return candidate
        if normalized in self.records:
            return normalized
        lower_name = candidate.lower()
        matches = [
            record.tool_name
            for record in self.records.values()
            if lower_name == record.name.lower()
            or lower_name == record.tool_name.lower()
        ]
        if len(matches) == 1:
            return matches[0]
        return ""

    async def _review(self, record: SkillRecord) -> str:
        code_result = await review_skill_code(record.source_path, record.content)
        if not code_result.approved:
            return code_result.reason or "skill code review rejected"
        prompt_result = await review_skill_prompt(record.source_path, record.content)
        if not prompt_result.approved:
            return prompt_result.reason or "skill prompt review rejected"
        return ""


def _dedupe_schemas(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for schema in schemas:
        name = schema.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(schema)
    return result


def _skill_payload_from_record(record: SkillRecord) -> dict[str, Any]:
    return {
        "skill_name": record.tool_name,
        "name": record.name,
        "description": record.description,
        "recommended_action": "invoke_skill",
        "invoke_tool": "invoke_skill",
    }


def _merge_search_results(
    *,
    primary: list[SearchResult],
    fallback: list[SearchResult],
    top_k: int,
) -> list[SearchResult]:
    merged: dict[str, SearchResult] = {}
    for result in primary:
        merged[result.record.tool_name] = result
    for result in fallback:
        existing = merged.get(result.record.tool_name)
        if existing is None:
            merged[result.record.tool_name] = result
            continue
        existing.score += result.score
        existing.keyword_score = max(existing.keyword_score, result.keyword_score)
        existing.metadata["local_keyword_fallback"] = True
    return sorted(merged.values(), key=lambda item: item.score, reverse=True)[:top_k]


def _local_keyword_search(
    query: str,
    *,
    records: dict[str, SkillRecord],
    top_k: int,
    preferred_names: list[str] | None = None,
) -> list[SearchResult]:
    query_tokens = _tokenize_for_local_search(query)
    preferred = {name.lower() for name in preferred_names or []}
    results: list[SearchResult] = []
    for record in records.values():
        score = _local_keyword_score(query_tokens, record)
        lower_tool_name = record.tool_name.lower()
        lower_name = record.name.lower()
        if preferred and (
            lower_tool_name in preferred
            or lower_name in preferred
            or any(item in lower_tool_name or item in lower_name for item in preferred)
        ):
            score += 5.0
        if score <= 0:
            continue
        results.append(
            SearchResult(
                record=record,
                score=score,
                keyword_score=score,
                semantic_score=0.0,
                metadata={"retriever": "local_keyword_fallback"},
            )
        )
    return sorted(results, key=lambda item: (-item.score, item.record.tool_name))[:top_k]


def _render_generated_dynamic_skill(
    *,
    name: str,
    description: str,
    when_to_use: str,
    when_not_use: list[str],
    content: str,
    memory_uid: str,
) -> str:
    never_use = "\n".join(f"- {item}" for item in when_not_use) or "- 无"
    return "\n".join(
        [
            "---",
            f"name: {_frontmatter_value(name)}",
            f"description: {_frontmatter_value(description)}",
            "generated_by: long_term_memory",
            f"memory_uid: {memory_uid}",
            "---",
            "",
            f"# {name}",
            "",
            "## 适用场景",
            when_to_use,
            "",
            "## 不适用场景",
            never_use,
            "",
            "## 工作流",
            content.strip(),
            "",
        ]
    )


def _frontmatter_value(value: str) -> str:
    return " ".join(value.split()).replace(":", "-")


def _estimate_card_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _dynamic_skill_summary_hint(summary: str) -> str:
    return (
        "Dynamic Skill 能力摘要（仅用于判断是否值得检索，不代表这些 Skill 已加载或已执行）：\n"
        f"{summary}\n"
        "若用户需求可能属于摘要中的任一能力类别，先按检索规则调用 search_skill；"
        "若用户需求完全不在摘要覆盖范围内，可以不搜索 Skill，直接使用模型自身能力或 Core Tool 完成任务。"
        "只有摘要明确覆盖目标能力且多次 search_skill 未命中时，才允许调用 list_dynamic_skills。"
    )


def _local_keyword_score(query_tokens: list[str], record: SkillRecord) -> float:
    haystacks = [
        (record.tool_name.lower(), 4.0),
        (record.name.lower(), 4.0),
        (record.description.lower(), 3.0),
        (record.content.lower(), 1.0),
    ]
    score = 0.0
    for token in query_tokens:
        for text, weight in haystacks:
            if token in text:
                score += weight
    compact_query = "".join(query_tokens)
    if compact_query and compact_query in (record.name + record.description + record.content).lower():
        score += 6.0
    return score


def _tokenize_for_local_search(query: str) -> list[str]:
    normalized = query.lower().strip()
    tokens = TOKEN_RE.findall(normalized)
    if normalized:
        tokens.append(normalized)
    return list(dict.fromkeys(token for token in tokens if token.strip()))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _normalize_reference_path(reference_path: str) -> str | None:
    normalized = reference_path.strip().replace("\\", "/").lstrip("/")
    if not normalized:
        return None
    parts = [part for part in normalized.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        return None
    if not parts:
        return None
    if parts[0] != "references":
        parts.insert(0, "references")
    return "/".join(parts)


def _rank_references(
    *,
    query: str,
    references: list[SkillReferenceRecord],
    skill_tool_name: str,
    limit: int,
) -> list[tuple[SkillReferenceRecord, float]]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    scored: list[tuple[SkillReferenceRecord, float]] = []
    for reference in references:
        if skill_tool_name and reference.skill_tool_name != skill_tool_name:
            continue
        haystack_name = _tokens(
            " ".join([
                reference.skill_name,
                reference.skill_tool_name,
                reference.reference_path,
                reference.file_name,
            ])
        )
        haystack_content = _tokens(reference.content[:8000])
        name_score = _overlap(query_tokens, haystack_name)
        content_score = _overlap(query_tokens, haystack_content)
        score = (0.65 * name_score) + (0.35 * content_score)
        if score <= 0:
            continue
        scored.append((reference, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text)}


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left)


def _reference_snippet(content: str, query: str, limit: int = 240) -> str:
    compact = " ".join(content.split())
    if len(compact) <= limit:
        return compact
    query_tokens = sorted(_tokens(query), key=len, reverse=True)
    lower = compact.lower()
    start = 0
    for token in query_tokens:
        index = lower.find(token.lower())
        if index >= 0:
            start = max(0, index - 60)
            break
    snippet = compact[start : start + limit]
    if start > 0:
        snippet = "..." + snippet
    if start + limit < len(compact):
        snippet += "..."
    return snippet
