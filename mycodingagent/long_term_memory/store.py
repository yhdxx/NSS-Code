from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from time import time
from typing import Any
from uuid import uuid4

from mycodingagent.long_term_memory.models import (
    ExtractionJob,
    ExtractionStatus,
    LongTermMemoryItem,
    LongTermMemoryVersion,
    MemoryItemStatus,
    MemoryScope,
    MemoryType,
    MemoryVersionStatus,
)


class SQLiteLongTermMemoryStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS long_term_memory_versions (
                    version_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    workspace_fingerprint TEXT NOT NULL,
                    workspace_label TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    parent_version_id TEXT NOT NULL DEFAULT '',
                    source_session_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    committed_at REAL NOT NULL DEFAULT 0,
                    error_text TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS long_term_memory_items (
                    version_id TEXT NOT NULL,
                    memory_uid TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    content TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (version_id, memory_uid)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS long_term_memory_extractions (
                    extraction_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    workspace_fingerprint TEXT NOT NULL,
                    workspace_label TEXT NOT NULL DEFAULT '',
                    workspace_root TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    source_message_count INTEGER NOT NULL DEFAULT 0,
                    started_at REAL NOT NULL DEFAULT 0,
                    finished_at REAL NOT NULL DEFAULT 0,
                    error_text TEXT NOT NULL DEFAULT '',
                    committed_version_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(session_id, source_hash)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS long_term_memory_turn_usage (
                    usage_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_start_index INTEGER NOT NULL,
                    turn_end_index INTEGER NOT NULL,
                    version_id TEXT NOT NULL DEFAULT '',
                    exposed_workflow_json TEXT NOT NULL DEFAULT '[]',
                    exposed_skill_json TEXT NOT NULL DEFAULT '[]',
                    used_skill_json TEXT NOT NULL DEFAULT '[]',
                    success INTEGER NOT NULL DEFAULT 0,
                    prompted_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS long_term_memory_locks (
                    lock_key TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    acquired_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ltm_versions_lookup "
                "ON long_term_memory_versions(user_id, workspace_fingerprint, status, committed_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ltm_items_version_type "
                "ON long_term_memory_items(version_id, memory_type, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ltm_extractions_status "
                "ON long_term_memory_extractions(status, updated_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ltm_usage_session "
                "ON long_term_memory_turn_usage(session_id, created_at)"
            )

    def latest_committed_version(self, *, user_id: str, workspace_fingerprint: str) -> LongTermMemoryVersion | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM long_term_memory_versions
                WHERE user_id = ? AND workspace_fingerprint = ? AND status = ?
                ORDER BY committed_at DESC, created_at DESC
                LIMIT 1
                """,
                (user_id, workspace_fingerprint, MemoryVersionStatus.COMMITTED.value),
            ).fetchone()
        return _version_from_row(row) if row is not None else None

    def load_items(self, version_id: str, *, active_only: bool = True) -> list[LongTermMemoryItem]:
        query = "SELECT * FROM long_term_memory_items WHERE version_id = ?"
        params: list[Any] = [version_id]
        if active_only:
            query += " AND status = ?"
            params.append(MemoryItemStatus.ACTIVE.value)
        query += " ORDER BY memory_type, updated_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [_item_from_row(row) for row in rows]

    def mark_extraction_pending(
        self,
        *,
        session_id: str,
        user_id: str,
        workspace_fingerprint: str,
        workspace_label: str,
        workspace_root: str,
        source_hash: str,
        source_message_count: int,
    ) -> str:
        now = time()
        extraction_id = uuid4().hex
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO long_term_memory_extractions(
                    extraction_id, session_id, user_id, workspace_fingerprint, workspace_label,
                    workspace_root, status, source_hash, source_message_count, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extraction_id,
                    session_id,
                    user_id,
                    workspace_fingerprint,
                    workspace_label,
                    workspace_root,
                    ExtractionStatus.PENDING.value,
                    source_hash,
                    source_message_count,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT extraction_id FROM long_term_memory_extractions
                WHERE session_id = ? AND source_hash = ?
                """,
                (session_id, source_hash),
            ).fetchone()
        return str(row["extraction_id"]) if row is not None else extraction_id

    def claim_extraction(self, extraction_id: str, *, lock_ttl_seconds: int) -> ExtractionJob | None:
        now = time()
        stale_before = now - max(1, lock_ttl_seconds)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE long_term_memory_extractions
                SET status = ?, started_at = ?, updated_at = ?, error_text = ''
                WHERE extraction_id = ?
                  AND (
                    status IN (?, ?)
                    OR (status = ? AND started_at < ?)
                  )
                """,
                (
                    ExtractionStatus.EXTRACTING.value,
                    now,
                    now,
                    extraction_id,
                    ExtractionStatus.PENDING.value,
                    ExtractionStatus.FAILED.value,
                    ExtractionStatus.EXTRACTING.value,
                    stale_before,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM long_term_memory_extractions WHERE extraction_id = ?",
                (extraction_id,),
            ).fetchone()
        return _extraction_from_row(row) if row is not None else None

    def list_claimable_extractions(self, *, limit: int, lock_ttl_seconds: int) -> list[ExtractionJob]:
        now = time()
        stale_before = now - max(1, lock_ttl_seconds)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM long_term_memory_extractions
                WHERE status IN (?, ?)
                   OR (status = ? AND started_at < ?)
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (
                    ExtractionStatus.PENDING.value,
                    ExtractionStatus.FAILED.value,
                    ExtractionStatus.EXTRACTING.value,
                    stale_before,
                    limit,
                ),
            ).fetchall()
        return [_extraction_from_row(row) for row in rows]

    def mark_extraction_failed(self, extraction_id: str, error_text: str) -> None:
        now = time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE long_term_memory_extractions
                SET status = ?, error_text = ?, finished_at = ?, updated_at = ?
                WHERE extraction_id = ?
                """,
                (ExtractionStatus.FAILED.value, error_text[:4000], now, now, extraction_id),
            )

    def acquire_write_lock(self, *, user_id: str, workspace_fingerprint: str, owner_id: str, ttl_seconds: int) -> bool:
        lock_key = self.lock_key(user_id=user_id, workspace_fingerprint=workspace_fingerprint)
        now = time()
        expires_at = now + max(1, ttl_seconds)
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO long_term_memory_locks(lock_key, owner_id, acquired_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (lock_key, owner_id, now, expires_at),
                )
                return True
            except sqlite3.IntegrityError:
                cursor = conn.execute(
                    """
                    UPDATE long_term_memory_locks
                    SET owner_id = ?, acquired_at = ?, expires_at = ?
                    WHERE lock_key = ? AND expires_at < ?
                    """,
                    (owner_id, now, expires_at, lock_key, now),
                )
                return cursor.rowcount > 0

    def release_write_lock(self, *, user_id: str, workspace_fingerprint: str, owner_id: str) -> None:
        lock_key = self.lock_key(user_id=user_id, workspace_fingerprint=workspace_fingerprint)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM long_term_memory_locks WHERE lock_key = ? AND owner_id = ?",
                (lock_key, owner_id),
            )

    def apply_patch_as_new_version(
        self,
        *,
        user_id: str,
        workspace_fingerprint: str,
        workspace_label: str,
        source_session_id: str,
        parent_version_id: str,
        existing_items: list[LongTermMemoryItem],
        new_items: list[dict[str, Any]],
        update_items: list[dict[str, Any]],
        retire_items: list[dict[str, Any]],
        extraction_id: str,
    ) -> str:
        now = time()
        version_id = uuid4().hex
        existing_by_uid = {item.memory_uid: item for item in existing_items if item.status == MemoryItemStatus.ACTIVE}
        self._validate_patch(existing_by_uid, new_items, update_items, retire_items)
        next_items: dict[str, LongTermMemoryItem] = {
            uid: LongTermMemoryItem(
                memory_uid=item.memory_uid,
                version_id=version_id,
                memory_type=item.memory_type,
                scope=item.scope,
                content=item.content,
                confidence=item.confidence,
                evidence=list(item.evidence),
                metadata=dict(item.metadata),
                status=item.status,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for uid, item in existing_by_uid.items()
        }
        for raw in new_items:
            memory_uid = uuid4().hex
            next_items[memory_uid] = _item_from_payload(raw, version_id=version_id, memory_uid=memory_uid, now=now)
        for raw in update_items:
            previous = existing_by_uid[str(raw["memory_uid"])]
            metadata = dict(raw.get("metadata") or {})
            metadata.setdefault("previous_updated_at", previous.updated_at)
            next_items[previous.memory_uid] = _item_from_payload(
                raw,
                version_id=version_id,
                memory_uid=previous.memory_uid,
                now=now,
                created_at=previous.created_at,
                metadata=metadata,
            )
        for raw in retire_items:
            previous = existing_by_uid[str(raw["memory_uid"])]
            metadata = dict(previous.metadata)
            metadata["retire_reason"] = str(raw.get("reason", ""))
            next_items[previous.memory_uid] = LongTermMemoryItem(
                memory_uid=previous.memory_uid,
                version_id=version_id,
                memory_type=previous.memory_type,
                scope=previous.scope,
                content=previous.content,
                confidence=previous.confidence,
                evidence=list(raw.get("evidence") or previous.evidence),
                metadata=metadata,
                status=MemoryItemStatus.RETIRED,
                created_at=previous.created_at,
                updated_at=now,
            )

        with self._connect() as conn:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    """
                    INSERT INTO long_term_memory_versions(
                        version_id, user_id, workspace_fingerprint, workspace_label, status,
                        parent_version_id, source_session_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        user_id,
                        workspace_fingerprint,
                        workspace_label,
                        MemoryVersionStatus.STAGING.value,
                        parent_version_id,
                        source_session_id,
                        now,
                    ),
                )
                conn.executemany(
                    """
                    INSERT INTO long_term_memory_items(
                        version_id, memory_uid, memory_type, scope, content, confidence,
                        evidence_json, metadata_json, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [_item_row_values(item) for item in next_items.values()],
                )
                conn.execute(
                    """
                    UPDATE long_term_memory_versions
                    SET status = ?, committed_at = ?
                    WHERE version_id = ?
                    """,
                    (MemoryVersionStatus.COMMITTED.value, now, version_id),
                )
                conn.execute(
                    """
                    UPDATE long_term_memory_extractions
                    SET status = ?, committed_version_id = ?, finished_at = ?, updated_at = ?
                    WHERE extraction_id = ?
                    """,
                    (ExtractionStatus.COMMITTED.value, version_id, now, now, extraction_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                with self._connect() as fail_conn:
                    fail_conn.execute(
                        "UPDATE long_term_memory_versions SET status = ? WHERE version_id = ?",
                        (MemoryVersionStatus.FAILED.value, version_id),
                    )
                raise
        return version_id

    def record_turn_usage(
        self,
        *,
        session_id: str,
        turn_start_index: int,
        turn_end_index: int,
        version_id: str,
        exposed_workflow: list[str],
        exposed_skill: list[str],
        used_skill: list[str],
        success: bool,
        prompted: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO long_term_memory_turn_usage(
                    usage_id, session_id, turn_start_index, turn_end_index, version_id,
                    exposed_workflow_json, exposed_skill_json, used_skill_json,
                    success, prompted_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    session_id,
                    turn_start_index,
                    turn_end_index,
                    version_id,
                    json.dumps(exposed_workflow, ensure_ascii=False),
                    json.dumps(exposed_skill, ensure_ascii=False),
                    json.dumps(used_skill, ensure_ascii=False),
                    int(success),
                    json.dumps(prompted or {}, ensure_ascii=False),
                    time(),
                ),
            )

    def successful_skill_reuse_count(self, memory_uid: str) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT used_skill_json FROM long_term_memory_turn_usage
                WHERE success = 1
                """
            ).fetchall()
        count = 0
        for row in rows:
            try:
                used = json.loads(row["used_skill_json"])
            except json.JSONDecodeError:
                used = []
            if memory_uid in used:
                count += 1
        return count

    def last_skill_prompt_at(self, memory_uid: str) -> float:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT prompted_json, created_at FROM long_term_memory_turn_usage ORDER BY created_at DESC"
            ).fetchall()
        for row in rows:
            try:
                prompted = json.loads(row["prompted_json"])
            except json.JSONDecodeError:
                prompted = {}
            if prompted.get("memory_uid") == memory_uid:
                return float(row["created_at"])
        return 0.0

    def mark_skill_candidate_promotion_status(
        self,
        *,
        user_id: str,
        workspace_fingerprint: str,
        memory_uid: str,
        decision: str,
    ) -> str:
        latest = self.latest_committed_version(user_id=user_id, workspace_fingerprint=workspace_fingerprint)
        if latest is None:
            return ""
        items = self.load_items(latest.version_id, active_only=True)
        target = next((item for item in items if item.memory_uid == memory_uid), None)
        if target is None or target.memory_type != MemoryType.SKILL_CANDIDATE:
            return ""
        now = time()
        version_id = uuid4().hex
        with self._connect() as conn:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    """
                    INSERT INTO long_term_memory_versions(
                        version_id, user_id, workspace_fingerprint, workspace_label, status,
                        parent_version_id, source_session_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        user_id,
                        workspace_fingerprint,
                        latest.workspace_label,
                        MemoryVersionStatus.STAGING.value,
                        latest.version_id,
                        latest.source_session_id,
                        now,
                    ),
                )
                copied_items: list[LongTermMemoryItem] = []
                for item in items:
                    metadata = dict(item.metadata)
                    updated_at = item.updated_at
                    if item.memory_uid == memory_uid:
                        metadata["promotion_status"] = decision
                        metadata["promotion_updated_at"] = now
                        if decision == "declined":
                            metadata["promotion_declined_count"] = int(metadata.get("promotion_declined_count", 0) or 0) + 1
                        updated_at = now
                    copied_items.append(
                        LongTermMemoryItem(
                            memory_uid=item.memory_uid,
                            version_id=version_id,
                            memory_type=item.memory_type,
                            scope=item.scope,
                            content=item.content,
                            confidence=item.confidence,
                            evidence=list(item.evidence),
                            metadata=metadata,
                            status=item.status,
                            created_at=item.created_at,
                            updated_at=updated_at,
                        )
                    )
                conn.executemany(
                    """
                    INSERT INTO long_term_memory_items(
                        version_id, memory_uid, memory_type, scope, content, confidence,
                        evidence_json, metadata_json, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [_item_row_values(item) for item in copied_items],
                )
                conn.execute(
                    """
                    UPDATE long_term_memory_versions
                    SET status = ?, committed_at = ?
                    WHERE version_id = ?
                    """,
                    (MemoryVersionStatus.COMMITTED.value, now, version_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return version_id

    @staticmethod
    def lock_key(*, user_id: str, workspace_fingerprint: str) -> str:
        return f"user:{user_id}:workspace:{workspace_fingerprint}"

    @staticmethod
    def _validate_patch(
        existing_by_uid: dict[str, LongTermMemoryItem],
        new_items: list[dict[str, Any]],
        update_items: list[dict[str, Any]],
        retire_items: list[dict[str, Any]],
    ) -> None:
        for raw in [*new_items, *update_items]:
            if not str(raw.get("content", "")).strip():
                raise ValueError("memory content is required")
            if not raw.get("evidence"):
                raise ValueError("memory evidence is required")
            MemoryType(str(raw["memory_type"]))
            MemoryScope(str(raw["scope"]))
        for raw in update_items:
            if str(raw.get("memory_uid", "")) not in existing_by_uid:
                raise ValueError(f"unknown memory_uid for update: {raw.get('memory_uid')}")
        for raw in retire_items:
            if str(raw.get("memory_uid", "")) not in existing_by_uid:
                raise ValueError(f"unknown memory_uid for retire: {raw.get('memory_uid')}")
            if not str(raw.get("reason", "")).strip():
                raise ValueError("retire reason is required")


def _item_from_payload(
    raw: dict[str, Any],
    *,
    version_id: str,
    memory_uid: str,
    now: float,
    created_at: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> LongTermMemoryItem:
    return LongTermMemoryItem(
        memory_uid=memory_uid,
        version_id=version_id,
        memory_type=MemoryType(str(raw["memory_type"])),
        scope=MemoryScope(str(raw["scope"])),
        content=str(raw["content"]).strip(),
        confidence=float(raw["confidence"]),
        evidence=[str(item) for item in raw.get("evidence", [])],
        metadata=metadata if metadata is not None else dict(raw.get("metadata") or {}),
        status=MemoryItemStatus.ACTIVE,
        created_at=created_at if created_at is not None else now,
        updated_at=now,
    )


def _item_row_values(item: LongTermMemoryItem) -> tuple[Any, ...]:
    return (
        item.version_id,
        item.memory_uid,
        item.memory_type.value,
        item.scope.value,
        item.content,
        item.confidence,
        json.dumps(item.evidence, ensure_ascii=False),
        json.dumps(item.metadata, ensure_ascii=False, default=str),
        item.status.value,
        item.created_at,
        item.updated_at,
    )


def _item_from_row(row: sqlite3.Row) -> LongTermMemoryItem:
    return LongTermMemoryItem(
        version_id=str(row["version_id"]),
        memory_uid=str(row["memory_uid"]),
        memory_type=MemoryType(str(row["memory_type"])),
        scope=MemoryScope(str(row["scope"])),
        content=str(row["content"]),
        confidence=float(row["confidence"]),
        evidence=json.loads(row["evidence_json"] or "[]"),
        metadata=json.loads(row["metadata_json"] or "{}"),
        status=MemoryItemStatus(str(row["status"])),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


def _version_from_row(row: sqlite3.Row) -> LongTermMemoryVersion:
    return LongTermMemoryVersion(
        version_id=str(row["version_id"]),
        user_id=str(row["user_id"]),
        workspace_fingerprint=str(row["workspace_fingerprint"]),
        workspace_label=str(row["workspace_label"]),
        status=MemoryVersionStatus(str(row["status"])),
        parent_version_id=str(row["parent_version_id"]),
        source_session_id=str(row["source_session_id"]),
        created_at=float(row["created_at"]),
        committed_at=float(row["committed_at"]),
        error_text=str(row["error_text"]),
    )


def _extraction_from_row(row: sqlite3.Row) -> ExtractionJob:
    return ExtractionJob(
        extraction_id=str(row["extraction_id"]),
        session_id=str(row["session_id"]),
        user_id=str(row["user_id"]),
        workspace_fingerprint=str(row["workspace_fingerprint"]),
        workspace_label=str(row["workspace_label"]),
        workspace_root=str(row["workspace_root"]),
        status=ExtractionStatus(str(row["status"])),
        source_hash=str(row["source_hash"]),
        source_message_count=int(row["source_message_count"]),
        started_at=float(row["started_at"]),
        finished_at=float(row["finished_at"]),
        error_text=str(row["error_text"]),
        committed_version_id=str(row["committed_version_id"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )
