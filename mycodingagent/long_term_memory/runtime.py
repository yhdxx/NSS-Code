from __future__ import annotations

import asyncio
import json
import re
from time import time
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI

from mycodingagent.configuration import CONFIG
from mycodingagent.long_term_memory.models import ExtractionResult, LongTermMemoryContext, MemoryType
from mycodingagent.long_term_memory.query_model import LongTermMemoryQueryModel
from mycodingagent.long_term_memory.session_serializer import (
    build_storage_payload,
    recent_user_assistant_messages,
    session_source_hash,
)
from mycodingagent.long_term_memory.storage_model import LongTermMemoryStorageModel
from mycodingagent.long_term_memory.store import SQLiteLongTermMemoryStore
from mycodingagent.memory import MemoryRuntime
from mycodingagent.tool_runtime import ToolRegistry


USES_MEMORY_RE = re.compile(r"uses_memory_uid=([A-Za-z0-9_.:-]+)")


class LongTermMemoryRuntime:
    def __init__(
        self,
        *,
        memory_runtime: MemoryRuntime,
        registry: ToolRegistry,
        api_client: AsyncOpenAI,
        user_id: str,
        storage_model: str,
        query_model: str,
        store: SQLiteLongTermMemoryStore | None = None,
    ) -> None:
        self.memory_runtime = memory_runtime
        self.registry = registry
        self.api_client = api_client
        self.user_id = user_id
        self.store = store or SQLiteLongTermMemoryStore(CONFIG.memory.db_path)
        self.storage_model = LongTermMemoryStorageModel(api_client=api_client, model=storage_model)
        self.query_model = LongTermMemoryQueryModel(api_client=api_client, model=query_model)
        self._backfill_task: asyncio.Task | None = None
        self._last_context_by_session: dict[str, LongTermMemoryContext] = {}

    def schedule_startup_backfill(self) -> None:
        if not CONFIG.long_term_memory.enabled or not CONFIG.long_term_memory.startup_backfill_enabled:
            return
        if self._backfill_task is not None and not self._backfill_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self.store.requeue_interrupted_extractions_for_startup(limit=100)
        self._backfill_task = loop.create_task(self._run_backfill())

    async def close(self) -> None:
        if self._backfill_task is not None:
            self._backfill_task.cancel()
            try:
                await self._backfill_task
            except asyncio.CancelledError:
                pass
        self._backfill_task = None

    def mark_session_pending(self, session_id: str) -> str:
        state = self.memory_runtime.store.load_session(session_id)
        if state is None or not state.messages:
            return ""
        source_hash = session_source_hash(state.messages)
        return self.store.mark_extraction_pending(
            session_id=session_id,
            user_id=self.user_id,
            workspace_fingerprint=state.workspace_fingerprint or self.memory_runtime.workspace_fingerprint,
            workspace_label=state.workspace_label or self.memory_runtime.workspace_label,
            workspace_root=state.workspace_root or self.memory_runtime.workspace_root,
            source_hash=source_hash,
            source_message_count=len(state.messages),
        )

    async def extract_session_now(
        self,
        session_id: str,
        *,
        timeout_seconds: int | None = None,
    ) -> ExtractionResult:
        extraction_id = self.mark_session_pending(session_id)
        if not extraction_id:
            return ExtractionResult(status="skipped", error="empty or missing session")
        coroutine = self._extract_by_id(extraction_id)
        if timeout_seconds is None:
            return await coroutine
        try:
            return await asyncio.wait_for(coroutine, timeout=max(1, timeout_seconds))
        except asyncio.TimeoutError:
            return ExtractionResult(status="timeout", extraction_id=extraction_id, error="extraction timed out")

    async def retrieve_for_turn(
        self,
        *,
        current_query: str,
        recent_messages: list[dict[str, Any]],
    ) -> LongTermMemoryContext | None:
        if not CONFIG.long_term_memory.enabled:
            return None
        session_id = self.memory_runtime.get_current_session_id() or ""
        version = self.store.latest_committed_version(
            user_id=self.user_id,
            workspace_fingerprint=self.memory_runtime.workspace_fingerprint,
        )
        if version is None:
            self._last_context_by_session.pop(session_id, None)
            return None
        items = self.store.load_items(version.version_id, active_only=True)
        if not items:
            self._last_context_by_session.pop(session_id, None)
            return None
        try:
            context = await self.query_model.select(
                current_query=current_query,
                recent_messages=recent_user_assistant_messages(
                    recent_messages,
                    max_turns=CONFIG.long_term_memory.query_recent_turns,
                ),
                version_id=version.version_id,
                items=items,
                workspace={
                    "workspace_root": self.memory_runtime.workspace_root,
                    "workspace_label": self.memory_runtime.workspace_label,
                    "workspace_fingerprint": self.memory_runtime.workspace_fingerprint,
                },
            )
        except Exception:
            context = None
        if session_id and context is not None:
            self._last_context_by_session[session_id] = context
        elif session_id:
            self._last_context_by_session.pop(session_id, None)
        return context

    def record_turn_usage_and_maybe_prompt_skill_promotion(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        turn_start_index: int,
        success: bool,
    ) -> None:
        context = self._last_context_by_session.pop(session_id, None)
        if context is None:
            return
        exposed_workflow = [item.memory_uid for item in context.workflow_candidates]
        exposed_skill = [item.memory_uid for item in context.skill_candidates]
        used_skill = sorted(set(exposed_skill) & _extract_used_memory_uids(messages[turn_start_index:]))
        self.store.record_turn_usage(
            session_id=session_id,
            turn_start_index=turn_start_index,
            turn_end_index=len(messages),
            version_id=context.version_id,
            exposed_workflow=exposed_workflow,
            exposed_skill=exposed_skill,
            used_skill=used_skill,
            success=success,
        )
        if not success:
            return
        for memory_uid in used_skill:
            if not self._should_prompt_skill_promotion(memory_uid):
                continue
            decision = _confirm_skill_promotion(memory_uid)
            self.store.record_turn_usage(
                session_id=session_id,
                turn_start_index=turn_start_index,
                turn_end_index=len(messages),
                version_id=context.version_id,
                exposed_workflow=[],
                exposed_skill=[memory_uid],
                used_skill=[memory_uid],
                success=True,
                prompted={"memory_uid": memory_uid, "decision": decision},
            )
            self._mark_skill_promotion_decision(memory_uid, decision)

    async def _run_backfill(self) -> None:
        jobs = self.store.list_claimable_extractions(
            limit=20,
            lock_ttl_seconds=CONFIG.long_term_memory.lock_ttl_seconds,
        )
        for job in jobs:
            await self._extract_by_id(job.extraction_id)

    async def _extract_by_id(self, extraction_id: str) -> ExtractionResult:
        job = self.store.claim_extraction(
            extraction_id,
            lock_ttl_seconds=CONFIG.long_term_memory.lock_ttl_seconds,
        )
        if job is None:
            return ExtractionResult(status="skipped", extraction_id=extraction_id, error="extraction is locked")
        owner_id = uuid4().hex
        if not self.store.acquire_write_lock(
            user_id=job.user_id,
            workspace_fingerprint=job.workspace_fingerprint,
            owner_id=owner_id,
            ttl_seconds=CONFIG.long_term_memory.lock_ttl_seconds,
        ):
            self.store.mark_extraction_failed(extraction_id, "memory write lock is held")
            return ExtractionResult(status="failed", extraction_id=extraction_id, error="memory write lock is held")
        try:
            result = await self._extract_claimed_job(job)
            return result
        except Exception as exc:
            self.store.mark_extraction_failed(extraction_id, str(exc))
            return ExtractionResult(status="failed", extraction_id=extraction_id, error=str(exc))
        finally:
            self.store.release_write_lock(
                user_id=job.user_id,
                workspace_fingerprint=job.workspace_fingerprint,
                owner_id=owner_id,
            )

    async def _extract_claimed_job(self, job: Any) -> ExtractionResult:
        state = self.memory_runtime.store.load_session(job.session_id)
        if state is None:
            raise ValueError(f"session not found: {job.session_id}")
        latest = self.store.latest_committed_version(
            user_id=job.user_id,
            workspace_fingerprint=job.workspace_fingerprint,
        )
        existing_items = self.store.load_items(latest.version_id, active_only=True) if latest is not None else []
        payload = build_storage_payload(
            session_state=state,
            tool_registry=self.registry,
            existing_memories=[_item_for_storage(item) for item in existing_items],
            extraction_id=job.extraction_id,
        )
        patch = await self.storage_model.extract_patch(payload)
        version_id = self.store.apply_patch_as_new_version(
            user_id=job.user_id,
            workspace_fingerprint=job.workspace_fingerprint,
            workspace_label=job.workspace_label,
            source_session_id=job.session_id,
            parent_version_id=latest.version_id if latest is not None else "",
            existing_items=existing_items,
            new_items=list(patch.get("new_items", [])),
            update_items=list(patch.get("update_items", [])),
            retire_items=list(patch.get("retire_items", [])),
            extraction_id=job.extraction_id,
        )
        return ExtractionResult(status="committed", extraction_id=job.extraction_id, version_id=version_id)

    def _should_prompt_skill_promotion(self, memory_uid: str) -> bool:
        if self.store.successful_skill_reuse_count(memory_uid) < CONFIG.long_term_memory.skill_candidate_success_threshold:
            return False
        last_prompted_at = self.store.last_skill_prompt_at(memory_uid)
        cooldown = CONFIG.long_term_memory.skill_candidate_prompt_cooldown_days * 24 * 60 * 60
        return not last_prompted_at or (time() - last_prompted_at) >= cooldown

    def _mark_skill_promotion_decision(self, memory_uid: str, decision: str) -> None:
        owner_id = uuid4().hex
        if not self.store.acquire_write_lock(
            user_id=self.user_id,
            workspace_fingerprint=self.memory_runtime.workspace_fingerprint,
            owner_id=owner_id,
            ttl_seconds=CONFIG.long_term_memory.lock_ttl_seconds,
        ):
            return
        try:
            self.store.mark_skill_candidate_promotion_status(
                user_id=self.user_id,
                workspace_fingerprint=self.memory_runtime.workspace_fingerprint,
                memory_uid=memory_uid,
                decision=decision,
            )
        finally:
            self.store.release_write_lock(
                user_id=self.user_id,
                workspace_fingerprint=self.memory_runtime.workspace_fingerprint,
                owner_id=owner_id,
            )


def _item_for_storage(item: Any) -> dict[str, Any]:
    return {
        "memory_uid": item.memory_uid,
        "type": item.memory_type.value,
        "scope": item.scope.value,
        "content": item.content,
        "confidence": item.confidence,
        "evidence": item.evidence,
        "metadata": item.metadata,
    }


def _extract_used_memory_uids(messages: list[dict[str, Any]]) -> set[str]:
    text = json.dumps(messages, ensure_ascii=False, default=str)
    return set(USES_MEMORY_RE.findall(text))


def _confirm_skill_promotion(memory_uid: str) -> str:
    print(f"检测到长期流程候选已成功复用：{memory_uid}", flush=True)
    answer = input("是否将该流程标记为可沉淀 Skill？输入 y 确认，其它任意键跳过：").strip().lower()
    return "approved_for_skill" if answer in {"y", "yes"} else "declined"
