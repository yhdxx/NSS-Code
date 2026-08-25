from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from time import time
from typing import Any, Callable
from uuid import uuid4


WORK_STATUSES = frozenset({"pending", "modified"})
TEST_STATUSES = frozenset({"untested", "failed", "passed"})
TASK_STATUSES = frozenset({"active", "completed", "interrupted", "superseded"})


class PathTaskGraphRuntime:
    """Session-scoped path range and agent-reported status state."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        store: Any | None = None,
        session_id_provider: Callable[[], str] | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve(strict=False)
        self.store = store
        self.session_id_provider = session_id_provider or (lambda: "")
        self._current: dict[str, Any] | None = None

    @property
    def current(self) -> dict[str, Any] | None:
        session_id = self._session_id()
        if self._current is None or str(self._current.get("session_id") or "") != session_id:
            loader = getattr(self.store, "load_active_task_graph", None) if self.store else None
            self._current = loader(session_id) if callable(loader) and session_id else None
        return copy.deepcopy(self._current) if self._current is not None else None

    def context_boundary(self) -> dict[str, Any] | None:
        session_id = self._session_id()
        loader = getattr(self.store, "load_latest_task_graph", None) if self.store else None
        value = loader(session_id) if callable(loader) and session_id else self.current
        return copy.deepcopy(value) if isinstance(value, dict) else None

    def completed_boundaries(self) -> list[dict[str, Any]]:
        session_id = self._session_id()
        loader = getattr(self.store, "load_completed_task_graphs", None) if self.store else None
        if callable(loader) and session_id:
            return [copy.deepcopy(item) for item in loader(session_id)]
        graph = self.current
        return [graph] if isinstance(graph, dict) and graph.get("status") == "completed" else []

    async def create(self, paths: list[str], *, plan_id: str = "", plan_step_id: str = "") -> dict[str, Any]:
        normalized: list[str] = []
        for raw in paths:
            path = self._normalize(raw)
            if path is None:
                return {"error_code": "path_outside_workspace", "error": f"路径位于工作区之外：{raw}"}
            if path not in normalized:
                normalized.append(path)
        if not normalized:
            return {"error_code": "paths_required", "error": "paths 不能为空"}

        selected: set[str] = set()
        for relative in normalized:
            selected.add(relative)
            current = Path(relative).parent
            while str(current) not in {"", "."}:
                selected.add(current.as_posix())
                current = current.parent
            absolute = self.workspace_root / relative
            if absolute.is_dir():
                for child in absolute.rglob("*"):
                    if child.is_file() or child.is_dir():
                        child_rel = child.relative_to(self.workspace_root).as_posix()
                        if not any(part in {".git", ".venv", "node_modules", "__pycache__"} for part in Path(child_rel).parts):
                            selected.add(child_rel)

        paths_sorted = sorted(selected, key=lambda value: (len(Path(value).parts), value))
        nodes: list[dict[str, Any]] = []
        for path in paths_sorted:
            absolute = self.workspace_root / path
            kind = "directory" if absolute.is_dir() else "file"
            parent_path = Path(path).parent.as_posix()
            parent_id = self._node_id(parent_path) if parent_path != "." and parent_path in selected else None
            nodes.append({
                "id": self._node_id(path),
                "kind": kind,
                "path": path,
                "parent_id": parent_id,
                "work_status": "pending",
                "test_status": "untested",
            })
        graph = {
            "task_graph_id": uuid4().hex,
            "session_id": self._session_id(),
            "status": "active",
            "plan_id": plan_id.strip(),
            "plan_step_id": plan_step_id.strip(),
            "targets": normalized,
            "nodes": nodes,
            "edges": [
                {"source_id": node["parent_id"], "target_id": node["id"], "edge_type": "contains"}
                for node in nodes if node["parent_id"]
            ],
            "note": "",
            "start_message_index": None,
            "end_message_index": None,
            "created_at": time(),
            "updated_at": time(),
        }
        session_id = self._session_id()
        if self.store and session_id:
            supersede = getattr(self.store, "supersede_active_task_graphs", None)
            save = getattr(self.store, "save_task_graph", None)
            if callable(supersede):
                supersede(session_id)
            if callable(save):
                save(graph)
        self._current = graph
        return copy.deepcopy(graph)

    async def update(self, task_graph_id: str, updates: list[dict[str, Any]], *, task_status: str = "", note: str = "") -> dict[str, Any]:
        graph = self.current
        if graph is None or str(graph.get("task_graph_id")) != task_graph_id.strip():
            return {"error_code": "task_graph_not_found", "error": "当前会话没有这个任务图"}
        by_id = {str(node["id"]): node for node in graph.get("nodes", [])}
        by_path = {str(node["path"]): node for node in graph.get("nodes", [])}
        for update in updates:
            node_id = str(update.get("node_id") or update.get("id") or "")
            node = by_id.get(node_id) or by_path.get(str(update.get("path") or ""))
            if node is None:
                return {"error_code": "node_not_found", "error": "节点不属于当前任务图"}
            if update.get("work_status") is not None:
                value = str(update["work_status"])
                if value not in WORK_STATUSES:
                    return {"error_code": "invalid_work_status", "error": "work_status 必须是 pending 或 modified"}
                node["work_status"] = value
            if update.get("test_status") is not None:
                value = str(update["test_status"])
                if value not in TEST_STATUSES:
                    return {"error_code": "invalid_test_status", "error": "test_status 必须是 untested、failed 或 passed"}
                node["test_status"] = value
        if task_status:
            if task_status not in TASK_STATUSES:
                return {"error_code": "invalid_task_status", "error": "task_status 不合法"}
            graph["status"] = task_status
        if note:
            graph["note"] = note.strip()
        graph["updated_at"] = time()
        save = getattr(self.store, "save_task_graph", None) if self.store else None
        if callable(save):
            save(graph)
        self._current = graph
        return copy.deepcopy(graph)

    def set_start_boundary(self, message_index: int) -> None:
        graph = self.current
        if graph is None or graph.get("start_message_index") is not None:
            return
        graph["start_message_index"] = max(0, int(message_index))
        graph["updated_at"] = time()
        self._persist(graph)

    def tag_message(self, message: dict[str, Any]) -> None:
        graph = self.current
        if graph is not None and graph.get("status") == "active" and graph.get("start_message_index") is not None:
            message.setdefault("metadata", {})["task_graph_id"] = str(graph.get("task_graph_id") or "")

    def finish_after_final(self, message_index: int) -> None:
        graph = self.current
        if graph is None or graph.get("status") != "active":
            return
        graph["status"] = "completed"
        graph["end_message_index"] = max(0, int(message_index))
        graph["updated_at"] = time()
        self._persist(graph)

    def mark_interrupted(self) -> None:
        graph = self.current
        if graph is None or graph.get("status") != "active":
            return
        graph["status"] = "interrupted"
        graph["updated_at"] = time()
        self._persist(graph)

    def runtime_payload(self) -> dict[str, Any] | None:
        return self.current

    def _persist(self, graph: dict[str, Any]) -> None:
        self._current = graph
        save = getattr(self.store, "save_task_graph", None) if self.store else None
        if callable(save):
            save(graph)

    def _normalize(self, raw: str) -> str | None:
        value = str(raw or "").strip().replace("\\", "/")
        if value in {"", ".", "/workspace", "/workspace/"}:
            return "."
        if value.startswith("/workspace/"):
            value = value[len("/workspace/"):]
        candidate = (self.workspace_root / value).resolve(strict=False) if not value.startswith("/") else Path(value).resolve(strict=False)
        try:
            return candidate.relative_to(self.workspace_root).as_posix()
        except ValueError:
            return None

    @staticmethod
    def _node_id(path: str) -> str:
        return "path_" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:20]

    def _session_id(self) -> str:
        try:
            return str(self.session_id_provider() or "")
        except Exception:
            return ""


def task_graph_json(graph: dict[str, Any]) -> str:
    return json.dumps(graph, ensure_ascii=False, sort_keys=True)
