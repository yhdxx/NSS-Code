from __future__ import annotations

import json
from pathlib import Path

from mycodingagent.long_term_memory.models import MemoryItemStatus, MemoryType
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
        workspace_fingerprint="wf",
        workspace_label="repo",
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

    latest = store.latest_committed_version(user_id="u1", workspace_fingerprint="wf")
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
        workspace_fingerprint="wf",
        workspace_label="repo",
        source_session_id="s1",
        parent_version_id="",
        existing_items=[],
        new_items=[
            {
                "memory_type": "skill_candidate",
                "scope": "workspace",
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
        workspace_fingerprint="wf",
        memory_uid=memory_uid,
        decision="approved_for_skill",
    )

    assert promoted_version
    latest = store.latest_committed_version(user_id="u1", workspace_fingerprint="wf")
    assert latest is not None
    assert latest.version_id == promoted_version
    promoted_item = store.load_items(promoted_version)[0]
    assert promoted_item.metadata["promotion_status"] == "approved_for_skill"


def test_internal_submit_tools_expose_structured_parameters():
    patch_tool = SubmitLongTermMemoryPatch(extraction_id="e1", collector={})
    query_tool = SubmitLongTermMemoryQueryResult(query_id="q1", collector={})

    assert "new_items" in patch_tool.get_schema()["input_schema"]["properties"]
    assert "workflow_candidates" in query_tool.get_schema()["input_schema"]["properties"]
    assert "skill_candidates" in query_tool.get_schema()["input_schema"]["properties"]
