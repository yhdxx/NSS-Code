from __future__ import annotations

import asyncio
import ctypes
import os
import select
import struct
from pathlib import Path
from threading import Event, Lock, Thread

from config import CONFIG

IN_ACCESS = 0x00000001
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
POLL_INTERVAL_SECONDS = CONFIG.skills.watcher_poll_interval


class SkillDirectoryWatcher:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._dirty = True
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._backend: _WatcherBackend | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self._backend = _create_backend(self.root)
        self._thread = Thread(target=self._run, name="skill-directory-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._backend is not None:
            self._backend.close()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def mark_dirty(self) -> None:
        with self._lock:
            self._dirty = True

    def consume_dirty(self) -> bool:
        with self._lock:
            dirty = self._dirty
            self._dirty = False
            return dirty

    async def wait_for_change(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else asyncio.get_running_loop().time() + timeout
        while True:
            if self.consume_dirty():
                return True
            if timeout is not None:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return False
                await asyncio.sleep(min(0.1, remaining))
            else:
                await asyncio.sleep(0.1)

    def _run(self) -> None:
        if self._backend is None:
            return
        while not self._stop_event.is_set():
            changed = self._backend.poll(self._stop_event)
            if changed:
                self.mark_dirty()


class MultiSkillDirectoryWatcher:
    def __init__(self, roots: tuple[Path, ...] | list[Path]) -> None:
        self._watchers = [SkillDirectoryWatcher(root) for root in roots]

    def start(self) -> None:
        for watcher in self._watchers:
            watcher.start()

    def stop(self) -> None:
        for watcher in self._watchers:
            watcher.stop()

    def consume_dirty(self) -> bool:
        return any(watcher.consume_dirty() for watcher in self._watchers)

    async def wait_for_change(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else asyncio.get_running_loop().time() + timeout
        while True:
            if self.consume_dirty():
                return True
            if timeout is not None:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return False
                await asyncio.sleep(min(0.1, remaining))
            else:
                await asyncio.sleep(0.1)


class _WatcherBackend:
    def poll(self, stop_event: Event) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        return None


class _InotifyBackend(_WatcherBackend):
    def __init__(self, root: Path) -> None:
        self.root = root
        self._libc = ctypes.CDLL("libc.so.6", use_errno=True)
        self._fd = self._libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if self._fd < 0:
            raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))
        self._watch_descriptors: dict[int, Path] = {}
        self._add_tree(root)

    def poll(self, stop_event: Event) -> bool:
        readable, _, _ = select.select([self._fd], [], [], 0.5)
        if stop_event.is_set() or not readable:
            return False

        changed = False
        while True:
            try:
                data = os.read(self._fd, 65536)
            except BlockingIOError:
                break
            if not data:
                break
            changed = self._consume_events(data) or changed
        return changed

    def close(self) -> None:
        try:
            os.close(self._fd)
        except OSError:
            pass

    def _consume_events(self, data: bytes) -> bool:
        offset = 0
        changed = False
        while offset + EVENT_STRUCT.size <= len(data):
            wd, mask, _cookie, name_len = EVENT_STRUCT.unpack_from(data, offset)
            offset += EVENT_STRUCT.size
            raw_name = data[offset : offset + name_len].rstrip(b"\0")
            offset += name_len

            parent = self._watch_descriptors.get(wd)
            name = raw_name.decode(errors="replace") if raw_name else ""
            path = parent / name if parent and name else parent

            if mask & IN_IGNORED:
                self._watch_descriptors.pop(wd, None)
            if path is not None and (mask & IN_ISDIR) and (mask & (IN_CREATE | IN_MOVED_TO)):
                self._add_tree(path)
            if mask & WATCH_MASK:
                changed = True
        return changed

    def _add_tree(self, root: Path) -> None:
        for directory in _iter_directories(root):
            self._add_watch(directory)

    def _add_watch(self, directory: Path) -> None:
        raw_path = os.fsencode(str(directory))
        wd = self._libc.inotify_add_watch(self._fd, raw_path, WATCH_MASK)
        if wd < 0:
            return
        self._watch_descriptors[wd] = directory


class _PollingBackend(_WatcherBackend):
    def __init__(self, root: Path) -> None:
        self.root = root
        self._snapshot = _snapshot(root)

    def poll(self, stop_event: Event) -> bool:
        stop_event.wait(POLL_INTERVAL_SECONDS)
        current = _snapshot(self.root)
        if current == self._snapshot:
            return False
        self._snapshot = current
        return True


def _create_backend(root: Path) -> _WatcherBackend:
    try:
        return _InotifyBackend(root)
    except Exception:
        return _PollingBackend(root)


def _iter_directories(root: Path) -> list[Path]:
    if not root.exists():
        return []
    directories: list[Path] = []
    for path in [root, *root.rglob("*")]:
        if path.is_dir() and not _should_skip(path):
            directories.append(path)
    return directories


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    if not root.exists():
        return {}
    snapshot: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if _should_skip(path):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[str(path)] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def _should_skip(path: Path) -> bool:
    return any(part in CONFIG.skills.skip_dirs for part in path.parts)
