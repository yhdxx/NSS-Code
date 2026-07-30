from __future__ import annotations

import fnmatch
import hashlib
import json
from pathlib import Path
from threading import Lock
from time import time
from typing import Any

from mycodingagent.tool_runtime.base import get_sandbox_root, resolve_sandbox_path


IGNORED_CHANGE_PATTERNS = (
    "__pycache__/*",
    ".pytest_cache/*",
    ".coverage",
    "coverage/*",
    "dist/*",
    "build/*",
    "node_modules/.cache/*",
)


SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".vue",
    ".java",
    ".go",
    ".rs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".css",
    ".scss",
    ".html",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
}


class FileWriteLockManager:
    def __init__(self) -> None:
        self._guard = Lock()
        self._locks: dict[str, str] = {}

    def acquire(self, path: str, owner: str) -> tuple[bool, str]:
        with self._guard:
            locked_by = self._locks.get(path)
            if locked_by and locked_by != owner:
                return False, locked_by
            self._locks[path] = owner
            return True, ""

    def release(self, path: str, owner: str) -> None:
        with self._guard:
            if self._locks.get(path) == owner:
                self._locks.pop(path, None)

    def release_many(self, paths: list[str], owner: str) -> None:
        for path in paths:
            self.release(path, owner)


class FileCoordinator:
    def __init__(self, *, sandbox_root: Path | None = None) -> None:
        self.sandbox_root = sandbox_root or get_sandbox_root()
        self.locks = FileWriteLockManager()

    def record_read(self, run: Any, *, task_id: str, raw_path: str) -> None:
        path = self._resolve(raw_path)
        if path is None or not path.is_file():
            return
        file_key = str(path)
        version = self._ensure_file_version(run, path)
        run.task_file_reads.setdefault(task_id, {})[file_key] = {
            "read_revision": version["revision"],
            "read_hash": version["hash"],
            "read_mtime_ns": version.get("mtime_ns", 0),
        }
        access = run.file_access_index.setdefault(file_key, {"readers": [], "writers": []})
        if task_id not in access.setdefault("readers", []):
            access["readers"].append(task_id)

    def before_write(self, run: Any, *, task_id: str, raw_path: str) -> tuple[bool, str, str]:
        path = self._resolve(raw_path)
        if path is None:
            return False, "", self._json_error("invalid_path", f"Invalid file path: {raw_path}")
        file_key = str(path)
        ok, locked_by = self.locks.acquire(file_key, task_id)
        if not ok:
            self._add_waiter(run, file_key=file_key, task_id=task_id, operation="write", blocked_by=locked_by)
            return False, file_key, json.dumps(
                {
                    "status": "error",
                    "error": "file_locked",
                    "file_path": file_key,
                    "locked_by": locked_by,
                    "queued_for_notice": True,
                    "next_action": "Wait for runtime notice, then re-read the file before editing.",
                },
                ensure_ascii=False,
                indent=2,
            )
        if path.exists():
            stale = self._stale_error(run, task_id=task_id, path=path)
            if stale:
                self.locks.release(file_key, task_id)
                return False, file_key, stale
        return True, file_key, ""

    def after_write(self, run: Any, *, task_id: str, file_key: str, success: bool) -> None:
        try:
            path = Path(file_key)
            if success and path.exists():
                old_revision = int(run.file_versions.get(file_key, {}).get("revision", 0) or 0)
                version = self._refresh_file_version(run, path, task_id=task_id)
                self._record_writer(run, file_key=file_key, task_id=task_id)
                self._notify_related_tasks(
                    run,
                    file_key=file_key,
                    changed_by=task_id,
                    previous_revision=old_revision,
                    current_revision=int(version["revision"]),
                )
        finally:
            self.locks.release(file_key, task_id)
            self._notify_waiters(run, file_key=file_key, current_revision=self._current_revision(run, file_key))

    def before_bash(self, run: Any, *, task_id: str, raw_paths: list[str]) -> tuple[bool, list[str], str]:
        file_keys: list[str] = []
        for raw_path in raw_paths:
            path = self._resolve(raw_path)
            if path is None:
                return False, [], self._json_error("invalid_path", f"Invalid declared write file: {raw_path}")
            file_keys.append(str(path))
        file_keys = sorted(set(file_keys))
        acquired: list[str] = []
        for file_key in file_keys:
            ok, locked_by = self.locks.acquire(file_key, task_id)
            if not ok:
                self.locks.release_many(acquired, task_id)
                self._add_waiter(run, file_key=file_key, task_id=task_id, operation="bash_write", blocked_by=locked_by)
                return False, [], json.dumps(
                    {
                        "status": "error",
                        "error": "file_locked",
                        "file_path": file_key,
                        "locked_by": locked_by,
                        "queued_for_notice": True,
                        "next_action": "Wait for runtime notice, then re-read the file before editing.",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            acquired.append(file_key)
            path = Path(file_key)
            if path.exists():
                stale = self._stale_error(run, task_id=task_id, path=path)
                if stale:
                    self.locks.release_many(acquired, task_id)
                    return False, [], stale
        return True, file_keys, ""

    def after_bash(
        self,
        run: Any,
        *,
        task_id: str,
        declared_file_keys: list[str],
        before_snapshot: dict[str, str | None],
        after_snapshot: dict[str, str | None],
    ) -> tuple[bool, str, list[str]]:
        declared = set(declared_file_keys)
        changed = sorted(path for path in set(before_snapshot) | set(after_snapshot) if before_snapshot.get(path) != after_snapshot.get(path))
        illegal = [path for path in changed if path not in declared and self._is_relevant_change(path)]
        if illegal:
            self.restore_snapshot(before_snapshot)
            self.locks.release_many(declared_file_keys, task_id)
            return False, json.dumps(
                {
                    "status": "error",
                    "error": "undeclared_bash_write",
                    "changed_files": illegal,
                    "message": "Bash modified files not listed in declared_write_files. The changes were reverted.",
                },
                ensure_ascii=False,
                indent=2,
            ), changed
        for file_key in declared_file_keys:
            path = Path(file_key)
            old_revision = int(run.file_versions.get(file_key, {}).get("revision", 0) or 0)
            if path.exists():
                version = self._refresh_file_version(run, path, task_id=task_id)
                self._record_writer(run, file_key=file_key, task_id=task_id)
                self._notify_related_tasks(
                    run,
                    file_key=file_key,
                    changed_by=task_id,
                    previous_revision=old_revision,
                    current_revision=int(version["revision"]),
                )
            self._notify_waiters(run, file_key=file_key, current_revision=self._current_revision(run, file_key))
        self.locks.release_many(declared_file_keys, task_id)
        return True, "", changed

    def snapshot_workspace(self) -> dict[str, str | None]:
        snapshot: dict[str, str | None] = {}
        root = self.sandbox_root.resolve(strict=False)
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            key = str(path.resolve(strict=False))
            if self._is_ignored(key):
                continue
            try:
                snapshot[key] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            except OSError:
                continue
        return snapshot

    def restore_snapshot(self, snapshot: dict[str, str | None]) -> None:
        root = self.sandbox_root.resolve(strict=False)
        current = set(self.snapshot_workspace())
        previous = set(snapshot)
        for key in current - previous:
            path = Path(key)
            try:
                if path.resolve(strict=False).is_relative_to(root):
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        for key, content in snapshot.items():
            if content is None:
                continue
            path = Path(key)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            except OSError:
                pass

    def pop_notices(self, run: Any, *, task_id: str) -> list[dict[str, Any]]:
        notices = list(run.file_notices.get(task_id, []))
        if notices:
            run.file_notices[task_id] = []
        return notices

    def _resolve(self, raw_path: str) -> Path | None:
        path, error = resolve_sandbox_path(raw_path, self.sandbox_root)
        return None if error or path is None else path

    def _ensure_file_version(self, run: Any, path: Path) -> dict[str, Any]:
        key = str(path)
        existing = run.file_versions.get(key)
        current_hash = _hash_file(path)
        current_mtime = _mtime_ns(path)
        if existing and existing.get("hash") == current_hash and existing.get("mtime_ns") == current_mtime:
            return existing
        revision = int(existing.get("revision", 0) if existing else 0)
        payload = {
            "revision": revision,
            "hash": current_hash,
            "mtime_ns": current_mtime,
            "last_modified_by": existing.get("last_modified_by", "") if existing else "",
        }
        run.file_versions[key] = payload
        return payload

    def _refresh_file_version(self, run: Any, path: Path, *, task_id: str) -> dict[str, Any]:
        key = str(path)
        previous = run.file_versions.get(key, {})
        payload = {
            "revision": int(previous.get("revision", 0) or 0) + 1,
            "hash": _hash_file(path),
            "mtime_ns": _mtime_ns(path),
            "last_modified_by": task_id,
        }
        run.file_versions[key] = payload
        return payload

    def _stale_error(self, run: Any, *, task_id: str, path: Path) -> str:
        file_key = str(path)
        current = self._ensure_file_version(run, path)
        read = run.task_file_reads.get(task_id, {}).get(file_key)
        if read is None:
            return json.dumps(
                {
                    "status": "error",
                    "error": "stale_file",
                    "file_path": file_key,
                    "read_revision": None,
                    "current_revision": current["revision"],
                    "next_action": "Read the file before editing.",
                },
                ensure_ascii=False,
                indent=2,
            )
        if int(read.get("read_revision", -1)) != int(current.get("revision", 0)):
            return json.dumps(
                {
                    "status": "error",
                    "error": "stale_file",
                    "file_path": file_key,
                    "read_revision": read.get("read_revision"),
                    "current_revision": current.get("revision"),
                    "next_action": "Re-read the file before editing.",
                },
                ensure_ascii=False,
                indent=2,
            )
        return ""

    def _record_writer(self, run: Any, *, file_key: str, task_id: str) -> None:
        access = run.file_access_index.setdefault(file_key, {"readers": [], "writers": []})
        if task_id not in access.setdefault("writers", []):
            access["writers"].append(task_id)

    def _add_waiter(self, run: Any, *, file_key: str, task_id: str, operation: str, blocked_by: str) -> None:
        waiters = run.file_waiters.setdefault(file_key, [])
        if any(waiter.get("task_id") == task_id and waiter.get("operation") == operation for waiter in waiters):
            return
        waiters.append(
            {
                "task_id": task_id,
                "operation": operation,
                "blocked_by": blocked_by,
                "requested_revision": self._current_revision(run, file_key),
                "created_at": time(),
            }
        )

    def _notify_waiters(self, run: Any, *, file_key: str, current_revision: int) -> None:
        waiters = run.file_waiters.pop(file_key, [])
        for waiter in waiters:
            task_id = str(waiter.get("task_id", ""))
            if not task_id:
                continue
            self._add_notice(
                run,
                task_id=task_id,
                notice={
                    "file": file_key,
                    "event": "lock_released",
                    "previous_blocker": waiter.get("blocked_by", ""),
                    "current_revision": current_revision,
                    "action_required": "re_read_before_edit",
                },
            )

    def _notify_related_tasks(
        self,
        run: Any,
        *,
        file_key: str,
        changed_by: str,
        previous_revision: int,
        current_revision: int,
    ) -> None:
        access = run.file_access_index.get(file_key, {})
        related = set(access.get("readers", [])) | set(access.get("writers", []))
        for task_id in sorted(related):
            if task_id == changed_by:
                continue
            self._add_notice(
                run,
                task_id=task_id,
                notice={
                    "file": file_key,
                    "event": "changed_after_you_read",
                    "changed_by": changed_by,
                    "previous_revision": previous_revision,
                    "current_revision": current_revision,
                    "action_required": "none",
                },
            )

    def _add_notice(self, run: Any, *, task_id: str, notice: dict[str, Any]) -> None:
        notices = run.file_notices.setdefault(task_id, [])
        marker = (notice.get("file"), notice.get("event"), notice.get("current_revision"))
        for existing in notices:
            if (existing.get("file"), existing.get("event"), existing.get("current_revision")) == marker:
                return
        notices.append(notice)

    def _current_revision(self, run: Any, file_key: str) -> int:
        return int(run.file_versions.get(file_key, {}).get("revision", 0) or 0)

    def _json_error(self, code: str, message: str) -> str:
        return json.dumps({"status": "error", "error": code, "message": message}, ensure_ascii=False, indent=2)

    def _is_ignored(self, file_key: str) -> bool:
        try:
            rel = str(Path(file_key).resolve(strict=False).relative_to(self.sandbox_root.resolve(strict=False)))
        except ValueError:
            rel = file_key
        return any(fnmatch.fnmatch(rel, pattern) or rel.startswith(pattern.rstrip("*")) for pattern in IGNORED_CHANGE_PATTERNS)

    def _is_relevant_change(self, file_key: str) -> bool:
        if self._is_ignored(file_key):
            return False
        return Path(file_key).suffix in SOURCE_EXTENSIONS


def _hash_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0
