from __future__ import annotations

import sqlite3

import pytest

from mycodingagent.long_term_memory.store import SQLiteLongTermMemoryStore
from mycodingagent.memory.stores import SQLiteMemoryStore
from mycodingagent.sqlite_utils import IncompatibleSchemaError, SCHEMA_VERSION_TABLE
from mycodingagent.tool_runtime.command_policy import BashPolicyStore


@pytest.mark.parametrize(
    ("component", "factory"),
    [
        ("memory", SQLiteMemoryStore),
        ("long_term_memory", SQLiteLongTermMemoryStore),
        ("bash_policy", BashPolicyStore),
    ],
)
def test_persistent_store_rejects_schema_version_mismatch(tmp_path, component, factory):
    db_path = tmp_path / f"{component}.sqlite3"
    factory(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE {SCHEMA_VERSION_TABLE} SET version = 0 WHERE component = ?",
            (component,),
        )

    with pytest.raises(IncompatibleSchemaError) as error:
        factory(db_path)

    message = str(error.value)
    assert str(db_path) in message
    assert "found 0, expected 1" in message
    assert "Back up the database and remove it" in message
