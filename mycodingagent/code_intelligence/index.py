from __future__ import annotations

import hashlib
import gc
import os
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from time import time
from typing import Any

from tree_sitter import Node
from tree_sitter_language_pack import get_parser


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
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_spec": "type",
    },
    "typescript": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
    },
    "javascript": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
    },
    "rust": {
        "function_item": "function",
        "struct_item": "struct",
        "enum_item": "enum",
        "trait_item": "trait",
        "mod_item": "module",
    },
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
        "enum_declaration": "enum",
    },
}
CALL_NODES = {"call", "call_expression", "method_invocation", "macro_invocation"}


@dataclass(frozen=True)
class CodeSymbol:
    path: str
    language: str
    name: str
    kind: str
    start_line: int
    start_column: int
    end_line: int
    parent: str = ""
    signature: str = ""


@dataclass(frozen=True)
class CodeCall:
    path: str
    caller: str
    callee: str
    line: int


class WorkspaceCodeIndex:
    def __init__(self, workspace_root: Path, db_path: Path | str, *, max_files: int = 5000) -> None:
        self.workspace_root = workspace_root.resolve(strict=False)
        self.db_path = Path(db_path).expanduser()
        self.max_files = max_files
        self._init_db()

    def query(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        self.refresh()
        if operation == "outline":
            return self._outline(str(kwargs.get("path", "")))
        if operation in {"symbols", "definition_candidates"}:
            return self._symbols(
                str(kwargs.get("query", "")),
                exact=operation == "definition_candidates",
                limit=int(kwargs.get("limit", 50)),
            )
        if operation in {"callers", "callees"}:
            return self._calls(operation, str(kwargs.get("query", "")), int(kwargs.get("limit", 50)))
        return {"error": f"unsupported code index operation: {operation}"}

    def refresh(self) -> dict[str, int]:
        files = list(self._iter_files())[: self.max_files]
        current_paths = {path.relative_to(self.workspace_root).as_posix() for path in files}
        indexed = 0
        unchanged = 0
        with self._connect() as conn:
            existing = {row["path"]: row["content_hash"] for row in conn.execute("SELECT path, content_hash FROM code_files")}
        for path in files:
            relative = path.relative_to(self.workspace_root).as_posix()
            try:
                content = path.read_bytes()
            except OSError:
                continue
            content_hash = hashlib.sha256(content).hexdigest()
            if existing.get(relative) == content_hash:
                unchanged += 1
                continue
            self._index_file(relative, LANGUAGE_BY_SUFFIX[path.suffix.lower()], content, content_hash)
            indexed += 1
        removed = set(existing) - current_paths
        if removed:
            with self._connect() as conn:
                for relative in removed:
                    conn.execute("DELETE FROM code_files WHERE path = ?", (relative,))
                    conn.execute("DELETE FROM code_symbols WHERE path = ?", (relative,))
                    conn.execute("DELETE FROM code_calls WHERE path = ?", (relative,))
        return {"indexed": indexed, "unchanged": unchanged, "removed": len(removed)}

    def _index_file(self, relative: str, language: str, content: bytes, content_hash: str) -> None:
        # Keep the parser alive while walking nodes. Some grammar wheels tie the
        # language capsule lifetime to the parser and can crash if it is collected.
        parser = get_parser(language)
        tree = parser.parse(content)
        symbols: list[CodeSymbol] = []
        calls: list[CodeCall] = []

        gc_was_enabled = gc.isenabled()
        gc.disable()
        try:
            stack: list[tuple[Node, str]] = [(tree.root_node, "")]
            while stack:
                node, parent = stack.pop()
                current_parent = parent
                kind = SYMBOL_NODES.get(language, {}).get(node.type)
                if kind:
                    name_node = node.child_by_field_name("name")
                    name = self._node_text(name_node, content) if name_node is not None else ""
                    if name:
                        signature = self._signature(node, content)
                        symbols.append(
                            CodeSymbol(
                                path=relative,
                                language=language,
                                name=name,
                                kind=kind,
                                start_line=node.start_point.row + 1,
                                start_column=node.start_point.column,
                                end_line=node.end_point.row + 1,
                                parent=parent,
                                signature=signature,
                            )
                        )
                        current_parent = name
                if node.type in CALL_NODES:
                    target = node.child_by_field_name("function")
                    if target is None:
                        target = node.child_by_field_name("name")
                    callee = self._node_text(target, content) if target is not None else ""
                    if callee:
                        calls.append(CodeCall(relative, parent, callee[:200], node.start_point.row + 1))
                children = list(node.named_children)
                stack.extend((child, current_parent) for child in reversed(children))
        finally:
            if gc_was_enabled:
                gc.enable()
        with self._connect() as conn:
            conn.execute("DELETE FROM code_symbols WHERE path = ?", (relative,))
            conn.execute("DELETE FROM code_calls WHERE path = ?", (relative,))
            conn.execute(
                "INSERT OR REPLACE INTO code_files(path, language, content_hash, indexed_at) VALUES (?, ?, ?, ?)",
                (relative, language, content_hash, time()),
            )
            conn.executemany(
                """
                INSERT INTO code_symbols(path, language, name, kind, start_line, start_column, end_line, parent, signature)
                VALUES (:path, :language, :name, :kind, :start_line, :start_column, :end_line, :parent, :signature)
                """,
                [asdict(symbol) for symbol in symbols],
            )
            conn.executemany(
                "INSERT INTO code_calls(path, caller, callee, line) VALUES (:path, :caller, :callee, :line)",
                [asdict(call) for call in calls],
            )

    def _outline(self, raw_path: str) -> dict[str, Any]:
        relative = self._relative_path(raw_path)
        if relative is None:
            return {"error": f"path outside workspace or not found: {raw_path}", "symbols": []}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM code_symbols WHERE path = ? ORDER BY start_line, start_column", (relative,)
            ).fetchall()
        return {"path": relative, "symbols": [dict(row) for row in rows]}

    def _symbols(self, query: str, *, exact: bool, limit: int) -> dict[str, Any]:
        limit = max(1, min(limit, 200))
        with self._connect() as conn:
            if exact:
                rows = conn.execute(
                    "SELECT * FROM code_symbols WHERE lower(name) = lower(?) ORDER BY path, start_line LIMIT ?",
                    (query, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM code_symbols WHERE lower(name) LIKE lower(?) ORDER BY name, path LIMIT ?",
                    (f"%{query}%", limit),
                ).fetchall()
        return {"query": query, "symbols": [dict(row) for row in rows]}

    def _calls(self, operation: str, query: str, limit: int) -> dict[str, Any]:
        column = "callee" if operation == "callers" else "caller"
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT path, caller, callee, line FROM code_calls WHERE lower({column}) = lower(?) LIMIT ?",
                (query, max(1, min(limit, 200))),
            ).fetchall()
        return {"query": query, operation: [dict(row) for row in rows]}

    def _iter_files(self):
        for root, dirnames, filenames in os.walk(self.workspace_root):
            dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
            for filename in sorted(filenames):
                path = Path(root) / filename
                if path.suffix.lower() in LANGUAGE_BY_SUFFIX and path.stat().st_size <= 2_000_000:
                    yield path

    def _relative_path(self, raw_path: str) -> str | None:
        path = Path(raw_path)
        path = path if path.is_absolute() else self.workspace_root / path
        try:
            resolved = path.resolve(strict=False)
            relative = resolved.relative_to(self.workspace_root).as_posix()
        except ValueError:
            return None
        return relative if resolved.is_file() else None

    @staticmethod
    def _node_text(node: Node | None, content: bytes) -> str:
        if node is None:
            return ""
        return content[node.start_byte : node.end_byte].decode("utf-8", errors="replace").strip()

    def _signature(self, node: Node, content: bytes) -> str:
        text = self._node_text(node, content).splitlines()[0] if node.end_byte > node.start_byte else ""
        return text[:500]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS code_files(path TEXT PRIMARY KEY, language TEXT NOT NULL, content_hash TEXT NOT NULL, indexed_at REAL NOT NULL)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS code_symbols(
                    path TEXT NOT NULL, language TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
                    start_line INTEGER NOT NULL, start_column INTEGER NOT NULL, end_line INTEGER NOT NULL,
                    parent TEXT NOT NULL, signature TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS code_calls(path TEXT NOT NULL, caller TEXT NOT NULL, callee TEXT NOT NULL, line INTEGER NOT NULL)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_code_symbols_name ON code_symbols(name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_code_calls_callee ON code_calls(callee)")
