from __future__ import annotations

import gc
import hashlib
import os
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from time import time
from typing import Any

from tree_sitter import Node
from tree_sitter_language_pack import get_parser


CODE_INDEX_SCHEMA_VERSION = 2
MAX_FILE_SIZE = 2_000_000
LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".java": "java",
}
SKIP_DIRS = {".git", ".venv", "node_modules", "target", "dist", "build", "__pycache__", ".idea"}
SYMBOL_NODES = {
    "python": {"function_definition": "function", "class_definition": "class"},
    "go": {"function_declaration": "function", "method_declaration": "method", "type_spec": "type"},
    "typescript": {
        "function_declaration": "function", "class_declaration": "class", "method_definition": "method",
        "interface_declaration": "interface", "type_alias_declaration": "type",
    },
    "javascript": {
        "function_declaration": "function", "class_declaration": "class", "method_definition": "method",
    },
    "rust": {
        "function_item": "function", "struct_item": "struct", "enum_item": "enum",
        "trait_item": "trait", "mod_item": "module",
    },
    "java": {
        "class_declaration": "class", "interface_declaration": "interface", "method_declaration": "method",
        "constructor_declaration": "constructor", "enum_declaration": "enum",
    },
}
CALL_NODES = {"call", "call_expression", "method_invocation", "macro_invocation"}
IMPORT_NODES = {
    "import_statement", "import_from_statement", "import_declaration", "import_spec", "use_declaration"
}
REFERENCE_NODES = {
    "identifier", "type_identifier", "field_identifier", "property_identifier", "scoped_identifier"
}


@dataclass(frozen=True)
class CodeSymbol:
    path: str
    language: str
    name: str
    qualified_name: str
    kind: str
    start_line: int
    start_column: int
    end_line: int
    parent: str = ""
    signature: str = ""


@dataclass(frozen=True)
class CodeCall:
    path: str
    language: str
    caller: str
    qualified_callee: str
    callee_name: str
    line: int


@dataclass(frozen=True)
class CodeImport:
    path: str
    language: str
    module: str
    imported_name: str
    line: int


@dataclass(frozen=True)
class CodeReference:
    path: str
    language: str
    name: str
    line: int
    column: int
    reference_kind: str = "syntactic"


class WorkspaceCodeIndex:
    def __init__(self, workspace_root: Path, db_path: Path | str, *, max_files: int = 5000) -> None:
        self.workspace_root = workspace_root.resolve(strict=False)
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_files = max_files
        self._lock = RLock()
        self._dirty_paths: set[str] = set()
        self._ready = False
        self._generation = 0
        self._init_db()

    def status(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            count = int(conn.execute("SELECT COUNT(*) FROM code_files").fetchone()[0])
            return {
                "available": True,
                "schema_version": CODE_INDEX_SCHEMA_VERSION,
                "generation": self._generation,
                "indexed_files": count,
                "languages": sorted(set(LANGUAGE_BY_SUFFIX.values())),
                "ready": self._ready,
            }

    def mark_dirty(self, path: Path | str, _is_delete: bool = False) -> None:
        relative = self._relative_candidate(path)
        if relative is None:
            return
        with self._lock:
            self._dirty_paths.add(relative)

    def query(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            if self._ready:
                self._reconcile_indexed_paths()
            refresh = self.refresh()
            result = self._query_without_refresh(operation, **kwargs)
            result.setdefault("index_generation", self._generation)
            result.setdefault("refresh", refresh)
            result.setdefault("evidence_count", self._evidence_count(result))
            return result

    def _reconcile_indexed_paths(self) -> None:
        """Catch edits that race the workspace watcher without rereading file contents."""
        with self._connect() as conn:
            indexed = conn.execute("SELECT path, mtime_ns, size FROM code_files").fetchall()
        for row in indexed:
            relative = str(row["path"])
            path = self.workspace_root / relative
            try:
                stat = path.stat()
                changed = (stat.st_mtime_ns, stat.st_size) != (int(row["mtime_ns"]), int(row["size"]))
            except OSError:
                changed = True
            if changed:
                self._dirty_paths.add(relative)

    def refresh(self, *, force_full: bool = False) -> dict[str, int]:
        with self._lock:
            full = force_full or not self._ready
            if full:
                result = self._refresh_full()
                self._ready = True
            elif self._dirty_paths:
                dirty = sorted(self._dirty_paths)
                self._dirty_paths.clear()
                result = self._refresh_paths(dirty)
            else:
                return {"indexed": 0, "unchanged": 0, "removed": 0, "full": 0}
            if result["indexed"] or result["removed"]:
                self._generation += 1
                self._set_meta("generation", str(self._generation))
            result["full"] = int(full)
            return result

    def _query_without_refresh(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        raw_path_filter = str(kwargs.get("path", ""))
        path_filter = self._normalize_filter(raw_path_filter)
        if raw_path_filter.strip() and not path_filter:
            return {"error": f"路径过滤条件位于工作区之外：{raw_path_filter}"}
        language = str(kwargs.get("language", "")).strip().lower()
        limit = self._limit(kwargs.get("limit", 50))
        query = str(kwargs.get("query", "")).strip()
        if language and language not in set(LANGUAGE_BY_SUFFIX.values()):
            return {"error": f"不支持的语言过滤条件：{language}"}
        if operation == "outline":
            return self._outline(str(kwargs.get("path", "")))
        if operation in {"symbols", "definition_candidates"}:
            return self._symbols(query, exact=operation == "definition_candidates", limit=limit,
                                 path_filter=path_filter, language=language)
        if operation in {"callers", "callees"}:
            return self._calls(operation, query, limit, path_filter=path_filter, language=language)
        if operation == "impact":
            return self._impact(
                query,
                depth=max(1, min(int(kwargs.get("depth", 1)), 3)),
                include_tests=bool(kwargs.get("include_tests", True)),
                limit=limit,
                path_filter=path_filter,
                language=language,
            )
        if operation == "batch":
            queries = kwargs.get("queries", [])
            if not isinstance(queries, list) or not queries:
                return {"error": "batch 需要非空的 queries 列表"}
            if len(queries) > 20:
                return {"error": "batch 最多支持 20 个查询"}
            results: list[dict[str, Any]] = []
            for item in queries:
                if not isinstance(item, dict):
                    return {"error": "batch 中的每个查询都必须是对象"}
                child = dict(item)
                child_operation = str(child.pop("operation", ""))
                if child_operation == "batch":
                    return {"error": "不支持嵌套 batch 查询"}
                results.append(self._query_without_refresh(child_operation, **child))
            return {"results": results, "count": len(results)}
        return {"error": f"不支持的代码索引操作：{operation}"}

    def _refresh_full(self) -> dict[str, int]:
        files = list(self._iter_files())[: self.max_files]
        current = {path.relative_to(self.workspace_root).as_posix(): path for path in files}
        with self._connect() as conn:
            existing = {
                row["path"]: (int(row["mtime_ns"]), int(row["size"]))
                for row in conn.execute("SELECT path, mtime_ns, size FROM code_files")
            }
        indexed = unchanged = 0
        for relative, path in current.items():
            try:
                stat = path.stat()
            except OSError:
                continue
            fingerprint = (stat.st_mtime_ns, stat.st_size)
            if existing.get(relative) == fingerprint:
                unchanged += 1
                continue
            if self._index_path(relative, path, stat.st_mtime_ns, stat.st_size):
                indexed += 1
        removed = sorted(set(existing) - set(current))
        self._delete_paths(removed)
        return {"indexed": indexed, "unchanged": unchanged, "removed": len(removed)}

    def _refresh_paths(self, relatives: list[str]) -> dict[str, int]:
        indexed = unchanged = removed = 0
        with self._connect() as conn:
            existing = {
                row["path"]: (int(row["mtime_ns"]), int(row["size"]))
                for row in conn.execute(
                    f"SELECT path, mtime_ns, size FROM code_files WHERE path IN ({','.join('?' for _ in relatives)})",
                    relatives,
                )
            } if relatives else {}
        for relative in relatives:
            path = self.workspace_root / relative
            if not path.is_file() or path.suffix.lower() not in LANGUAGE_BY_SUFFIX:
                if relative in existing:
                    self._delete_paths([relative])
                    removed += 1
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size > MAX_FILE_SIZE:
                self._delete_paths([relative])
                removed += int(relative in existing)
                continue
            if existing.get(relative) == (stat.st_mtime_ns, stat.st_size):
                unchanged += 1
                continue
            if self._index_path(relative, path, stat.st_mtime_ns, stat.st_size):
                indexed += 1
        return {"indexed": indexed, "unchanged": unchanged, "removed": removed}

    def _index_path(self, relative: str, path: Path, mtime_ns: int, size: int) -> bool:
        try:
            content = path.read_bytes()
        except OSError:
            return False
        language = LANGUAGE_BY_SUFFIX[path.suffix.lower()]
        content_hash = hashlib.sha256(content).hexdigest()
        parser = get_parser(language)
        tree = parser.parse(content)
        symbols: list[CodeSymbol] = []
        calls: list[CodeCall] = []
        imports: list[CodeImport] = []
        references: list[CodeReference] = []
        gc_was_enabled = gc.isenabled()
        gc.disable()
        try:
            stack: list[tuple[Node, str]] = [(tree.root_node, "")]
            while stack:
                node, parent = stack.pop()
                current_parent = parent
                kind = SYMBOL_NODES.get(language, {}).get(node.type)
                name_node = node.child_by_field_name("name") if kind else None
                if kind and name_node is not None:
                    name = self._node_text(name_node, content)
                    if name:
                        qualified_name = f"{parent}.{name}" if parent else name
                        symbols.append(
                            CodeSymbol(relative, language, name, qualified_name, kind,
                                       node.start_point.row + 1, node.start_point.column,
                                       node.end_point.row + 1, parent, self._signature(node, content))
                        )
                        current_parent = qualified_name
                if node.type in CALL_NODES:
                    target = node.child_by_field_name("function")
                    if target is None:
                        target = node.child_by_field_name("name")
                    qualified = self._node_text(target, content) if target is not None else ""
                    if qualified:
                        calls.append(
                            CodeCall(relative, language, parent, qualified[:300],
                                     self._terminal_name(qualified), node.start_point.row + 1)
                        )
                if node.type in IMPORT_NODES:
                    text = self._node_text(node, content)[:500]
                    names = self._identifier_texts(node, content)
                    if not names:
                        names = [""]
                    imports.extend(
                        CodeImport(relative, language, text, imported_name, node.start_point.row + 1)
                        for imported_name in names
                    )
                if node.type in REFERENCE_NODES:
                    name = self._node_text(node, content)
                    if name and len(name) <= 300:
                        references.append(
                            CodeReference(relative, language, name, node.start_point.row + 1,
                                          node.start_point.column)
                        )
                stack.extend((child, current_parent) for child in reversed(list(node.named_children)))
        finally:
            if gc_was_enabled:
                gc.enable()
        with self._connect() as conn:
            self._delete_path_rows(conn, relative)
            conn.execute(
                "INSERT INTO code_files(path, language, content_hash, mtime_ns, size, indexed_at) VALUES (?, ?, ?, ?, ?, ?)",
                (relative, language, content_hash, mtime_ns, size, time()),
            )
            conn.executemany(
                """INSERT INTO code_symbols(path, language, name, qualified_name, kind, start_line,
                   start_column, end_line, parent, signature)
                   VALUES (:path, :language, :name, :qualified_name, :kind, :start_line,
                   :start_column, :end_line, :parent, :signature)""",
                [asdict(item) for item in symbols],
            )
            conn.executemany(
                """INSERT INTO code_calls(path, language, caller, qualified_callee, callee_name, line)
                   VALUES (:path, :language, :caller, :qualified_callee, :callee_name, :line)""",
                [asdict(item) for item in calls],
            )
            conn.executemany(
                """INSERT INTO code_imports(path, language, module, imported_name, line)
                   VALUES (:path, :language, :module, :imported_name, :line)""",
                [asdict(item) for item in imports],
            )
            conn.executemany(
                """INSERT INTO code_references(path, language, name, line, column, reference_kind)
                   VALUES (:path, :language, :name, :line, :column, :reference_kind)""",
                [asdict(item) for item in references],
            )
        return True

    def _outline(self, raw_path: str) -> dict[str, Any]:
        relative = self._normalize_file(raw_path)
        if relative is None:
            return {"error": f"路径位于工作区之外或不存在：{raw_path}", "symbols": []}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM code_symbols WHERE path = ? ORDER BY start_line, start_column", (relative,)
            ).fetchall()
        return {"path": relative, "symbols": [dict(row) for row in rows]}

    def _symbols(self, query: str, *, exact: bool, limit: int, path_filter: str, language: str) -> dict[str, Any]:
        clauses = ["lower(name) = lower(?)" if exact else "lower(name) LIKE lower(?)"]
        values: list[Any] = [query if exact else f"%{query}%"]
        self._add_filters(clauses, values, path_filter, language)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM code_symbols WHERE {' AND '.join(clauses)} ORDER BY name, path, start_line LIMIT ?",
                (*values, limit),
            ).fetchall()
        return {"query": query, "symbols": [dict(row) for row in rows], "truncated": len(rows) == limit}

    def _calls(self, operation: str, query: str, limit: int, *, path_filter: str, language: str) -> dict[str, Any]:
        if operation == "callers":
            clauses = ["(lower(callee_name) = lower(?) OR lower(qualified_callee) = lower(?))"]
            values: list[Any] = [query, query]
        else:
            clauses = ["(lower(caller) = lower(?) OR lower(caller) LIKE lower(?))"]
            values = [query, f"%.{query}"]
        self._add_filters(clauses, values, path_filter, language)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM code_calls WHERE {' AND '.join(clauses)} ORDER BY path, line LIMIT ?",
                (*values, limit),
            ).fetchall()
        payload = [dict(row) for row in rows]
        for item in payload:
            item["match"] = "qualified" if item.get("qualified_callee", "").lower() == query.lower() else "terminal"
        return {"query": query, operation: payload, "truncated": len(rows) == limit}

    def _impact(self, query: str, *, depth: int, include_tests: bool, limit: int,
                path_filter: str, language: str) -> dict[str, Any]:
        definitions = self._symbols(query, exact=True, limit=limit, path_filter=path_filter, language=language)["symbols"]
        callers = self._calls("callers", query, limit, path_filter=path_filter, language=language)["callers"]
        callees = self._calls("callees", query, limit, path_filter=path_filter, language=language)["callees"]
        discovered_callers = {str(item.get("caller", "")).rsplit(".", 1)[-1] for item in callers if item.get("caller")}
        frontier = set(discovered_callers)
        for _ in range(1, depth):
            next_frontier: set[str] = set()
            for caller_name in sorted(frontier):
                more = self._calls("callers", caller_name, limit, path_filter=path_filter, language=language)["callers"]
                for item in more:
                    key = (item["path"], item["line"], item["qualified_callee"])
                    if key not in {(row["path"], row["line"], row["qualified_callee"]) for row in callers}:
                        callers.append(item)
                        if item.get("caller"):
                            next_frontier.add(str(item["caller"]).rsplit(".", 1)[-1])
            frontier = next_frontier
            if not frontier:
                break
        clauses = ["lower(name) = lower(?)"]
        values: list[Any] = [query]
        self._add_filters(clauses, values, path_filter, language)
        with self._connect() as conn:
            references = [dict(row) for row in conn.execute(
                f"SELECT * FROM code_references WHERE {' AND '.join(clauses)} ORDER BY path, line LIMIT ?",
                (*values, limit),
            ).fetchall()]
            import_clauses = ["(lower(imported_name) = lower(?) OR lower(module) LIKE lower(?))"]
            import_values: list[Any] = [query, f"%{query}%"]
            self._add_filters(import_clauses, import_values, path_filter, language)
            imports = [dict(row) for row in conn.execute(
                f"SELECT * FROM code_imports WHERE {' AND '.join(import_clauses)} ORDER BY path, line LIMIT ?",
                (*import_values, limit),
            ).fetchall()]
        evidence = [*definitions, *callers, *callees, *references, *imports]
        tests = self._dedupe_rows([item for item in evidence if self._is_test_path(str(item.get("path", "")))]) if include_tests else []
        recommended_files: list[str] = []
        for group in (definitions, callers, callees, imports, references):
            for item in group:
                path = str(item.get("path", ""))
                if path and path not in recommended_files:
                    recommended_files.append(path)
        return {
            "query": query,
            "depth": depth,
            "definitions": definitions,
            "callers": self._dedupe_rows(callers)[:limit],
            "callees": self._dedupe_rows(callees)[:limit],
            "imports": self._dedupe_rows(imports)[:limit],
            "references": self._dedupe_rows(references)[:limit],
            "tests": tests[:limit],
            "recommended_files": recommended_files[:limit],
            "truncated": any(len(items) >= limit for items in (callers, callees, imports, references)),
            "warnings": ["references 是语法级结果；需要类型感知的精确语义时请使用 LSP 复核"],
        }

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS code_index_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            row = conn.execute("SELECT value FROM code_index_meta WHERE key = 'schema_version'").fetchone()
            try:
                stored_version = int(row[0]) if row is not None else -1
            except (TypeError, ValueError):
                stored_version = -1
            if stored_version != CODE_INDEX_SCHEMA_VERSION:
                for table in ("code_files", "code_symbols", "code_calls", "code_imports", "code_references"):
                    conn.execute(f"DROP TABLE IF EXISTS {table}")
                conn.execute("DELETE FROM code_index_meta")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS code_files(
                   path TEXT PRIMARY KEY, language TEXT NOT NULL, content_hash TEXT NOT NULL,
                   mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL, indexed_at REAL NOT NULL)"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS code_symbols(
                   path TEXT NOT NULL, language TEXT NOT NULL, name TEXT NOT NULL, qualified_name TEXT NOT NULL,
                   kind TEXT NOT NULL, start_line INTEGER NOT NULL, start_column INTEGER NOT NULL,
                   end_line INTEGER NOT NULL, parent TEXT NOT NULL, signature TEXT NOT NULL)"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS code_calls(
                   path TEXT NOT NULL, language TEXT NOT NULL, caller TEXT NOT NULL,
                   qualified_callee TEXT NOT NULL, callee_name TEXT NOT NULL, line INTEGER NOT NULL)"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS code_imports(
                   path TEXT NOT NULL, language TEXT NOT NULL, module TEXT NOT NULL,
                   imported_name TEXT NOT NULL, line INTEGER NOT NULL)"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS code_references(
                   path TEXT NOT NULL, language TEXT NOT NULL, name TEXT NOT NULL,
                   line INTEGER NOT NULL, column INTEGER NOT NULL, reference_kind TEXT NOT NULL)"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_code_symbols_name ON code_symbols(name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_code_calls_terminal ON code_calls(callee_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_code_calls_qualified ON code_calls(qualified_callee)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_code_imports_name ON code_imports(imported_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_code_references_name ON code_references(name)")
            conn.execute(
                "INSERT OR REPLACE INTO code_index_meta(key, value) VALUES ('schema_version', ?)",
                (str(CODE_INDEX_SCHEMA_VERSION),),
            )
            generation = conn.execute("SELECT value FROM code_index_meta WHERE key = 'generation'").fetchone()
            self._generation = int(generation[0]) if generation else 0

    def _set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO code_index_meta(key, value) VALUES (?, ?)", (key, value))

    def _delete_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        with self._connect() as conn:
            for relative in paths:
                self._delete_path_rows(conn, relative)

    @staticmethod
    def _delete_path_rows(conn: sqlite3.Connection, relative: str) -> None:
        for table in ("code_files", "code_symbols", "code_calls", "code_imports", "code_references"):
            conn.execute(f"DELETE FROM {table} WHERE path = ?", (relative,))

    def _iter_files(self):
        for root, dirnames, filenames in os.walk(self.workspace_root):
            dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
            for filename in sorted(filenames):
                path = Path(root) / filename
                try:
                    supported = path.suffix.lower() in LANGUAGE_BY_SUFFIX and path.stat().st_size <= MAX_FILE_SIZE
                except OSError:
                    supported = False
                if supported:
                    yield path

    def _relative_candidate(self, raw_path: Path | str) -> str | None:
        path = Path(raw_path)
        if path.is_absolute() and (path == Path("/workspace") or Path("/workspace") in path.parents):
            path = self.workspace_root / path.relative_to("/workspace")
        elif not path.is_absolute():
            path = self.workspace_root / path
        try:
            relative = path.resolve(strict=False).relative_to(self.workspace_root).as_posix()
        except ValueError:
            return None
        return relative

    def _normalize_file(self, raw_path: str) -> str | None:
        relative = self._relative_candidate(raw_path)
        if relative is None:
            return None
        return relative if (self.workspace_root / relative).is_file() else None

    def _normalize_filter(self, raw_path: str) -> str:
        if not raw_path.strip():
            return ""
        relative = self._relative_candidate(raw_path)
        return relative or ""

    @staticmethod
    def _add_filters(clauses: list[str], values: list[Any], path_filter: str, language: str) -> None:
        if path_filter:
            clauses.append("(path = ? OR path LIKE ?)")
            values.extend([path_filter, path_filter.rstrip("/") + "/%"])
        if language:
            clauses.append("language = ?")
            values.append(language)

    @staticmethod
    def _node_text(node: Node | None, content: bytes) -> str:
        if node is None:
            return ""
        return content[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()

    def _identifier_texts(self, node: Node, content: bytes) -> list[str]:
        names: list[str] = []
        stack = list(node.named_children)
        while stack:
            child = stack.pop()
            if child.type in REFERENCE_NODES:
                value = self._node_text(child, content)
                if value:
                    names.append(value)
            stack.extend(child.named_children)
        return sorted(set(names))

    def _signature(self, node: Node, content: bytes) -> str:
        text = self._node_text(node, content).splitlines()[0] if node.end_byte > node.start_byte else ""
        return text[:500]

    @staticmethod
    def _terminal_name(value: str) -> str:
        normalized = value.rstrip("!").replace("::", ".")
        return normalized.rsplit(".", 1)[-1].strip()

    @staticmethod
    def _limit(value: Any) -> int:
        return max(1, min(int(value), 200))

    @staticmethod
    def _evidence_count(payload: dict[str, Any]) -> int:
        count = 0
        for key, value in payload.items():
            if key in {"warnings", "recommended_files"}:
                continue
            if key == "results" and isinstance(value, list):
                count += sum(
                    WorkspaceCodeIndex._evidence_count(item)
                    for item in value
                    if isinstance(item, dict)
                )
            elif isinstance(value, list):
                count += len(value)
        return count

    @staticmethod
    def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[Any, ...]] = set()
        result: list[dict[str, Any]] = []
        for row in rows:
            key = (row.get("path"), row.get("line", row.get("start_line")),
                   row.get("name", row.get("qualified_callee", row.get("module"))))
            if key in seen:
                continue
            seen.add(key)
            result.append(row)
        return result

    @staticmethod
    def _is_test_path(path: str) -> bool:
        name = Path(path).name.lower()
        return path.startswith("tests/") or "/tests/" in path or name.startswith("test_") or name.endswith("_test.go")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn
