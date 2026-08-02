from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from threading import RLock, Thread
from time import sleep, time
from typing import Any, Callable

from mycodingagent.code_intelligence.agentignore import AgentIgnore
from mycodingagent.code_intelligence.index import WorkspaceCodeIndex
from mycodingagent.sqlite_utils import SQLITE_CONNECTION_FACTORY

UNKNOWN_DESCRIPTION = "暂未描述"
GRAPH_SCHEMA_VERSION = 1
BOOTSTRAP_DEPTH = 3
BOOTSTRAP_DEBOUNCE_SECONDS = 1.0


class ProjectGraphService:
    """Persistent module/unit views over the static workspace code index."""

    def __init__(self, workspace_root: Path, db_path: Path | str, code_index: WorkspaceCodeIndex) -> None:
        self.workspace_root = workspace_root.resolve(strict=False)
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.code_index = code_index
        self.agent_ignore = AgentIgnore(self.workspace_root)
        self._work_mode = lambda: "code"
        self._progress_callback: Callable[[str], None] | None = None
        self._dirty = True
        self._dirty_at = time()
        self._dirty_reason = "initial"
        self._last_filter_fingerprint = self._filter_fingerprint()
        self._background_thread: Thread | None = None
        self._lock = RLock()
        self._init_db()

    def set_work_mode_provider(self, provider) -> None:
        self._work_mode = provider

    def set_progress_callback(self, callback: Callable[[str], None] | None) -> None:
        self._progress_callback = callback

    def mark_dirty(self, path: Path | str, _is_delete: bool = False) -> None:
        with self._lock:
            self._dirty = True
            self._dirty_at = time()
            relative = self._relative_path(path)
            self._dirty_reason = "agentignore_changed" if relative == ".agentignore" else "workspace_changed"
            if self._background_thread is None or not self._background_thread.is_alive():
                self._background_thread = Thread(
                    target=self._background_refresh,
                    name="project-graph-refresh",
                    daemon=True,
                )
                self._background_thread.start()

    def work_mode_provider(self) -> str:
        return str(self._work_mode())

    def _background_refresh(self) -> None:
        while True:
            sleep(BOOTSTRAP_DEBOUNCE_SECONDS)
            with self._lock:
                if not self._dirty:
                    self._background_thread = None
                    return
                if time() - self._dirty_at < BOOTSTRAP_DEBOUNCE_SECONDS:
                    continue
                try:
                    self._refresh()
                except Exception as exc:
                    self._report_progress(f"后台刷新失败：{type(exc).__name__}: {exc}")
                    self._background_thread = None
                    return

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._refresh()
            return self._status_payload()

    def runtime_payload(self) -> dict[str, Any]:
        with self._lock:
            return self._status_payload()

    def _status_payload(self) -> dict[str, Any]:
        with self._connect() as conn:
            modules = int(conn.execute("SELECT COUNT(*) FROM graph_nodes WHERE kind = 'module'").fetchone()[0])
            units = int(conn.execute("SELECT COUNT(*) FROM graph_nodes WHERE kind NOT IN ('module', 'file')").fetchone()[0])
            stale = int(conn.execute("SELECT COUNT(*) FROM graph_descriptions WHERE status = 'stale'").fetchone()[0])
        return {
            "available": True,
            "generation": self._generation(),
            "modules": modules,
            "units": units,
            "stale_descriptions": stale,
            "workspace_root": "/workspace",
        }

    def architecture(self, module: str = "", *, depth: int = BOOTSTRAP_DEPTH, bootstrap: bool = False) -> dict[str, Any]:
        with self._lock:
            self._ensure_fresh()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM graph_nodes WHERE kind = 'module' ORDER BY path"
                ).fetchall()
                resolution = self._resolve_module(module, rows)
                if isinstance(resolution, dict):
                    return resolution
                target = resolution
                target_path = str(target["path"])
                max_depth = max(1, min(int(depth or BOOTSTRAP_DEPTH), BOOTSTRAP_DEPTH))
                target_depth = self._path_depth(target_path)
                subtree = [
                    row for row in rows
                    if target_path == "."
                    or str(row["path"]) == target_path
                    or str(row["path"]).startswith(target_path + "/")
                ]
                visible_subtree = [
                    row for row in subtree
                    if self._path_depth(str(row["path"])) - target_depth < max_depth
                ]
                descriptions = self._descriptions(conn, [str(row["id"]) for row in subtree])
                counts = self._module_counts(conn, [str(row["id"]) for row in visible_subtree])
                language_stats = self._meta_json(conn, "language_stats", {})
                filter_stats = self._meta_json(conn, "filter_stats", {})
                primary_language = self._meta_value(conn, "primary_language", "")
                navigation_hash = self._navigation_hash(conn)
            return {
                "graph": "project_architecture",
                "generation": self._generation(),
                "bootstrap": bool(bootstrap),
                "depth": max_depth,
                "navigation_hash": navigation_hash,
                "primary_language": primary_language,
                "language_stats": language_stats,
                "filter_stats": filter_stats,
                "module": self._module_payload(target, descriptions, counts),
                "root_module": self._module_payload(target, descriptions, counts),
                "modules": [self._module_payload(row, descriptions, counts) for row in visible_subtree],
                "children": [
                    self._module_payload(row, descriptions, counts)
                    for row in visible_subtree
                    if str(row["parent_id"] or "") == str(target["id"])
                ],
            }

    def bootstrap_messages(self) -> list[dict[str, Any]]:
        payload = self.architecture("", depth=BOOTSTRAP_DEPTH, bootstrap=True)
        if "error_code" in payload:
            return []
        navigation_hash = str(payload.get("navigation_hash") or "")
        generation = int(payload.get("generation") or 0)
        call_id = f"project_graph_bootstrap_{generation}_{navigation_hash[:12]}"
        arguments = json.dumps(
            {"module": "", "depth": BOOTSTRAP_DEPTH, "bootstrap": True},
            ensure_ascii=False,
            sort_keys=True,
        )
        metadata = {
            "project_graph_bootstrap": True,
            "generation": generation,
            "navigation_hash": navigation_hash,
        }
        return [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": "ProjectArchitecture", "arguments": arguments},
                    }
                ],
                "metadata": metadata,
            },
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                "metadata": metadata,
            },
        ]

    def dependency_graph(self, module: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_fresh()
            with self._connect() as conn:
                modules = conn.execute("SELECT * FROM graph_nodes WHERE kind = 'module' ORDER BY path").fetchall()
                resolution = self._resolve_module(module, modules)
                if isinstance(resolution, dict):
                    return resolution
                target = resolution
                module_id = str(target["id"])
                child_modules = [row for row in modules if str(row["parent_id"]) == module_id]
                units = conn.execute(
                    "SELECT * FROM graph_nodes WHERE module_id = ? AND kind NOT IN ('module', 'file') ORDER BY path, start_line, name",
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
            self._ensure_fresh()
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

    def update_descriptions(self, updates: list[dict[str, str]]) -> dict[str, Any]:
        if not updates:
            return self._error("updates_required", "updates 不能为空")
        results: list[dict[str, Any]] = []
        for item in updates:
            result = self.update_description(
                str(item.get("target") or ""),
                str(item.get("description") or ""),
                str(item.get("content_hash") or ""),
            )
            results.append(result)
        failed = [item for item in results if "error_code" in item]
        return {
            "status": "updated" if not failed else "partial_failure",
            "updated": len(results) - len(failed),
            "failed": len(failed),
            "results": results,
        }

    def _refresh(self) -> None:
        started_at = time()
        self._report_progress("正在刷新静态代码索引...")
        static_graph = self.code_index.static_graph_snapshot()
        self._report_progress(
            f"静态索引完成：{len(static_graph['symbols'])} 个符号，{len(static_graph['calls'])} 条调用。"
        )
        self.agent_ignore.reload()
        files = {
            str(item["path"]): str(item["content_hash"])
            for item in static_graph.get("files", [])
        }
        self._report_progress(f"文件扫描完成：{len(files)} 个文件进入项目图谱。")
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
            seen_unit_ids: set[str] = set()
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
                    if unit_id in seen_unit_ids:
                        duplicate_key = (
                            "unit",
                            f"{path}:{qualified}:{symbol.get('kind')}:{symbol.get('start_line')}",
                        )
                        unit_id = self._id(*duplicate_key)
                        duplicate_index = 2
                        while unit_id in seen_unit_ids:
                            unit_id = self._id(duplicate_key[0], f"{duplicate_key[1]}:{duplicate_index}")
                            duplicate_index += 1
                    seen_unit_ids.add(unit_id)
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
            self._report_progress(f"正在写入图谱：{len(nodes)} 个节点...")
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
            conn.execute(
                "INSERT OR REPLACE INTO graph_meta(key, value) VALUES ('language_stats', ?)",
                (json.dumps(static_graph.get("language_stats", {}), ensure_ascii=False, sort_keys=True),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO graph_meta(key, value) VALUES ('primary_language', ?)",
                (str(static_graph.get("primary_language", "")),),
            )
            filter_stats = {
                **dict(static_graph.get("filter_stats", {})),
                "agentignore_fingerprint": self._filter_fingerprint(),
                "graph_input": "indexed_code_files",
            }
            conn.execute(
                "INSERT OR REPLACE INTO graph_meta(key, value) VALUES ('filter_stats', ?)",
                (json.dumps(filter_stats, ensure_ascii=False, sort_keys=True),),
            )
            navigation_hash = self._compute_navigation_hash(conn, depth=BOOTSTRAP_DEPTH)
            conn.execute(
                "INSERT OR REPLACE INTO graph_meta(key, value) VALUES ('navigation_hash', ?)",
                (navigation_hash,),
            )
            self._last_filter_fingerprint = filter_stats["agentignore_fingerprint"]
        self._report_progress(
            f"项目图谱完成：generation={generation}，耗时 {time() - started_at:.1f} 秒。"
        )
        self._dirty = False

    def _ensure_fresh(self) -> None:
        if self._dirty or self._generation() == 0:
            self._refresh()

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
        conn = sqlite3.connect(self.db_path, factory=SQLITE_CONNECTION_FACTORY)
        conn.row_factory = sqlite3.Row
        return conn

    def _module_counts(
        self,
        conn: sqlite3.Connection,
        module_ids: list[str],
    ) -> dict[str, dict[str, int]]:
        if not module_ids:
            return {}
        modules = [dict(row) for row in conn.execute("SELECT id, path, parent_id FROM graph_nodes WHERE kind = 'module'")]
        units = [dict(row) for row in conn.execute("SELECT module_id FROM graph_nodes WHERE kind NOT IN ('module', 'file')")]
        module_path_by_id = {str(row["id"]): str(row["path"]) for row in modules}
        counts = {
            str(row["id"]): {
                "recursive_unit_count": 0,
                "child_module_count": 0,
            }
            for row in modules
            if str(row["id"]) in set(module_ids)
        }
        for row in modules:
            parent_id = str(row["parent_id"] or "")
            if parent_id in counts:
                counts[parent_id]["child_module_count"] += 1
        for unit in units:
            unit_module_path = module_path_by_id.get(str(unit["module_id"]), "")
            for module_id in counts:
                module_path = module_path_by_id.get(module_id, "")
                if (
                    module_path == "."
                    or unit_module_path == module_path
                    or unit_module_path.startswith(module_path + "/")
                ):
                    counts[module_id]["recursive_unit_count"] += 1
        return counts

    def _navigation_hash(self, conn: sqlite3.Connection) -> str:
        value = self._meta_value(conn, "navigation_hash", "")
        return value or self._compute_navigation_hash(conn, depth=BOOTSTRAP_DEPTH)

    def _compute_navigation_hash(self, conn: sqlite3.Connection, *, depth: int) -> str:
        rows = conn.execute("SELECT id, path, name, parent_id FROM graph_nodes WHERE kind = 'module' ORDER BY path").fetchall()
        visible = [
            {
                "id": row["id"],
                "path": row["path"],
                "name": row["name"],
                "parent_id": row["parent_id"],
            }
            for row in rows
            if self._path_depth(str(row["path"])) < depth
        ]
        payload = {
            "modules": visible,
            "agentignore_fingerprint": self._filter_fingerprint(),
        }
        return self._hash_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))

    @staticmethod
    def _meta_value(conn: sqlite3.Connection, key: str, default: str = "") -> str:
        row = conn.execute("SELECT value FROM graph_meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row is not None else default

    @classmethod
    def _meta_json(cls, conn: sqlite3.Connection, key: str, default: Any) -> Any:
        raw = cls._meta_value(conn, key, "")
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _path_depth(path: str) -> int:
        if not path or path == ".":
            return 0
        return len(Path(path).parts)

    def _relative_path(self, path: Path | str) -> str:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        try:
            return candidate.resolve(strict=False).relative_to(self.workspace_root).as_posix()
        except ValueError:
            return str(path)

    def _filter_fingerprint(self) -> str:
        try:
            return self._hash_bytes((self.workspace_root / ".agentignore").read_bytes())
        except OSError:
            return ""

    def _report_progress(self, message: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(message)

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

    def _module_payload(
        self,
        row: sqlite3.Row,
        descriptions: dict[str, dict[str, Any]],
        counts: dict[str, dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        description = descriptions.get(str(row["id"]), {})
        payload = {
            "id": row["id"],
            "name": row["name"],
            "path": row["path"],
            "parent_id": row["parent_id"],
            "description": description.get("description", UNKNOWN_DESCRIPTION),
            "content_hash": row["content_hash"],
            "status": description.get("status", "undescribed"),
        }
        if counts is not None:
            payload.update(counts.get(str(row["id"]), {"recursive_unit_count": 0, "child_module_count": 0}))
        return payload

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
