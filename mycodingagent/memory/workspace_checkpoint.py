from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from mycodingagent.memory.models import WorkspaceCheckpoint, WorkspaceFileSnapshot
from mycodingagent.memory.stores import SQLiteMemoryStore


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class RewindResult:
    checkpoint: WorkspaceCheckpoint | None = None
    restored: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.checkpoint is not None and not self.conflicts and not self.errors


@dataclass
class WorkspaceCheckpointManager:
    store: SQLiteMemoryStore
    workspace_root: Path
    session_id: str = ""
    current: WorkspaceCheckpoint | None = None
    _captured_paths: set[str] = field(default_factory=set)

    def begin_turn(self, *, session_id: str, turn_index: int, message_index: int, prompt: str) -> WorkspaceCheckpoint:
        checkpoint = WorkspaceCheckpoint(
            checkpoint_id=uuid4().hex,
            session_id=session_id,
            turn_index=turn_index,
            message_index=message_index,
            prompt=prompt[:500],
        )
        self.session_id = session_id
        self.current = checkpoint
        self._captured_paths.clear()
        self.store.save_workspace_checkpoint(checkpoint)
        return checkpoint

    def capture_before(self, path: Path) -> None:
        checkpoint = self.current
        if checkpoint is None:
            return
        relative = self._relative(path)
        if relative in self._captured_paths:
            return
        existed = path.is_file()
        content = path.read_bytes() if existed else None
        before_hash = _content_hash(content) if content is not None else ""
        self.store.save_workspace_file_snapshot(
            WorkspaceFileSnapshot(
                checkpoint_id=checkpoint.checkpoint_id,
                path=relative,
                existed=existed,
                before_hash=before_hash,
            ),
            content,
        )
        self._captured_paths.add(relative)

    def capture_after(self, path: Path) -> None:
        checkpoint = self.current
        if checkpoint is None:
            return
        relative = self._relative(path)
        if relative not in self._captured_paths:
            return
        after_hash = _content_hash(path.read_bytes()) if path.is_file() else ""
        self.store.update_workspace_file_after_hash(checkpoint.checkpoint_id, relative, after_hash)

    def list(self, session_id: str | None = None) -> list[WorkspaceCheckpoint]:
        return self.store.list_workspace_checkpoints(session_id or self.session_id)

    def rewind(self, checkpoint_id: str, *, force: bool = False) -> RewindResult:
        checkpoint, snapshots = self.store.load_workspace_snapshots_from(self.session_id, checkpoint_id)
        if checkpoint is None:
            return RewindResult(errors=(f"checkpoint not found: {checkpoint_id}",))

        earliest: dict[str, WorkspaceFileSnapshot] = {}
        latest: dict[str, WorkspaceFileSnapshot] = {}
        for snapshot in snapshots:
            earliest.setdefault(snapshot.path, snapshot)
            latest[snapshot.path] = snapshot

        conflicts: list[str] = []
        for relative, snapshot in latest.items():
            path = self._resolve(relative)
            current_hash = _content_hash(path.read_bytes()) if path.is_file() else ""
            if current_hash != snapshot.after_hash:
                conflicts.append(relative)
        if conflicts and not force:
            return RewindResult(checkpoint=checkpoint, conflicts=tuple(sorted(conflicts)))

        restored: list[str] = []
        errors: list[str] = []
        for relative, snapshot in earliest.items():
            try:
                path = self._resolve(relative)
                if snapshot.existed:
                    content = self.store.load_workspace_blob(snapshot.before_hash)
                    if content is None:
                        raise RuntimeError("snapshot content is missing")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                elif path.exists():
                    path.unlink()
                restored.append(relative)
            except Exception as exc:
                errors.append(f"{relative}: {exc}")
        if not errors:
            self.store.truncate_workspace_checkpoints(self.session_id, checkpoint.turn_index)
            self.current = None
            self._captured_paths.clear()
        return RewindResult(
            checkpoint=checkpoint,
            restored=tuple(sorted(restored)),
            conflicts=tuple(sorted(conflicts)),
            errors=tuple(errors),
        )

    def _relative(self, path: Path) -> str:
        resolved = path.resolve(strict=False)
        return resolved.relative_to(self.workspace_root.resolve(strict=False)).as_posix()

    def _resolve(self, relative: str) -> Path:
        root = self.workspace_root.resolve(strict=False)
        resolved = (root / relative).resolve(strict=False)
        resolved.relative_to(root)
        return resolved
