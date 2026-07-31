from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mycodingagent.code_intelligence import LSPManager, WorkspaceCodeIndex


@pytest.mark.parametrize(
    ("filename", "content", "symbol"),
    [
        ("sample.py", "class PythonThing:\n    def run(self):\n        return helper()\n", "PythonThing"),
        ("sample.go", "package p\ntype GoThing struct{}\nfunc Run() { Helper() }\n", "GoThing"),
        ("sample.ts", "class TypeScriptThing { run() { helper(); } }\n", "TypeScriptThing"),
        ("sample.js", "class JavaScriptThing { run() { helper(); } }\n", "JavaScriptThing"),
        ("sample.rs", "struct RustThing {}\nfn run() { helper(); }\n", "RustThing"),
        ("Sample.java", "class JavaThing { void run() { helper(); } }\n", "JavaThing"),
    ],
)
def test_code_index_extracts_six_language_symbols(tmp_path, filename, content, symbol):
    (tmp_path / filename).write_text(content, encoding="utf-8")
    index = WorkspaceCodeIndex(tmp_path, tmp_path / "index.sqlite3")

    result = index.query("definition_candidates", query=symbol)

    assert [item["name"] for item in result["symbols"]] == [symbol]


def test_code_index_incrementally_updates_and_reports_calls(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text("def caller():\n    target()\n", encoding="utf-8")
    index = WorkspaceCodeIndex(tmp_path, tmp_path / "index.sqlite3")

    assert index.query("callers", query="target")["callers"][0]["caller"] == "caller"
    source.write_text("def renamed():\n    target()\n", encoding="utf-8")

    assert index.query("definition_candidates", query="caller")["symbols"] == []
    assert index.query("definition_candidates", query="renamed")["symbols"]


def test_lsp_degrades_when_language_server_is_missing(tmp_path, monkeypatch):
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr("mycodingagent.code_intelligence.lsp.shutil.which", lambda _name: None)
    manager = LSPManager(tmp_path)

    result = asyncio.run(manager.query("hover", path="sample.py", line=1, column=0))

    assert result["available"] is False
    assert result["language"] == "python"
