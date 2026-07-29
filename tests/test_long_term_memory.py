from __future__ import annotations

import json
from pathlib import Path

from mycodingagent.long_term_memory.models import (
    ExtractionStatus,
    LongTermMemoryContext,
    LongTermMemoryItem,
    MemoryItemStatus,
    MemoryScope,
    MemoryType,
)
from mycodingagent.long_term_memory.namespaces import GLOBAL_WORKSPACE_FINGERPRINT, WORKFLOW_STAGING_FINGERPRINT
from mycodingagent.long_term_memory.session_serializer import build_storage_payload, session_source_hash
from mycodingagent.long_term_memory.store import SQLiteLongTermMemoryStore
from mycodingagent.long_term_memory.tools import SubmitLongTermMemoryPatch, SubmitLongTermMemoryQueryResult
from mycodingagent.memory.models import SessionState


def test_session_serializer_omits_tool_output_but_keeps_call_intent():
    messages = [
        {"role": "system", "content": "hidden"},
        {"role": "user", "content": "do work"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "ReadFile",
                        "arguments": json.dumps({"file_path": "app.py", "intent": "read app"}),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "VERY LARGE SECRET TOOL OUTPUT",
            "metadata": {"tool_name": "ReadFile", "intent": "read app"},
        },
        {"role": "assistant", "content": "done"},
    ]
    state = SessionState(
        session_id="s1",
        messages=messages,
        workspace_root="/repo",
        workspace_label="repo",
        workspace_fingerprint="wf",
    )

    payload = build_storage_payload(
        session_state=state,
        tool_registry=None,
        existing_memories=[],
        extraction_id="e1",
    )
    text = json.dumps(payload, ensure_ascii=False)

    assert "VERY LARGE SECRET TOOL OUTPUT" not in text
    assert '"output_omitted": true' in text
    assert '"intent": "read app"' in text
    assert payload["tool_catalog"] == []
    assert session_source_hash(messages) == session_source_hash(messages)


def test_store_uses_staging_commit_and_latest_committed_version(tmp_path: Path):
    store = SQLiteLongTermMemoryStore(tmp_path / "memory.sqlite3")

    extraction_id = store.mark_extraction_pending(
        session_id="s1",
        user_id="u1",
        workspace_fingerprint="wf",
        workspace_label="repo",
        workspace_root="/repo",
        source_hash="hash1",
        source_message_count=2,
    )
    claimed = store.claim_extraction(extraction_id, lock_ttl_seconds=60)
    assert claimed is not None

    version_id = store.apply_patch_as_new_version(
        user_id="u1",
        workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT,
        workspace_label="User Global Memory",
        source_session_id="s1",
        parent_version_id="",
        existing_items=[],
        new_items=[
            {
                "memory_type": "user_preference",
                "scope": "user",
                "content": "Prefers precise plans.",
                "confidence": 0.9,
                "evidence": ["message:1"],
                "metadata": {},
            }
        ],
        update_items=[],
        retire_items=[],
        extraction_id=extraction_id,
    )

    latest = store.latest_committed_version(user_id="u1", workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT)
    assert latest is not None
    assert latest.version_id == version_id
    items = store.load_items(version_id)
    assert len(items) == 1
    assert items[0].memory_type == MemoryType.USER_PREFERENCE
    assert items[0].status == MemoryItemStatus.ACTIVE


def test_write_lock_blocks_second_owner_until_expired(tmp_path: Path):
    store = SQLiteLongTermMemoryStore(tmp_path / "memory.sqlite3")

    assert store.acquire_write_lock(user_id="u1", workspace_fingerprint="wf", owner_id="a", ttl_seconds=60)
    assert not store.acquire_write_lock(user_id="u1", workspace_fingerprint="wf", owner_id="b", ttl_seconds=60)
    store.release_write_lock(user_id="u1", workspace_fingerprint="wf", owner_id="a")
    assert store.acquire_write_lock(user_id="u1", workspace_fingerprint="wf", owner_id="b", ttl_seconds=60)


def test_startup_requeues_interrupted_extracting_jobs_without_waiting_for_ttl(tmp_path: Path):
    store = SQLiteLongTermMemoryStore(tmp_path / "memory.sqlite3")
    extraction_id = store.mark_extraction_pending(
        session_id="s1",
        user_id="u1",
        workspace_fingerprint="wf",
        workspace_label="repo",
        workspace_root="/repo",
        source_hash="hash1",
        source_message_count=2,
    )
    claimed = store.claim_extraction(extraction_id, lock_ttl_seconds=3600)
    assert claimed is not None
    assert claimed.status == ExtractionStatus.EXTRACTING
    assert store.list_claimable_extractions(limit=10, lock_ttl_seconds=3600) == []

    assert store.requeue_interrupted_extractions_for_startup() == 1

    claimable = store.list_claimable_extractions(limit=10, lock_ttl_seconds=3600)
    assert [job.extraction_id for job in claimable] == [extraction_id]
    assert claimable[0].status == ExtractionStatus.PENDING


def test_startup_does_not_requeue_extracting_job_with_active_write_lock(tmp_path: Path):
    store = SQLiteLongTermMemoryStore(tmp_path / "memory.sqlite3")
    extraction_id = store.mark_extraction_pending(
        session_id="s1",
        user_id="u1",
        workspace_fingerprint="wf",
        workspace_label="repo",
        workspace_root="/repo",
        source_hash="hash1",
        source_message_count=2,
    )
    store.claim_extraction(extraction_id, lock_ttl_seconds=3600)
    assert store.acquire_write_lock(user_id="u1", workspace_fingerprint="wf", owner_id="owner", ttl_seconds=60)

    assert store.requeue_interrupted_extractions_for_startup() == 0
    assert store.list_claimable_extractions(limit=10, lock_ttl_seconds=3600) == []


def test_startup_does_not_requeue_extracting_job_with_global_or_workflow_lock(tmp_path: Path):
    store = SQLiteLongTermMemoryStore(tmp_path / "memory.sqlite3")
    extraction_id = store.mark_extraction_pending(
        session_id="s1",
        user_id="u1",
        workspace_fingerprint="wf",
        workspace_label="repo",
        workspace_root="/repo",
        source_hash="hash1",
        source_message_count=2,
    )
    store.claim_extraction(extraction_id, lock_ttl_seconds=3600)
    assert store.acquire_write_lock(
        user_id="u1",
        workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT,
        owner_id="owner",
        ttl_seconds=60,
    )

    assert store.requeue_interrupted_extractions_for_startup() == 0
    assert store.list_claimable_extractions(limit=10, lock_ttl_seconds=3600) == []


def test_skill_candidate_promotion_status_creates_new_version(tmp_path: Path):
    store = SQLiteLongTermMemoryStore(tmp_path / "memory.sqlite3")
    extraction_id = store.mark_extraction_pending(
        session_id="s1",
        user_id="u1",
        workspace_fingerprint="wf",
        workspace_label="repo",
        workspace_root="/repo",
        source_hash="hash1",
        source_message_count=2,
    )
    store.claim_extraction(extraction_id, lock_ttl_seconds=60)
    version_id = store.apply_patch_as_new_version(
        user_id="u1",
        workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT,
        workspace_label="User Global Memory",
        source_session_id="s1",
        parent_version_id="",
        existing_items=[],
        new_items=[
            {
                "memory_type": "skill_candidate",
                "scope": "user",
                "content": "Use batch extraction for large file splits.",
                "confidence": 0.9,
                "evidence": ["message:1"],
                "metadata": {},
            }
        ],
        update_items=[],
        retire_items=[],
        extraction_id=extraction_id,
    )
    memory_uid = store.load_items(version_id)[0].memory_uid

    promoted_version = store.mark_skill_candidate_promotion_status(
        user_id="u1",
        workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT,
        memory_uid=memory_uid,
        decision="approved_for_skill",
    )

    assert promoted_version
    latest = store.latest_committed_version(user_id="u1", workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT)
    assert latest is not None
    assert latest.version_id == promoted_version
    promoted_item = store.load_items(promoted_version)[0]
    assert promoted_item.metadata["promotion_status"] == "approved_for_skill"


def test_workflow_candidate_promotes_after_three_other_workspace_uses(tmp_path: Path):
    store = SQLiteLongTermMemoryStore(tmp_path / "memory.sqlite3")
    workflow_uid = _create_workflow_candidate(store, origin_workspace="origin")

    for workspace in ["other-1", "other-2", "other-3"]:
        store.update_workflow_observation(
            user_id="u1",
            memory_uid=workflow_uid,
            current_workspace_fingerprint=workspace,
            current_workspace_label=workspace,
            used_successfully=True,
            promotion_workspace_threshold=3,
            downgrade_workspace_threshold=3,
        )

    staging_latest = store.latest_committed_version(user_id="u1", workspace_fingerprint=WORKFLOW_STAGING_FINGERPRINT)
    assert staging_latest is not None
    retired = store.load_items(staging_latest.version_id, active_only=False)[0]
    assert retired.status == MemoryItemStatus.RETIRED

    global_latest = store.latest_committed_version(user_id="u1", workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT)
    assert global_latest is not None
    global_items = store.load_items(global_latest.version_id)
    assert len(global_items) == 1
    assert global_items[0].memory_type == MemoryType.SKILL_CANDIDATE
    assert global_items[0].metadata["lifecycle_status"] == "promoted_to_skill_candidate"


def test_workflow_candidate_downgrades_after_three_other_workspace_non_uses(tmp_path: Path):
    store = SQLiteLongTermMemoryStore(tmp_path / "memory.sqlite3")
    workflow_uid = _create_workflow_candidate(store, origin_workspace="origin")

    for workspace in ["other-1", "other-2", "other-3"]:
        store.update_workflow_observation(
            user_id="u1",
            memory_uid=workflow_uid,
            current_workspace_fingerprint=workspace,
            current_workspace_label=workspace,
            used_successfully=False,
            promotion_workspace_threshold=3,
            downgrade_workspace_threshold=3,
        )

    staging_latest = store.latest_committed_version(user_id="u1", workspace_fingerprint=WORKFLOW_STAGING_FINGERPRINT)
    assert staging_latest is not None
    retired = store.load_items(staging_latest.version_id, active_only=False)[0]
    assert retired.status == MemoryItemStatus.RETIRED

    origin_latest = store.latest_committed_version(user_id="u1", workspace_fingerprint="origin")
    assert origin_latest is not None
    origin_items = store.load_items(origin_latest.version_id)
    assert len(origin_items) == 1
    assert origin_items[0].memory_type == MemoryType.WORKFLOW_CANDIDATE
    assert origin_items[0].metadata["lifecycle_status"] == "workspace_only"


def test_long_term_memory_runtime_payload_uses_single_memory_field_for_empty_context():
    payload = LongTermMemoryContext(version_id="", query_id="q1").to_runtime_payload()

    assert payload == {"memory": "未查询到相关记忆"}


def test_long_term_memory_runtime_payload_concatenates_relevant_sections_only():
    workflow = LongTermMemoryItem(
        memory_uid="wf1",
        version_id="v1",
        memory_type=MemoryType.WORKFLOW_CANDIDATE,
        scope=MemoryScope.WORKSPACE,
        content="大文件拆分时先一次性定位边界，再批量写入。",
        confidence=0.9,
    )
    skill = LongTermMemoryItem(
        memory_uid="sk1",
        version_id="v1",
        memory_type=MemoryType.SKILL_CANDIDATE,
        scope=MemoryScope.USER,
        content="跨模块重构先跑现有测试，再改公共接口。",
        confidence=0.9,
    )
    context = LongTermMemoryContext(
        version_id="v1",
        query_id="q1",
        memories=[
            LongTermMemoryItem(
                memory_uid="u1",
                version_id="v1",
                memory_type=MemoryType.USER_PROFILE,
                scope=MemoryScope.USER,
                content="用户是 myCodingAgent 开发者。",
                confidence=0.9,
            ),
            LongTermMemoryItem(
                memory_uid="p1",
                version_id="v1",
                memory_type=MemoryType.USER_PREFERENCE,
                scope=MemoryScope.USER,
                content="偏好精简、无冗余字段的 Runtime Context。",
                confidence=0.9,
            ),
            LongTermMemoryItem(
                memory_uid="pf1",
                version_id="v1",
                memory_type=MemoryType.PROJECT_FACT,
                scope=MemoryScope.PROJECT,
                content="项目采用 LLM Runtime、Tool Runtime、Memory 分层架构。",
                confidence=0.9,
            ),
            LongTermMemoryItem(
                memory_uid="d1",
                version_id="v1",
                memory_type=MemoryType.DECISION,
                scope=MemoryScope.WORKSPACE,
                content="该类型不应注入主 Agent 长期记忆字段。",
                confidence=0.9,
            ),
        ],
        workflow_candidates=[workflow],
        skill_candidates=[skill],
    )

    payload = context.to_runtime_payload()

    assert set(payload.keys()) == {"memory"}
    memory = payload["memory"]
    assert "用户画像：" in memory
    assert "- 用户是 myCodingAgent 开发者。" in memory
    assert "用户偏好：" in memory
    assert "- 偏好精简、无冗余字段的 Runtime Context。" in memory
    assert "项目事实：" in memory
    assert "- 项目采用 LLM Runtime、Tool Runtime、Memory 分层架构。" in memory
    assert "可能相关的工作流：" in memory
    assert "uses_memory_uid=wf1" in memory
    assert "uses_memory_uid=sk1" in memory
    assert "该类型不应注入" not in memory
    assert "summary" not in payload
    assert "memories" not in payload
    assert "workflow_candidates" not in payload
    assert "skill_candidates" not in payload


def test_internal_submit_tools_expose_structured_parameters():
    patch_tool = SubmitLongTermMemoryPatch(extraction_id="e1", collector={})
    query_tool = SubmitLongTermMemoryQueryResult(query_id="q1", collector={})

    assert "new_items" not in patch_tool.get_schema()["input_schema"]["properties"]
    assert "user_profiles" in patch_tool.get_schema()["input_schema"]["properties"]
    assert "project_facts" in patch_tool.get_schema()["input_schema"]["properties"]
    assert "summary" not in query_tool.get_schema()["input_schema"]["properties"]
    assert "workflow_candidates" in query_tool.get_schema()["input_schema"]["properties"]
    assert "skill_candidates" in query_tool.get_schema()["input_schema"]["properties"]


def _create_workflow_candidate(store: SQLiteLongTermMemoryStore, *, origin_workspace: str) -> str:
    extraction_id = store.mark_extraction_pending(
        session_id="s-workflow",
        user_id="u1",
        workspace_fingerprint=origin_workspace,
        workspace_label=origin_workspace,
        workspace_root=f"/{origin_workspace}",
        source_hash=f"hash-{origin_workspace}",
        source_message_count=2,
    )
    store.claim_extraction(extraction_id, lock_ttl_seconds=60)
    version_id = store.apply_patch_as_new_version(
        user_id="u1",
        workspace_fingerprint=WORKFLOW_STAGING_FINGERPRINT,
        workspace_label="Workflow Staging Memory",
        source_session_id="s-workflow",
        parent_version_id="",
        existing_items=[],
        new_items=[
            {
                "memory_type": "workflow_candidate",
                "scope": "workspace",
                "content": "For large file splits, locate all boundaries once and write modules in batch.",
                "confidence": 0.9,
                "evidence": ["message:1"],
                "metadata": {
                    "origin_workspace_fingerprint": origin_workspace,
                    "origin_workspace_label": origin_workspace,
                },
            }
        ],
        update_items=[],
        retire_items=[],
        extraction_id=extraction_id,
    )
    return store.load_items(version_id)[0].memory_uid
