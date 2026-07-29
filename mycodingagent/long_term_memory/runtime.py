from __future__ import annotations

import asyncio
import json
import re
from time import time
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI

from mycodingagent.configuration import CONFIG
from mycodingagent.long_term_memory.models import ExtractionResult, LongTermMemoryContext, MemoryScope, MemoryType
from mycodingagent.long_term_memory.namespaces import (
    GLOBAL_WORKSPACE_FINGERPRINT,
    GLOBAL_WORKSPACE_LABEL,
    WORKFLOW_STAGING_FINGERPRINT,
    WORKFLOW_STAGING_LABEL,
    default_scope_for_type,
    label_for_namespace,
    namespace_for_bucket,
    type_for_bucket,
)
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
        global_version, global_items = self.store.load_latest_active_items(
            user_id=self.user_id,
            workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT,
        )
        workflow_version, workflow_items = self.store.load_latest_active_items(
            user_id=self.user_id,
            workspace_fingerprint=WORKFLOW_STAGING_FINGERPRINT,
        )
        workspace_version, workspace_items = self.store.load_latest_active_items(
            user_id=self.user_id,
            workspace_fingerprint=self.memory_runtime.workspace_fingerprint,
        )
        items = [*global_items, *workflow_items, *workspace_items]
        if not items:
            self._last_context_by_session.pop(session_id, None)
            return LongTermMemoryContext(version_id="", query_id="")
        version_id = "|".join(
            version.version_id
            for version in (global_version, workflow_version, workspace_version)
            if version is not None
        )
        try:
            context = await self.query_model.select(
                current_query=current_query,
                recent_messages=recent_user_assistant_messages(
                    recent_messages,
                    max_turns=CONFIG.long_term_memory.query_recent_turns,
                ),
                version_id=version_id,
                items=items,
                workspace={
                    "workspace_root": self.memory_runtime.workspace_root,
                    "workspace_label": self.memory_runtime.workspace_label,
                    "workspace_fingerprint": self.memory_runtime.workspace_fingerprint,
                },
                project_fact_search={
                    "store": self.store,
                    "user_id": self.user_id,
                    "current_workspace_fingerprint": self.memory_runtime.workspace_fingerprint,
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
        used_memory = _extract_used_memory_uids(messages[turn_start_index:])
        used_workflow = sorted(set(exposed_workflow) & used_memory)
        used_skill = sorted(set(exposed_skill) & used_memory)
        self.store.record_turn_usage(
            session_id=session_id,
            turn_start_index=turn_start_index,
            turn_end_index=len(messages),
            version_id=context.version_id,
            exposed_workflow=exposed_workflow,
            exposed_skill=exposed_skill,
            used_workflow=used_workflow,
            used_skill=used_skill,
            success=success,
        )
        for memory_uid in exposed_workflow:
            self.store.update_workflow_observation(
                user_id=self.user_id,
                memory_uid=memory_uid,
                current_workspace_fingerprint=self.memory_runtime.workspace_fingerprint,
                current_workspace_label=self.memory_runtime.workspace_label,
                used_successfully=success and memory_uid in used_workflow,
                promotion_workspace_threshold=3,
                downgrade_workspace_threshold=3,
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
                used_workflow=[],
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
        lock_namespaces = [
            GLOBAL_WORKSPACE_FINGERPRINT,
            WORKFLOW_STAGING_FINGERPRINT,
            job.workspace_fingerprint,
        ]
        acquired: list[str] = []
        for namespace in dict.fromkeys(lock_namespaces):
            if not self.store.acquire_write_lock(
                user_id=job.user_id,
                workspace_fingerprint=namespace,
                owner_id=owner_id,
                ttl_seconds=CONFIG.long_term_memory.lock_ttl_seconds,
            ):
                for acquired_namespace in acquired:
                    self.store.release_write_lock(
                        user_id=job.user_id,
                        workspace_fingerprint=acquired_namespace,
                        owner_id=owner_id,
                    )
                self.store.mark_extraction_failed(extraction_id, "memory write lock is held")
                return ExtractionResult(status="failed", extraction_id=extraction_id, error="memory write lock is held")
            acquired.append(namespace)
        try:
            result = await self._extract_claimed_job(job)
            return result
        except Exception as exc:
            self.store.mark_extraction_failed(extraction_id, str(exc))
            return ExtractionResult(status="failed", extraction_id=extraction_id, error=str(exc))
        finally:
            for namespace in acquired:
                self.store.release_write_lock(
                    user_id=job.user_id,
                    workspace_fingerprint=namespace,
                    owner_id=owner_id,
                )

    async def _extract_claimed_job(self, job: Any) -> ExtractionResult:
        state = self.memory_runtime.store.load_session(job.session_id)
        if state is None:
            raise ValueError(f"session not found: {job.session_id}")
        global_latest, global_items = self.store.load_latest_active_items(
            user_id=job.user_id,
            workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT,
        )
        workflow_latest, workflow_items = self.store.load_latest_active_items(
            user_id=job.user_id,
            workspace_fingerprint=WORKFLOW_STAGING_FINGERPRINT,
        )
        workspace_latest, workspace_items = self.store.load_latest_active_items(
            user_id=job.user_id,
            workspace_fingerprint=job.workspace_fingerprint,
        )
        payload = build_storage_payload(
            session_state=state,
            tool_registry=self.registry,
            existing_memories=[
                _item_for_storage(item)
                for item in [*global_items, *workflow_items, *workspace_items]
            ],
            existing_global_memories=[_item_for_storage(item) for item in global_items],
            existing_workflow_staging_memories=[_item_for_storage(item) for item in workflow_items],
            existing_workspace_memories=[_item_for_storage(item) for item in workspace_items],
            extraction_id=job.extraction_id,
        )
        patch = await self.storage_model.extract_patch(payload)
        namespace_existing = {
            GLOBAL_WORKSPACE_FINGERPRINT: (global_latest, global_items),
            WORKFLOW_STAGING_FINGERPRINT: (workflow_latest, workflow_items),
            job.workspace_fingerprint: (workspace_latest, workspace_items),
        }
        patches = _patch_by_namespace(
            patch=patch,
            current_workspace_fingerprint=job.workspace_fingerprint,
            current_workspace_label=job.workspace_label,
            existing_by_namespace={namespace: items for namespace, (_version, items) in namespace_existing.items()},
        )
        version_ids: dict[str, str] = {}
        for namespace, namespace_patch in patches.items():
            latest, existing_items = namespace_existing.get(namespace, (None, []))
            version_id = self.store.apply_patch_as_new_version(
                user_id=job.user_id,
                workspace_fingerprint=namespace,
                workspace_label=label_for_namespace(namespace, job.workspace_label),
                source_session_id=job.session_id,
                parent_version_id=latest.version_id if latest is not None else "",
                existing_items=existing_items,
                new_items=namespace_patch["new_items"],
                update_items=namespace_patch["update_items"],
                retire_items=namespace_patch["retire_items"],
                extraction_id=job.extraction_id,
            )
            version_ids[namespace] = version_id
        if not version_ids:
            self.store.mark_extraction_committed(job.extraction_id, "")
        preferred_version_id = (
            version_ids.get(job.workspace_fingerprint)
            or version_ids.get(GLOBAL_WORKSPACE_FINGERPRINT)
            or version_ids.get(WORKFLOW_STAGING_FINGERPRINT)
            or ""
        )
        return ExtractionResult(
            status="committed",
            extraction_id=job.extraction_id,
            version_id=preferred_version_id,
            version_ids=version_ids,
        )

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
            workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT,
            owner_id=owner_id,
            ttl_seconds=CONFIG.long_term_memory.lock_ttl_seconds,
        ):
            return
        try:
            self.store.mark_skill_candidate_promotion_status(
                user_id=self.user_id,
                workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT,
                memory_uid=memory_uid,
                decision=decision,
            )
        finally:
            self.store.release_write_lock(
                user_id=self.user_id,
                workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT,
                owner_id=owner_id,
            )


def _item_for_storage(item: Any) -> dict[str, Any]:
    payload = {
        "memory_uid": item.memory_uid,
        "type": item.memory_type.value,
        "scope": item.scope.value,
        "content": item.content,
        "confidence": item.confidence,
        "evidence": item.evidence,
        "metadata": item.metadata,
    }
    if item.memory_type in {MemoryType.WORKFLOW_CANDIDATE, MemoryType.SKILL_CANDIDATE}:
        workflow = item.metadata.get("workflow") if isinstance(item.metadata, dict) else None
        if isinstance(workflow, dict):
            payload.update(
                {
                    "name": str(workflow.get("name", "")).strip(),
                    "description": str(workflow.get("description", "")).strip(),
                    "when_to_use": str(workflow.get("when_to_use", "")).strip(),
                    "when_not_use": [
                        str(value).strip()
                        for value in list(workflow.get("when_not_use", []) or [])
                        if str(value).strip()
                    ][:3],
                }
            )
    return payload


def _patch_by_namespace(
    *,
    patch: dict[str, Any],
    current_workspace_fingerprint: str,
    current_workspace_label: str,
    existing_by_namespace: dict[str, list[Any]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for bucket_name in ("user_profiles", "user_preferences", "project_facts", "workflows", "skill_candidates"):
        memory_type = type_for_bucket(bucket_name)
        namespace = namespace_for_bucket(bucket_name, current_workspace_fingerprint)
        for raw in list(patch.get(bucket_name, []) or []):
            if not isinstance(raw, dict):
                continue
            item = _new_item_from_bucket(
                raw,
                bucket_name=bucket_name,
                memory_type=memory_type,
                namespace=namespace,
                current_workspace_fingerprint=current_workspace_fingerprint,
                current_workspace_label=current_workspace_label,
            )
            _namespace_patch(result, namespace)["new_items"].append(item)

    uid_to_namespace = {
        item.memory_uid: namespace
        for namespace, items in existing_by_namespace.items()
        for item in items
    }
    for field in ("update_workflows", "update_skill_candidates"):
        for raw in list(patch.get(field, []) or []):
            if not isinstance(raw, dict):
                continue
            namespace = uid_to_namespace.get(str(raw.get("memory_uid", "")))
            if namespace is None:
                namespace = current_workspace_fingerprint
            memory_type = MemoryType(str(raw.get("memory_type")))
            item = _structured_workflow_item(
                raw,
                memory_type=memory_type,
                namespace=namespace,
            )
            _namespace_patch(result, namespace)["update_items"].append(item)

    for field in ("update_items", "retire_items"):
        for raw in list(patch.get(field, []) or []):
            if not isinstance(raw, dict):
                continue
            namespace = uid_to_namespace.get(str(raw.get("memory_uid", "")))
            if namespace is None:
                # Preserve validation semantics by sending unknown ids to workspace patch.
                namespace = current_workspace_fingerprint
            _namespace_patch(result, namespace)[field].append(dict(raw))

    return {
        namespace: namespace_patch
        for namespace, namespace_patch in result.items()
        if namespace_patch["new_items"] or namespace_patch["update_items"] or namespace_patch["retire_items"]
    }


def _new_item_from_bucket(
    raw: dict[str, Any],
    *,
    bucket_name: str,
    memory_type: MemoryType,
    namespace: str,
    current_workspace_fingerprint: str,
    current_workspace_label: str,
) -> dict[str, Any]:
    scope_value = raw.get("scope") or default_scope_for_type(memory_type).value
    metadata = dict(raw.get("metadata") or {})
    metadata["namespace"] = namespace
    if bucket_name in {"workflows", "skill_candidates"}:
        item = _structured_workflow_item(raw, memory_type=memory_type, namespace=namespace)
        if bucket_name == "workflows":
            item["metadata"].setdefault("origin_workspace_fingerprint", current_workspace_fingerprint)
            item["metadata"].setdefault("origin_workspace_label", current_workspace_label)
        return item
    return {
        "memory_type": memory_type.value,
        "scope": str(scope_value),
        "content": raw.get("content", ""),
        "confidence": raw.get("confidence", 0.0),
        "evidence": list(raw.get("evidence", []) or []),
        "metadata": metadata,
    }


def _structured_workflow_item(
    raw: dict[str, Any],
    *,
    memory_type: MemoryType,
    namespace: str,
) -> dict[str, Any]:
    if memory_type not in {MemoryType.WORKFLOW_CANDIDATE, MemoryType.SKILL_CANDIDATE}:
        raise ValueError(f"structured workflow item has invalid type: {memory_type.value}")
    when_not_use = [str(item).strip() for item in list(raw.get("when_not_use", []) or []) if str(item).strip()]
    if len(when_not_use) > 3:
        raise ValueError("workflow when_not_use cannot contain more than 3 items")
    metadata = dict(raw.get("metadata") or {})
    metadata["namespace"] = namespace
    metadata["workflow"] = {
        "name": str(raw.get("name", "")).strip(),
        "description": str(raw.get("description", "")).strip(),
        "when_to_use": str(raw.get("when_to_use", "")).strip(),
        "when_not_use": when_not_use,
    }
    return {
        "memory_uid": str(raw.get("memory_uid", "")),
        "memory_type": memory_type.value,
        "scope": str(raw.get("scope") or default_scope_for_type(memory_type).value),
        "content": raw.get("content", ""),
        "confidence": raw.get("confidence", 0.0),
        "evidence": list(raw.get("evidence", []) or []),
        "metadata": metadata,
    }


def _namespace_patch(result: dict[str, dict[str, list[dict[str, Any]]]], namespace: str) -> dict[str, list[dict[str, Any]]]:
    return result.setdefault(namespace, {"new_items": [], "update_items": [], "retire_items": []})


def _extract_used_memory_uids(messages: list[dict[str, Any]]) -> set[str]:
    text = json.dumps(messages, ensure_ascii=False, default=str)
    return set(USES_MEMORY_RE.findall(text))


def _confirm_skill_promotion(memory_uid: str) -> str:
    print(f"检测到长期流程候选已成功复用：{memory_uid}", flush=True)
    answer = input("是否将该流程标记为可沉淀 Skill？输入 y 确认，其它任意键跳过：").strip().lower()
    return "approved_for_skill" if answer in {"y", "yes"} else "declined"
