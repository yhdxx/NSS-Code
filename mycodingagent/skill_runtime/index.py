from __future__ import annotations

import sqlite3
from pathlib import Path

from mycodingagent.skill_runtime.models import SkillRecord, SkillReferenceRecord


class SkillSqlStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skills (
                    tool_name TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rejected_skills (
                    source_path TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_references (
                    ref_id TEXT PRIMARY KEY,
                    skill_tool_name TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    reference_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_skill_references_skill_tool_name "
                "ON skill_references(skill_tool_name)"
            )

    def load_all(self) -> dict[str, SkillRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tool_name, name, description, content, source_path, content_hash, updated_at FROM skills"
            ).fetchall()
        records: dict[str, SkillRecord] = {}
        for tool_name, name, description, content, source_path, content_hash, updated_at in rows:
            records[tool_name] = SkillRecord(
                name=name,
                tool_name=tool_name,
                description=description,
                content=content,
                source_path=Path(source_path),
                content_hash=content_hash,
                updated_at=updated_at,
            )
        return records

    def upsert(self, record: SkillRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO skills (tool_name, name, description, content, source_path, content_hash, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tool_name) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    content=excluded.content,
                    source_path=excluded.source_path,
                    content_hash=excluded.content_hash,
                    updated_at=excluded.updated_at
                """,
                (
                    record.tool_name,
                    record.name,
                    record.description,
                    record.content,
                    str(record.source_path),
                    record.content_hash,
                    record.updated_at,
                ),
            )
            conn.execute("DELETE FROM rejected_skills WHERE source_path = ?", (str(record.source_path),))

    def delete_missing_sources(self, existing_sources: set[str]) -> int:
        with self._connect() as conn:
            rows = conn.execute("SELECT tool_name, source_path FROM skills").fetchall()
            deleted = 0
            for tool_name, source_path in rows:
                if source_path not in existing_sources:
                    conn.execute("DELETE FROM skills WHERE tool_name = ?", (tool_name,))
                    deleted += 1
        return deleted

    def delete_missing_tool_names(self, existing_tool_names: set[str]) -> int:
        with self._connect() as conn:
            rows = conn.execute("SELECT tool_name FROM skills").fetchall()
            deleted = 0
            for (tool_name,) in rows:
                if tool_name not in existing_tool_names:
                    conn.execute("DELETE FROM skills WHERE tool_name = ?", (tool_name,))
                    deleted += 1
        return deleted

    def reject(self, source_path: Path, reason: str, updated_at: float) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rejected_skills (source_path, reason, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    reason=excluded.reason,
                    updated_at=excluded.updated_at
                """,
                (str(source_path), reason, updated_at),
            )

    def load_references(self) -> dict[str, SkillReferenceRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ref_id, skill_tool_name, skill_name, reference_path, file_name,
                       content, source_path, content_hash, updated_at
                FROM skill_references
                """
            ).fetchall()
        records: dict[str, SkillReferenceRecord] = {}
        for row in rows:
            (
                ref_id,
                skill_tool_name,
                skill_name,
                reference_path,
                file_name,
                content,
                source_path,
                content_hash,
                updated_at,
            ) = row
            records[ref_id] = SkillReferenceRecord(
                ref_id=ref_id,
                skill_tool_name=skill_tool_name,
                skill_name=skill_name,
                reference_path=reference_path,
                file_name=file_name,
                content=content,
                source_path=Path(source_path),
                content_hash=content_hash,
                updated_at=updated_at,
            )
        return records

    def upsert_reference(self, record: SkillReferenceRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO skill_references (
                    ref_id, skill_tool_name, skill_name, reference_path, file_name,
                    content, source_path, content_hash, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ref_id) DO UPDATE SET
                    skill_tool_name=excluded.skill_tool_name,
                    skill_name=excluded.skill_name,
                    reference_path=excluded.reference_path,
                    file_name=excluded.file_name,
                    content=excluded.content,
                    source_path=excluded.source_path,
                    content_hash=excluded.content_hash,
                    updated_at=excluded.updated_at
                """,
                (
                    record.ref_id,
                    record.skill_tool_name,
                    record.skill_name,
                    record.reference_path,
                    record.file_name,
                    record.content,
                    str(record.source_path),
                    record.content_hash,
                    record.updated_at,
                ),
            )

    def delete_missing_references(self, existing_ref_ids: set[str]) -> int:
        with self._connect() as conn:
            rows = conn.execute("SELECT ref_id FROM skill_references").fetchall()
            deleted = 0
            for (ref_id,) in rows:
                if ref_id not in existing_ref_ids:
                    conn.execute("DELETE FROM skill_references WHERE ref_id = ?", (ref_id,))
                    deleted += 1
        return deleted

    def delete_references_for_missing_skills(self, existing_tool_names: set[str]) -> int:
        with self._connect() as conn:
            rows = conn.execute("SELECT ref_id, skill_tool_name FROM skill_references").fetchall()
            deleted = 0
            for ref_id, skill_tool_name in rows:
                if skill_tool_name not in existing_tool_names:
                    conn.execute("DELETE FROM skill_references WHERE ref_id = ?", (ref_id,))
                    deleted += 1
        return deleted

    def get_reference(self, *, skill_tool_name: str, reference_path: str) -> SkillReferenceRecord | None:
        ref_id = f"{skill_tool_name}:{reference_path}"
        return self.load_references().get(ref_id)

    def list_references_for_skill(self, skill_tool_name: str) -> list[SkillReferenceRecord]:
        records = [
            record
            for record in self.load_references().values()
            if record.skill_tool_name == skill_tool_name
        ]
        return sorted(records, key=lambda record: record.reference_path)
