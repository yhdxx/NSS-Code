from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import time
from typing import Any

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from mycodingagent.code_intelligence.index import (
    CALL_NODES,
    IMPORT_NODES,
    LANGUAGE_BY_SUFFIX,
    SYMBOL_NODES,
)


@dataclass(frozen=True)
class UnitRecord:
    path: str
    language: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int

    @property
    def canonical_name(self) -> str:
        return f"{self.path}::{self.qualified_name}"


@dataclass(frozen=True)
class CallRecord:
    path: str
    caller: str
    target: str
    line: int


class DynamicDependencyRuntime:
    """On-demand tree-sitter dependency queries with incremental import caching."""

    def __init__(self, workspace_root: Path, db_path: Path | str) -> None:
        self.workspace_root = workspace_root.resolve(strict=False)
        self.db_path = Path(db_path)
        self._lock = RLock()
        self._file_cache: dict[str, tuple[str, list[UnitRecord], list[CallRecord], list[str]]] = {}
        self._ensure_storage()

    def update_description(self, unit_name: str, description: str) -> dict[str, Any]:
        canonical = self._normalize_unit_name(unit_name)
        if canonical is None:
            return {"error_code": "invalid_unit_name", "error": "单位名称必须是 relative/path.ext::QualifiedName"}
        unit = self._resolve_unit(canonical)
        if unit is None:
            return {"error_code": "unit_not_found", "error": f"未找到单位：{unit_name}"}
        with self._connect() as conn:
            if description.strip():
                conn.execute(
                    "INSERT INTO unit_descriptions(canonical_unit_name, description, content_hash, updated_at) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(canonical_unit_name) DO UPDATE SET description=excluded.description, content_hash=excluded.content_hash, updated_at=excluded.updated_at",
                    (unit.canonical_name, description.strip(), self._file_hash(unit.path), time()),
                )
            else:
                conn.execute("DELETE FROM unit_descriptions WHERE canonical_unit_name = ?", (unit.canonical_name,))
        return {"status": "updated", "unit_name": unit.canonical_name}

    def query(self, unit_name: str) -> dict[str, Any]:
        canonical = self._normalize_unit_name(unit_name)
        if canonical is None:
            return {"error_code": "invalid_unit_name", "error": "单位名称必须是 relative/path.ext::QualifiedName"}
        target = self._resolve_unit(canonical)
        if target is None:
            return {"error_code": "unit_not_found", "error": f"未找到单位：{unit_name}"}
        payload: dict[str, Any] = {"unit": self._unit_payload(target)}
        callers, candidates, unresolved = self._callers(target)
        payload["callers"] = [self._unit_payload(item) for item in callers]
        if candidates:
            payload["candidate_files"] = sorted(candidates)
        if unresolved:
            payload["unresolved"] = unresolved
        return payload

    def _callees(self, target: UnitRecord) -> tuple[list[UnitRecord], list[str]]:
        _, _, calls, imports = self._parse_file(target.path)
        resolved: list[UnitRecord] = []
        unresolved: list[str] = []
        for call in calls:
            if call.caller != target.qualified_name and not call.caller.startswith(target.qualified_name + "."):
                continue
            matches = self._resolve_call(target.path, call.target, imports)
            if len(matches) == 1:
                if matches[0].canonical_name not in {item.canonical_name for item in resolved}:
                    resolved.append(matches[0])
            elif not matches:
                unresolved.append(call.target)
            else:
                unresolved.append(call.target)
        return resolved, sorted(set(unresolved))

    def _callers(self, target: UnitRecord) -> tuple[list[UnitRecord], set[str], list[str]]:
        candidates = self._import_candidates(target)
        callers: list[UnitRecord] = []
        unresolved: list[str] = []
        for path in sorted(candidates):
            _, units, calls, imports = self._parse_file(path)
            allowed = self._imports_target(imports, target)
            for call in calls:
                if not allowed and path != target.path:
                    continue
                match = self._target_matches(call.target, target, imports, path)
                if match is True:
                    caller = next((unit for unit in units if unit.qualified_name == call.caller), None)
                    if caller and caller.canonical_name not in {item.canonical_name for item in callers}:
                        callers.append(caller)
                elif match is None:
                    unresolved.append(f"{path}:{call.line}:{call.target}")
        return callers, candidates - {target.path}, unresolved

    def _import_candidates(self, target: UnitRecord) -> set[str]:
        candidates: set[str] = {target.path}
        with self._connect() as conn:
            rows = conn.execute("SELECT source_path, module, imported_name FROM dynamic_import_index").fetchall()
        for row in rows:
            if self._module_matches_path(str(row["module"]), target.path) or str(row["imported_name"] or "") in {target.qualified_name.split(".")[0], target.qualified_name}:
                candidates.add(str(row["source_path"]))
        # Populate the lightweight index lazily only when the cache has no hit.
        if len(candidates) == 1:
            for path in self._iter_source_files():
                self._parse_file(path)
            with self._connect() as conn:
                rows = conn.execute("SELECT source_path, module, imported_name FROM dynamic_import_index").fetchall()
            for row in rows:
                if self._module_matches_path(str(row["module"]), target.path) or str(row["imported_name"] or "") in {target.qualified_name.split(".")[0], target.qualified_name}:
                    candidates.add(str(row["source_path"]))
        return candidates

    def _resolve_call(self, source_path: str, call: str, imports: list[str]) -> list[UnitRecord]:
        local_units = self._parse_file(source_path)[1]
        exact = [unit for unit in local_units if unit.qualified_name == call or unit.qualified_name.endswith("." + call)]
        if exact:
            return exact
        terminal = call.rsplit(".", 1)[-1]
        imported_paths = self._imported_paths(source_path, imports)
        matches: list[UnitRecord] = []
        for path in imported_paths:
            matches.extend(unit for unit in self._parse_file(path)[1] if unit.qualified_name == call or unit.qualified_name.rsplit(".", 1)[-1] == terminal)
        return matches

    def _resolve_unit(self, canonical: str) -> UnitRecord | None:
        path, qualified = canonical.split("::", 1)
        units = self._parse_file(path)[1]
        matches = [item for item in units if item.qualified_name == qualified]
        return matches[0] if len(matches) == 1 else None

    def _parse_file(self, relative: str) -> tuple[str, list[UnitRecord], list[CallRecord], list[str]]:
        relative = Path(relative).as_posix()
        content = (self.workspace_root / relative).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        cached = self._file_cache.get(relative)
        if cached and cached[0] == digest:
            return cached
        language = LANGUAGE_BY_SUFFIX.get(Path(relative).suffix.lower())
        if language is None:
            result = (digest, [], [], [])
            self._file_cache[relative] = result
            return result
        tree = get_parser(language).parse(content)
        units: list[UnitRecord] = []
        calls: list[CallRecord] = []
        imports: list[str] = []
        stack: list[tuple[Node, str]] = [(tree.root_node, "")]
        while stack:
            node, parent = stack.pop()
            current_parent = parent
            kind = SYMBOL_NODES.get(language, {}).get(node.type)
            name_node = node.child_by_field_name("name") if kind else None
            if kind and name_node is not None:
                name = self._text(name_node, content)
                if name:
                    qualified = f"{parent}.{name}" if parent else name
                    units.append(UnitRecord(relative, language, qualified, kind, node.start_point.row + 1, node.end_point.row + 1))
                    current_parent = qualified
            if node.type in CALL_NODES:
                target = node.child_by_field_name("function") or node.child_by_field_name("name")
                call_target = self._text(target, content) if target is not None else ""
                if call_target:
                    calls.append(CallRecord(relative, parent, call_target, node.start_point.row + 1))
            if node.type in IMPORT_NODES:
                raw = self._text(node, content)[:1000]
                imports.append(raw)
            stack.extend((child, current_parent) for child in reversed(list(node.named_children)))
        result = (digest, units, calls, imports)
        self._file_cache[relative] = result
        self._store_imports(relative, digest, imports)
        return result

    def _store_imports(self, path: str, digest: str, imports: list[str]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM dynamic_import_index WHERE source_path = ?", (path,))
            for raw in imports:
                module, imported = self._import_parts(raw)
                conn.execute(
                    "INSERT INTO dynamic_import_index(source_path, module, imported_name, content_hash) VALUES (?, ?, ?, ?)",
                    (path, module, imported, digest),
                )

    @staticmethod
    def _import_parts(raw: str) -> tuple[str, str]:
        match = re.search(r"(?:from|import|use)\s+['\"]?([\w./:@-]+)(?:['\"]?)", raw)
        module = match.group(1) if match else raw
        names = re.findall(r"\b[A-Za-z_$][\w$]*\b", raw)
        imported = names[-1] if names else ""
        return module, imported

    def _imports_target(self, imports: list[str], target: UnitRecord) -> bool:
        return any(self._module_matches_path(self._import_parts(raw)[0], target.path) for raw in imports)

    def _target_matches(self, call: str, target: UnitRecord, imports: list[str], path: str) -> bool | None:
        if path == target.path:
            return call == target.qualified_name
        target_terminal = target.qualified_name.rsplit(".", 1)[-1]
        target_root = target.qualified_name.split(".", 1)[0]
        matches: list[bool] = []
        for raw in imports:
            module, imported = self._import_parts(raw)
            if not self._module_matches_path(module, target.path):
                continue
            bindings = self._import_bindings(raw, imported)
            if not bindings:
                continue
            for original, alias in bindings:
                if target.qualified_name == original or target.qualified_name.endswith("." + original):
                    if call == alias or call == f"{alias}.{target_terminal}" or call == target.qualified_name:
                        matches.append(True)
        if len(matches) == 1:
            return True
        if len(matches) > 1:
            return None
        return False

    @staticmethod
    def _import_bindings(raw: str, imported: str) -> list[tuple[str, str]]:
        from_match = re.search(r"\bfrom\s+[^\s]+\s+import\s+(.+)$", raw, re.DOTALL)
        if from_match:
            result: list[tuple[str, str]] = []
            for part in from_match.group(1).strip().strip("{}()").split(","):
                part = part.strip()
                if not part:
                    continue
                alias_match = re.fullmatch(r"([A-Za-z_$][\w$]*)\s+as\s+([A-Za-z_$][\w$]*)", part)
                if alias_match:
                    result.append((alias_match.group(1), alias_match.group(2)))
                else:
                    name_match = re.search(r"[A-Za-z_$][\w$]*", part)
                    if name_match:
                        result.append((name_match.group(0), name_match.group(0)))
            return result
        import_match = re.search(r"\bimport\s+(.+)$", raw, re.DOTALL)
        if import_match:
            result = []
            for part in import_match.group(1).split(","):
                part = part.strip().strip(";")
                alias_match = re.fullmatch(r"([\w.@/-]+)\s+as\s+([A-Za-z_$][\w$]*)", part)
                if alias_match:
                    module_name = alias_match.group(1).rsplit(".", 1)[-1]
                    result.append((module_name, alias_match.group(2)))
                else:
                    module_name = part.rsplit(".", 1)[-1]
                    if module_name:
                        result.append((module_name, module_name))
            return result
        bindings: list[tuple[str, str]] = []
        for part in re.split(r",|\n", raw):
            match = re.search(r"\b([A-Za-z_$][\w$]*)\s+as\s+([A-Za-z_$][\w$]*)\b", part)
            if match:
                bindings.append((match.group(1), match.group(2)))
                continue
            names = re.findall(r"\b[A-Za-z_$][\w$]*\b", part)
            for name in names:
                if name in {"from", "import", "use", "as", imported}:
                    continue
                bindings.append((name, name))
        if not bindings and imported:
            bindings.append((imported, imported))
        return bindings

    def _imported_paths(self, source_path: str, imports: list[str]) -> list[str]:
        modules = {self._import_parts(raw)[0] for raw in imports}
        paths: list[str] = []
        for path in self._iter_source_files():
            if path == source_path:
                continue
            if any(self._module_matches_path(module, path) for module in modules):
                paths.append(path)
        return paths

    @staticmethod
    def _module_matches_path(module: str, path: str) -> bool:
        module = module.strip().strip(".'\"").replace("/", ".")
        path_module = Path(path).with_suffix("").as_posix().replace("/", ".")
        return bool(module) and (module == path_module or module.endswith("." + path_module.split(".")[-1]) or path_module.endswith("." + module))

    def _unit_payload(self, unit: UnitRecord) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "unit_name": unit.canonical_name,
            "path": unit.path,
            "qualified_name": unit.qualified_name,
            "kind": unit.kind,
            "start_line": unit.start_line,
        }
        with self._connect() as conn:
            row = conn.execute("SELECT description FROM unit_descriptions WHERE canonical_unit_name = ?", (unit.canonical_name,)).fetchone()
        if row and str(row["description"] or "").strip():
            payload["description"] = str(row["description"])
        return payload

    def _normalize_unit_name(self, value: str) -> str | None:
        raw = str(value or "").strip().replace("\\", "/")
        if "::" not in raw:
            return None
        path, qualified = raw.split("::", 1)
        if not path or not qualified:
            return None
        candidate = (self.workspace_root / path).resolve(strict=False)
        try:
            relative = candidate.relative_to(self.workspace_root).as_posix()
        except ValueError:
            return None
        return f"{relative}::{qualified.strip()}"

    def _file_hash(self, relative: str) -> str:
        return hashlib.sha256((self.workspace_root / relative).read_bytes()).hexdigest()

    def _iter_source_files(self) -> list[str]:
        paths: list[str] = []
        for path in self.workspace_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in LANGUAGE_BY_SUFFIX:
                continue
            relative = path.relative_to(self.workspace_root).as_posix()
            if any(part in {".git", ".venv", "node_modules", "target", "dist", "build", "__pycache__"} for part in Path(relative).parts):
                continue
            paths.append(relative)
        return sorted(paths)

    @staticmethod
    def _text(node: Node | None, content: bytes) -> str:
        return content[node.start_byte:node.end_byte].decode("utf-8", errors="replace") if node is not None else ""

    def _ensure_storage(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS dynamic_import_index(source_path TEXT, module TEXT, imported_name TEXT, content_hash TEXT, PRIMARY KEY(source_path, module, imported_name))")
            conn.execute("CREATE TABLE IF NOT EXISTS unit_descriptions(canonical_unit_name TEXT PRIMARY KEY, description TEXT NOT NULL, content_hash TEXT NOT NULL, updated_at REAL NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
