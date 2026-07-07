from __future__ import annotations

import ctypes
import os
import select
import struct
from pathlib import Path
from threading import Event, Lock, Thread

from config import CONFIG
from tools.file_state_cache import FileStateCache

IN_MODIFY = 0x00000002
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_ISDIR = 0x40000000
IN_IGNORED = 0x00008000
IN_NONBLOCK = 0x00000800
IN_CLOEXEC = 0x00080000

WATCH_MASK = (
    IN_MODIFY
    | IN_ATTRIB
    | IN_CLOSE_WRITE
    | IN_MOVED_FROM
    | IN_MOVED_TO
    | IN_CREATE
    | IN_DELETE
    | IN_DELETE_SELF
    | IN_MOVE_SELF
)
EVENT_STRUCT = struct.Struct("iIII")


class WorkspaceChangeTracker:
    def __init__(self, root: Path, file_state_cache: FileStateCache, *, max_changes: int = 20) -> None:
        self.root = root.resolve(strict=False)
        self.file_state_cache = file_state_cache
        self.max_changes = max_changes
        self._changed_paths: set[str] = set()
        self._agent_writes: dict[str, tuple[int, int]] = {}
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._backend: _WorkspaceBackend | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self._backend = _InotifyWorkspaceBackend(self.root, self._record_change)
        except Exception:
            self._backend = _PollingWorkspaceBackend(self.root, self._record_change)
        self._thread = Thread(target=self._run, name="workspace-change-tracker", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._backend is not None:
            self._backend.close()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def mark_agent_write(self, path: str) -> None:
        normalized = self._normalize_path(path)
        fingerprint = _fingerprint(Path(normalized))
        if fingerprint is None:
            return
        with self._lock:
            self._agent_writes[normalized] = fingerprint
            self._changed_paths.discard(normalized)

    def mark_paths_for_recheck(self, paths: list[str]) -> None:
        with self._lock:
            for path in paths:
                normalized = self._normalize_path(path)
                self._agent_writes.pop(normalized, None)
                self._changed_paths.add(normalized)

    def consume_external_changes(self) -> tuple[list[str], int]:
        with self._lock:
            candidates = sorted(self._changed_paths)
            self._changed_paths.clear()

        stale_paths: list[str] = []
        for path in candidates:
            if not self.file_state_cache.has_read(path):
                continue
            if self._is_agent_write(path):
                continue
            if not self.file_state_cache.is_stale(path):
                continue
            stale_paths.append(_display_path(self.root, path))

        omitted = max(0, len(stale_paths) - self.max_changes)
        return stale_paths[: self.max_changes], omitted

    def _run(self) -> None:
        if self._backend is None:
            return
        while not self._stop_event.is_set():
            self._backend.poll(self._stop_event)

    def _record_change(self, path: Path, is_delete: bool) -> None:
        if path.is_dir() and not is_delete:
            return
        normalized = self._normalize_path(str(path))
        if not self.file_state_cache.has_read(normalized):
            return
        if self._is_agent_write(normalized):
            return
        with self._lock:
            self._changed_paths.add(normalized)

    def _is_agent_write(self, path: str) -> bool:
        with self._lock:
            expected = self._agent_writes.get(path)
        if expected is None:
            return False
        current = _fingerprint(Path(path))
        if current == expected:
            return True
        with self._lock:
            self._agent_writes.pop(path, None)
        return False

    def _normalize_path(self, path: str) -> str:
        return str(Path(path).resolve(strict=False))


class _WorkspaceBackend:
    def poll(self, stop_event: Event) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None


class _InotifyWorkspaceBackend(_WorkspaceBackend):
    def __init__(self, root: Path, on_change) -> None:
        self.root = root
        self._on_change = on_change
        self._libc = ctypes.CDLL("libc.so.6", use_errno=True)
        self._fd = self._libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if self._fd < 0:
            raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))
        self._watch_descriptors: dict[int, Path] = {}
        self._add_tree(root)

    def poll(self, stop_event: Event) -> None:
        readable, _, _ = select.select([self._fd], [], [], 0.5)
        if stop_event.is_set() or not readable:
            return

        while True:
            try:
                data = os.read(self._fd, 65536)
            except BlockingIOError:
                break
            if not data:
                break
            self._consume_events(data)

    def close(self) -> None:
        try:
            os.close(self._fd)
        except OSError:
            pass

    def _consume_events(self, data: bytes) -> None:
        offset = 0
        while offset + EVENT_STRUCT.size <= len(data):
            wd, mask, _cookie, name_len = EVENT_STRUCT.unpack_from(data, offset)
            offset += EVENT_STRUCT.size
            raw_name = data[offset : offset + name_len].rstrip(b"\0")
            offset += name_len

            parent = self._watch_descriptors.get(wd)
            name = raw_name.decode(errors="replace") if raw_name else ""
            path = parent / name if parent and name else parent
            if path is None:
                continue

            if mask & IN_IGNORED:
                self._watch_descriptors.pop(wd, None)
            if _should_skip(path):
                continue
            if mask & IN_ISDIR and mask & (IN_CREATE | IN_MOVED_TO):
                self._add_tree(path)
            if mask & WATCH_MASK:
                self._on_change(path, bool(mask & (IN_DELETE | IN_DELETE_SELF | IN_MOVED_FROM)))

    def _add_tree(self, root: Path) -> None:
        for directory in _iter_directories(root):
            self._add_watch(directory)

    def _add_watch(self, directory: Path) -> None:
        raw_path = os.fsencode(str(directory))
        wd = self._libc.inotify_add_watch(self._fd, raw_path, WATCH_MASK)
        if wd < 0:
            return
        self._watch_descriptors[wd] = directory


class _PollingWorkspaceBackend(_WorkspaceBackend):
    def __init__(self, root: Path, on_change) -> None:
        self.root = root
        self._on_change = on_change
        self._snapshot = _snapshot(root)

    def poll(self, stop_event: Event) -> None:
        stop_event.wait(CONFIG.skills.watcher_poll_interval)
        current = _snapshot(self.root)
        changed_paths = set(self._snapshot) ^ set(current)
        for path in set(self._snapshot) & set(current):
            if self._snapshot[path] != current[path]:
                changed_paths.add(path)
        self._snapshot = current
        for path in changed_paths:
            self._on_change(Path(path), path not in current)


def _iter_directories(root: Path) -> list[Path]:
    if not root.exists():
        return []
    directories: list[Path] = []
    for path in [root, *root.rglob("*")]:
        if path.is_dir() and not _should_skip(path):
            directories.append(path)
    return directories


def _should_skip(path: Path) -> bool:
    return any(part in CONFIG.sandbox.skip_dirs for part in path.parts)


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    if not root.exists():
        return {}
    snapshot: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if _should_skip(path) or path.is_dir():
            continue
        fingerprint = _fingerprint(path)
        if fingerprint is not None:
            snapshot[str(path.resolve(strict=False))] = fingerprint
    return snapshot


def _fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _display_path(root: Path, path: str) -> str:
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return path
