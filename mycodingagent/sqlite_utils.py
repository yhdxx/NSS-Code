from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION_TABLE = "mycodingagent_schema_versions"


class IncompatibleSchemaError(RuntimeError):
    pass


def require_component_schema(
    conn: sqlite3.Connection,
    *,
    db_path: Path,
    component: str,
    version: int,
    owned_tables: tuple[str, ...],
) -> None:
    """Reject old persistent state instead of mutating it in place."""

    metadata_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (SCHEMA_VERSION_TABLE,),
    ).fetchone() is not None
    current = None
    if metadata_exists:
        row = conn.execute(
            f"SELECT version FROM {SCHEMA_VERSION_TABLE} WHERE component = ?",
            (component,),
        ).fetchone()
        current = int(row[0]) if row is not None else None
    if current is None:
        placeholders = ",".join("?" for _ in owned_tables)
        existing = conn.execute(
            f"SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({placeholders}) LIMIT 1",
            owned_tables,
        ).fetchone()
        if existing is not None:
            raise IncompatibleSchemaError(_schema_error(db_path, component, "unversioned", version))
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {SCHEMA_VERSION_TABLE} ("
            "component TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        conn.execute(
            f"INSERT INTO {SCHEMA_VERSION_TABLE}(component, version) VALUES (?, ?)",
            (component, version),
        )
        return
    if current != version:
        raise IncompatibleSchemaError(_schema_error(db_path, component, str(current), version))


def _schema_error(db_path: Path, component: str, current: str, expected: int) -> str:
    return (
        f"Incompatible {component} SQLite schema at {db_path}: found {current}, expected {expected}. "
        "Back up the database and remove it so myAgent can create current state."
    )


class ClosingSQLiteConnection(sqlite3.Connection):
    """SQLite connection whose transaction context also releases its FD."""

    def __exit__(self, exc_type, exc, traceback):
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


SQLITE_CONNECTION_FACTORY = ClosingSQLiteConnection
