from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from mycodingagent.code_intelligence import LSPManager, WorkspaceCodeIndex
from mycodingagent.code_intelligence.lsp import _LSPProcess
from mycodingagent.tool_runtime.code_intelligence import CodeIndexTool, LSPTool


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


def test_code_index_impact_aggregates_callers_callees_and_tests(tmp_path):
    (tmp_path / "service.py").write_text(
        "def helper():\n    return 1\n\ndef target():\n    return helper()\n\ndef entry():\n    return target()\n",
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_service.py").write_text(
        "from service import target\n\ndef test_target():\n    assert target() == 1\n",
        encoding="utf-8",
    )
    index = WorkspaceCodeIndex(tmp_path, tmp_path / "index.sqlite3")

    result = index.query("impact", query="target", depth=2)

    assert {item["path"] for item in result["definitions"]} == {"service.py"}
    assert {item["caller"] for item in result["callers"]} >= {"entry", "test_target"}
    assert {item["callee_name"] for item in result["callees"]} == {"helper"}
    assert {item["path"] for item in result["tests"]} == {"tests/test_service.py"}
    assert result["recommended_files"] == ["service.py", "tests/test_service.py"]


def test_code_index_batch_uses_one_refresh_and_honors_filters(tmp_path):
    (tmp_path / "sample.py").write_text("def target():\n    return 1\n", encoding="utf-8")
    (tmp_path / "sample.js").write_text("function target() { return 1; }\n", encoding="utf-8")
    index = WorkspaceCodeIndex(tmp_path, tmp_path / "index.sqlite3")

    result = index.query(
        "batch",
        queries=[
            {"operation": "definition_candidates", "query": "target", "language": "python"},
            {"operation": "outline", "path": "sample.js"},
        ],
    )

    assert result["refresh"]["full"] == 1
    assert {item["path"] for item in result["results"][0]["symbols"]} == {"sample.py"}
    assert result["results"][1]["symbols"][0]["path"] == "sample.js"


def test_code_index_overview_summarizes_workspace_and_subdirectory(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "service.py").write_text("class Service:\n    pass\n", encoding="utf-8")
    (tmp_path / "web.ts").write_text("function render() { return 1; }\n", encoding="utf-8")
    index = WorkspaceCodeIndex(tmp_path, tmp_path / "index.sqlite3")

    workspace = index.query("overview", path="/workspace")
    package_only = index.query("overview", path="pkg")

    assert workspace["files"] == {"total": 2, "by_language": {"python": 1, "typescript": 1}}
    assert {item["path"] for item in workspace["modules"]} == {".", "pkg"}
    assert {item["name"] for item in workspace["symbols"]["top_level"]} == {"Service", "render"}
    assert package_only["path"] == "/workspace/pkg"
    assert package_only["files"]["by_language"] == {"python": 1}


def test_code_index_outline_directory_returns_overview_retry(tmp_path):
    (tmp_path / "sample.py").write_text("value = 1\n", encoding="utf-8")
    index = WorkspaceCodeIndex(tmp_path, tmp_path / "index.sqlite3")

    result = index.query("outline", path="/workspace")

    assert result["error_code"] == "file_required"
    assert result["workspace_root"] == "/workspace"
    assert result["suggested_call"] == {"operation": "overview", "path": "/workspace"}


def test_code_index_batch_promotes_invalid_child_to_structured_error(tmp_path):
    index = WorkspaceCodeIndex(tmp_path, tmp_path / "index.sqlite3")

    result = index.query("batch", queries=[{"operation": "symbols", "query": ""}])

    assert result["error_code"] == "batch_query_invalid"
    assert result["query_index"] == 0
    assert result["cause"]["error_code"] == "query_required"


@pytest.mark.parametrize("operation", ["symbols", "definition_candidates", "callers", "callees", "impact"])
def test_code_index_symbol_operations_require_query(tmp_path, operation):
    index = WorkspaceCodeIndex(tmp_path, tmp_path / "index.sqlite3")

    result = index.query(operation, query="")

    assert result["error_code"] == "query_required"


def test_code_index_does_not_reread_unchanged_files(tmp_path, monkeypatch):
    source = tmp_path / "sample.py"
    source.write_text("def target():\n    return 1\n", encoding="utf-8")
    index = WorkspaceCodeIndex(tmp_path, tmp_path / "index.sqlite3")
    index.query("symbols", query="target")

    monkeypatch.setattr(Path, "read_bytes", lambda _self: (_ for _ in ()).throw(AssertionError("reread")))

    result = index.query("symbols", query="target")
    assert result["symbols"]
    assert result["refresh"]["indexed"] == 0


def test_code_index_rejects_outside_workspace_filter(tmp_path):
    (tmp_path / "sample.py").write_text("def target():\n    return 1\n", encoding="utf-8")
    index = WorkspaceCodeIndex(tmp_path, tmp_path / "index.sqlite3")

    result = index.query("symbols", query="target", path="/etc")

    assert "工作区之外" in result["error"]
    assert result["suggested_call"] == {
        "operation": "symbols",
        "path": "/workspace",
        "query": "target",
    }


def test_code_index_empty_impact_has_zero_evidence(tmp_path):
    (tmp_path / "sample.py").write_text("value = 1\n", encoding="utf-8")
    index = WorkspaceCodeIndex(tmp_path, tmp_path / "index.sqlite3")

    result = index.query("impact", query="missing_symbol")

    assert result["evidence_count"] == 0


def test_lsp_degrades_when_language_server_is_missing(tmp_path, monkeypatch):
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr("mycodingagent.code_intelligence.lsp.shutil.which", lambda _name: None)
    manager = LSPManager(tmp_path)

    result = asyncio.run(manager.query("hover", path="sample.py", line=1, column=0))

    assert result["available"] is False
    assert result["language"] == "python"
    assert result["error_code"] == "server_unavailable"
    assert result["retryable"] is False
    assert "code_index" in result["fallback"]


def test_lsp_runtime_payload_reports_all_supported_languages(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "mycodingagent.code_intelligence.lsp.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"gopls", "rust-analyzer"} else None,
    )
    manager = LSPManager(tmp_path)

    payload = manager.runtime_payload()

    assert set(payload["languages"]) == {"python", "go", "typescript", "javascript", "rust", "java"}
    assert payload["available"] is True
    assert payload["policy"] == "conditional_semantic_verification"
    assert payload["languages"]["go"]["available"] is True
    assert payload["languages"]["python"]["available"] is False


def test_lsp_document_sync_opens_once_and_changes_only_when_content_changes(tmp_path, monkeypatch):
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    manager = LSPManager(tmp_path)
    client = _LSPProcess(
        process=SimpleNamespace(), lock=asyncio.Lock(), server_name="fake-lsp"
    )
    notifications = []

    async def fake_notify(_client, method, params):
        notifications.append((method, params))

    monkeypatch.setattr(manager, "_notify", fake_notify)

    async def scenario():
        uri = source.as_uri()
        await manager._sync_document(client, uri=uri, language="python", path=source)
        await manager._sync_document(client, uri=uri, language="python", path=source)
        source.write_text("value = 2\n", encoding="utf-8")
        await manager._sync_document(client, uri=uri, language="python", path=source)

    asyncio.run(scenario())

    assert [method for method, _params in notifications] == ["textDocument/didOpen", "textDocument/didChange"]
    assert notifications[1][1]["textDocument"]["version"] == 2


def test_code_intelligence_tool_descriptions_define_selection_order():
    assert "项目或目录结构使用 overview" in CodeIndexTool.description
    assert "修改影响分析" in CodeIndexTool.description
    assert "suggested_call" in CodeIndexTool.description
    assert "code_index 定位" in LSPTool.description
    assert "语言服务器不可用" in LSPTool.description


def test_code_index_schema_explains_operation_specific_paths():
    schema = CodeIndexTool.params_model.model_json_schema()

    assert "目录结构用 overview" in schema["properties"]["operation"]["description"]
    assert "overview 接受目录" in schema["properties"]["path"]["description"]
    assert "除 overview 和 outline 外" in schema["properties"]["query"]["description"]
