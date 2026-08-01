from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from threading import RLock
from time import time
from typing import Any

from mycodingagent.code_intelligence.index import LANGUAGE_BY_SUFFIX, SKIP_DIRS, WorkspaceCodeIndex

UNKNOWN_DESCRIPTION = "暂未描述"
GRAPH_SCHEMA_VERSION = 1


class ProjectGraphService:
    """Persistent module/unit views over the static workspace code index."""

    def __init__(self, workspace_root: Path, db_path: Path | str, code_index: WorkspaceCodeIndex) -> None:
        self.workspace_root = workspace_root.resolve(strict=False)
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.code_index = code_index
        self._work_mode = lambda: "code"
        self._lock = RLock()
        self._init_db()

    def set_work_mode_provider(self, provider) -> None:
        self._work_mode = provider

    def work_mode_provider(self) -> str:
        return str(self._work_mode())

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._refresh()
            return self._status_payload()

    def runtime_payload(self) -> dict[str, Any]:
        with self._lock:
            self._refresh()
            return self._status_payload()

    def _status_payload(self) -> dict[str, Any]:
        with self._connect() as conn:
            modules = int(conn.execute("SELECT COUNT(*) FROM graph_nodes WHERE kind = 'module'").fetchone()[0])
            units = int(conn.execute("SELECT COUNT(*) FROM graph_nodes WHERE kind != 'module'").fetchone()[0])
            stale = int(conn.execute("SELECT COUNT(*) FROM graph_descriptions WHERE status = 'stale'").fetchone()[0])
        return {
            "available": True,
            "generation": self._generation(),
            "modules": modules,
            "units": units,
            "stale_descriptions": stale,
            "workspace_root": "/workspace",
        }

    def architecture(self, module: str = "") -> dict[str, Any]:
        with self._lock:
            self._refresh()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM graph_nodes WHERE kind = 'module' ORDER BY path"
                ).fetchall()
                resolution = self._resolve_module(module, rows)
                if isinstance(resolution, dict):
                    return resolution
                target = resolution
                target_path = str(target["path"])
                subtree = [
                    row for row in rows
                    if target_path == "."
                    or str(row["path"]) == target_path
                    or str(row["path"]).startswith(target_path + "/")
                ]
                descriptions = self._descriptions(conn, [str(row["id"]) for row in subtree])
            return {
                "graph": "project_architecture",
                "generation": self._generation(),
                "module": self._module_payload(target, descriptions),
                "root_module": self._module_payload(target, descriptions),
                "modules": [self._module_payload(row, descriptions) for row in subtree],
                "children": [
                    self._module_payload(row, descriptions)
                    for row in subtree
                    if str(row["parent_id"] or "") == str(target["id"])
                ],
            }

    def dependency_graph(self, module: str) -> dict[str, Any]:
        with self._lock:
            self._refresh()
            with self._connect() as conn:
                modules = conn.execute("SELECT * FROM graph_nodes WHERE kind = 'module' ORDER BY path").fetchall()
                resolution = self._resolve_module(module, modules)
                if isinstance(resolution, dict):
                    return resolution
                target = resolution
                module_id = str(target["id"])
                child_modules = [row for row in modules if str(row["parent_id"]) == module_id]
                units = conn.execute(
                    "SELECT * FROM graph_nodes WHERE module_id = ? AND kind != 'module' ORDER BY path, start_line, name",
                    (module_id,),
                ).fetchall()
                ids = [str(row["id"]) for row in units] + [module_id]
                descriptions = self._descriptions(
                    conn,
                    ids + [str(row["id"]) for row in child_modules],
                )
                placeholders = ",".join("?" for _ in ids)
                edges = conn.execute(
                    f"SELECT * FROM graph_edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders}) ORDER BY edge_type, source_id",
                    (*ids, *ids),
                ).fetchall()
            return {
                "graph": "unit_dependency",
                "generation": self._generation(),
                "module": self._module_payload(target, descriptions),
                "architecture": [self._module_payload(row, descriptions) for row in child_modules],
                "units": [self._unit_payload(row, descriptions) for row in units],
                "edges": [dict(row) for row in edges],
            }

    def update_description(self, target: str, description: str, content_hash: str) -> dict[str, Any]:
        with self._lock:
            self._refresh()
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM graph_nodes WHERE id = ?", (target.strip(),)).fetchone()
                if row is None:
                    rows = conn.execute("SELECT * FROM graph_nodes WHERE name = ?", (target.strip(),)).fetchall()
                    if len(rows) != 1:
                        return self._error("target_ambiguous", f"请使用唯一的模块或单位 ID：{target}")
                    row = rows[0]
                if str(row["content_hash"]) != content_hash:
                    return self._error("stale_target", "目标内容已变化，请重新读取图谱后再更新 description")
                now = time()
                conn.execute(
                    "INSERT OR REPLACE INTO graph_descriptions(node_id, description, content_hash, status, updated_at) VALUES (?, ?, ?, 'verified', ?)",
                    (row["id"], description.strip() or UNKNOWN_DESCRIPTION, content_hash, now),
                )
            return {"status": "updated", "id": row["id"], "content_hash": content_hash}

    def _refresh(self) -> None:
        static_graph = self.code_index.static_graph_snapshot()
        files = self._workspace_files()
        with self._connect() as conn:
            old = {str(row["id"]): str(row["content_hash"]) for row in conn.execute("SELECT id, content_hash FROM graph_nodes")}
            nodes: list[dict[str, Any]] = []
            root_id = self._id("module", ".")
            module_ids: dict[str, str] = {".": root_id}
            for path in files:
                parts = Path(path).parts[:-1]
                current = "."
                for part in parts:
                    current = part if current == "." else f"{current}/{part}"
                    module_ids.setdefault(current, self._id("module", current))
            for module, module_id in sorted(module_ids.items()):
                parent = "" if module == "." else ("." if "/" not in module else module.rsplit("/", 1)[0])
                module_files = {path: digest for path, digest in files.items() if module == "." or path.startswith(module + "/")}
                nodes.append(
                    self._node(
                        module_id,
                        module,
                        "project" if module == "." else Path(module).name,
                        "module",
                        module_ids[parent] if parent else "",
                        self._hash_files(module_files),
                    )
                )
            for path, content_hash in files.items():
                parts = Path(path).parts[:-1]
                module = "."
                for part in parts:
                    module = part if module == "." else f"{module}/{part}"
                file_id = self._id("file", path)
                nodes.append(self._node(file_id, path, Path(path).name, "file", module_ids[module], content_hash))
                outline = [symbol for symbol in static_graph["symbols"] if symbol["path"] == path]
                try:
                    source_lines = (self.workspace_root / path).read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    source_lines = []
                for symbol in outline:
                    qualified = str(symbol.get("qualified_name") or symbol.get("name"))
                    unit_id = self._id("unit", f"{path}:{qualified}")
                    start = max(1, int(symbol.get("start_line") or 1))
                    end = max(start, int(symbol.get("end_line") or start))
                    source_fragment = "\n".join(source_lines[start - 1:end])
                    unit_hash = self._hash_text(source_fragment or json.dumps(symbol, sort_keys=True))
                    unit = self._node(unit_id, path, str(symbol.get("name")), str(symbol.get("kind")), file_id, unit_hash)
                    unit["qualified_name"] = qualified
                    unit["start_line"] = int(symbol.get("start_line") or 0)
                    nodes.append(unit)
            conn.execute("DELETE FROM graph_nodes")
            conn.execute("DELETE FROM graph_edges")
            conn.executemany(
                "INSERT INTO graph_nodes(id, path, name, kind, parent_id, module_id, content_hash, start_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(item["id"], item["path"], item["name"], item["kind"], item["parent_id"], self._module_for(item, module_ids), item["content_hash"], item.get("start_line", 0)) for item in nodes],
            )
            self._insert_static_edges(conn, nodes, static_graph["calls"])
            valid = {item["id"] for item in nodes}
            conn.execute("DELETE FROM graph_descriptions WHERE node_id NOT IN ({})".format(",".join("?" for _ in valid)), tuple(valid)) if valid else conn.execute("DELETE FROM graph_descriptions")
            for item in nodes:
                if item["id"] in old and old[item["id"]] != item["content_hash"]:
                    conn.execute("UPDATE graph_descriptions SET status = 'stale' WHERE node_id = ?", (item["id"],))
            generation = int(conn.execute("SELECT value FROM graph_meta WHERE key = 'generation'").fetchone()[0]) if conn.execute("SELECT 1 FROM graph_meta WHERE key = 'generation'").fetchone() else 0
            if old != {item["id"]: item["content_hash"] for item in nodes}:
                generation += 1
            conn.execute("INSERT OR REPLACE INTO graph_meta(key, value) VALUES ('generation', ?)", (str(generation),))

    def _insert_static_edges(
        self,
        conn: sqlite3.Connection,
        nodes: list[dict[str, Any]],
        calls: list[dict[str, Any]],
    ) -> None:
        by_parent = {(str(item["parent_id"]), str(item["name"])): str(item["id"]) for item in nodes}
        by_qualified: dict[tuple[str, str], str] = {}
        by_name: dict[str, list[str]] = {}
        for item in nodes:
            if item["kind"] not in {"module", "file"}:
                by_name.setdefault(str(item["name"]), []).append(str(item["id"]))
                by_qualified[(str(item["parent_id"]), str(item.get("qualified_name") or item["name"]))] = str(item["id"])
            if item["parent_id"]:
                conn.execute(
                    "INSERT OR IGNORE INTO graph_edges(source_id, target_id, edge_type, confidence) VALUES (?, ?, 'contains', 'exact')",
                    (item["parent_id"], item["id"]),
                )
        file_ids = {str(item["path"]): str(item["id"]) for item in nodes if item["kind"] == "file"}
        for call in calls:
            file_id = file_ids.get(str(call["path"]), "")
            source = by_qualified.get((file_id, str(call["caller"]))) or by_parent.get(
                (file_id, str(call["caller"]).rsplit(".", 1)[-1])
            )
            targets = by_name.get(str(call["callee_name"]), [])
            if source and targets:
                for target in targets:
                    conn.execute(
                        "INSERT OR IGNORE INTO graph_edges(source_id, target_id, edge_type, confidence, evidence_path, evidence_line) VALUES (?, ?, 'calls', 'syntactic', ?, ?)",
                        (source, target, call["path"], call["line"]),
                    )

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS graph_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS graph_nodes(id TEXT PRIMARY KEY, path TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, parent_id TEXT NOT NULL, module_id TEXT NOT NULL, content_hash TEXT NOT NULL, start_line INTEGER NOT NULL DEFAULT 0)")
            conn.execute("CREATE TABLE IF NOT EXISTS graph_edges(source_id TEXT NOT NULL, target_id TEXT NOT NULL, edge_type TEXT NOT NULL, confidence TEXT NOT NULL, evidence_path TEXT NOT NULL DEFAULT '', evidence_line INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(source_id, target_id, edge_type, evidence_path, evidence_line))")
            conn.execute("CREATE TABLE IF NOT EXISTS graph_descriptions(node_id TEXT PRIMARY KEY, description TEXT NOT NULL, content_hash TEXT NOT NULL, status TEXT NOT NULL, updated_at REAL NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _workspace_files(self) -> dict[str, str]:
        result = {}
        for root, dirs, names in os.walk(self.workspace_root):
            dirs[:] = sorted(item for item in dirs if item not in SKIP_DIRS)
            for name in names:
                path = Path(root) / name
                try:
                    if path.stat().st_size > 2_000_000:
                        continue
                    result[path.relative_to(self.workspace_root).as_posix()] = self._hash_bytes(path.read_bytes())
                except OSError:
                    continue
        return result

    def _resolve_module(self, value: str, rows: list[sqlite3.Row]) -> sqlite3.Row | dict[str, Any]:
        value = value.strip()
        if value in {"", "/", "/workspace", str(self.workspace_root)}:
            value = "."
        else:
            value = value.strip("/") or "."
        matches = [row for row in rows if value in {str(row["id"]), str(row["path"]), str(row["name"])}]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            return self._error("module_not_found", f"未找到项目模块：{value}")
        return {
            **self._error("module_ambiguous", f"模块名称不唯一，请改用模块 ID 或路径：{value}"),
            "candidates": [{"id": row["id"], "path": row["path"]} for row in matches],
        }

    def _descriptions(self, conn: sqlite3.Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        return {str(row["node_id"]): dict(row) for row in conn.execute("SELECT * FROM graph_descriptions WHERE node_id IN ({})".format(",".join("?" for _ in ids)), ids)}

    def _module_payload(self, row: sqlite3.Row, descriptions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        description = descriptions.get(str(row["id"]), {})
        return {"id": row["id"], "name": row["name"], "path": row["path"], "parent_id": row["parent_id"], "description": description.get("description", UNKNOWN_DESCRIPTION), "content_hash": row["content_hash"], "status": description.get("status", "undescribed")}

    def _unit_payload(self, row: sqlite3.Row, descriptions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {**self._module_payload(row, descriptions), "kind": row["kind"], "start_line": row["start_line"]}

    @staticmethod
    def _node(node_id: str, path: str, name: str, kind: str, parent_id: str, content_hash: str) -> dict[str, Any]:
        return {"id": node_id, "path": path, "name": name, "kind": kind, "parent_id": parent_id, "content_hash": content_hash, "start_line": 0}

    @staticmethod
    def _module_for(item: dict[str, Any], modules: dict[str, str]) -> str:
        if item["kind"] == "module":
            return item["id"]
        path = item["path"] if item["kind"] == "file" else item["path"].split(":", 1)[0]
        module = str(Path(path).parent) if "/" in path else "."
        return modules.get(module, modules["."])

    @staticmethod
    def _id(kind: str, value: str) -> str:
        return f"{kind}_{hashlib.sha256(f'{kind}:{value}'.encode()).hexdigest()[:16]}"

    @staticmethod
    def _hash_bytes(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _hash_text(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _hash_files(files: dict[str, str]) -> str:
        return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {"error_code": code, "error": message}

    def _generation(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM graph_meta WHERE key = 'generation'").fetchone()
        return int(row[0]) if row else 0
