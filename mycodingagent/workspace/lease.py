from __future__ import annotations

import hashlib
import json
import os
import socket
from pathlib import Path
from threading import Event, Thread
from time import time

from filelock import FileLock, Timeout


class WorkspaceLeaseError(RuntimeError):
    pass


class WorkspaceLease:
    def __init__(self, workspace_root: Path, state_root: Path, *, heartbeat_seconds: float = 5.0) -> None:
        identity = hashlib.sha256(str(workspace_root.resolve(strict=False)).encode("utf-8")).hexdigest()[:24]
        lease_root = state_root.expanduser() / "leases"
        lease_root.mkdir(parents=True, exist_ok=True)
        self.workspace_root = workspace_root.resolve(strict=False)
        self.lock_path = lease_root / f"workspace-{identity}.lock"
        self.metadata_path = lease_root / f"workspace-{identity}.json"
        self.heartbeat_seconds = heartbeat_seconds
        self._lock = FileLock(self.lock_path, timeout=0)
        self._stop = Event()
        self._thread: Thread | None = None

    def acquire(self) -> None:
        try:
            self._lock.acquire()
        except Timeout as exc:
            owner = self.owner_metadata()
            detail = f" pid={owner.get('pid')} host={owner.get('host')}" if owner else ""
            raise WorkspaceLeaseError(f"workspace is already leased:{detail}") from exc
        self._write_metadata()
        self._thread = Thread(target=self._heartbeat, name="workspace-lease-heartbeat", daemon=True)
        self._thread.start()

    def release(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.heartbeat_seconds + 1)
        self._thread = None
        try:
            self.metadata_path.unlink(missing_ok=True)
        finally:
            if self._lock.is_locked:
                self._lock.release()

    def owner_metadata(self) -> dict:
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _heartbeat(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            self._write_metadata()

    def _write_metadata(self) -> None:
        payload = {
            "workspace": str(self.workspace_root),
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "heartbeat_at": time(),
        }
        temporary = self.metadata_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.metadata_path)

    def __enter__(self) -> "WorkspaceLease":
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()
