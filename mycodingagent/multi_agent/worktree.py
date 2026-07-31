from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class WorktreeHandle:
    worktree_id: str
    path: Path


@dataclass(frozen=True)
class WorktreeDelivery:
    delivered: bool
    changed: bool = False
    preserved_path: str = ""
    error: str = ""


@dataclass(frozen=True)
class _GitResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class WorktreeManager:
    def __init__(self, workspace_root: Path, state_root: Path) -> None:
        self.workspace_root = workspace_root.resolve(strict=False)
        self.state_root = state_root.resolve(strict=False)

    async def create(self) -> WorktreeHandle:
        repository = await self._git(self.workspace_root, "rev-parse", "--show-toplevel")
        if repository.returncode != 0:
            raise ValueError("--worktree requires a Git repository")
        if Path(repository.stdout.decode().strip()).resolve(strict=False) != self.workspace_root:
            raise ValueError("--worktree must be launched from the Git repository root")
        status = await self._git(self.workspace_root, "status", "--porcelain", "--untracked-files=all")
        if status.stdout.strip():
            raise ValueError("--worktree requires a clean source workspace")
        worktree_id = uuid4().hex
        path = self.state_root / "worktrees" / worktree_id
        path.parent.mkdir(parents=True, exist_ok=True)
        result = await self._git(self.workspace_root, "worktree", "add", "--detach", str(path), "HEAD")
        if result.returncode != 0:
            raise ValueError(result.stderr.decode(errors="replace").strip() or "failed to create worktree")
        return WorktreeHandle(worktree_id, path)

    async def deliver(self, handle: WorktreeHandle) -> WorktreeDelivery:
        await self._git(handle.path, "add", "-N", ".")
        patch = await self._git(handle.path, "diff", "--binary", "--no-ext-diff", "HEAD")
        if patch.returncode != 0:
            return WorktreeDelivery(False, preserved_path=str(handle.path), error="failed to build worktree patch")
        if not patch.stdout:
            await self.discard(handle)
            return WorktreeDelivery(True, changed=False)
        source_status = await self._git(self.workspace_root, "status", "--porcelain", "--untracked-files=all")
        if source_status.stdout.strip():
            return WorktreeDelivery(
                False,
                changed=True,
                preserved_path=str(handle.path),
                error="source workspace changed while the worktree task was running",
            )
        check_result = await self._git_input(
            self.workspace_root,
            patch.stdout,
            "apply",
            "--check",
            "--3way",
            "--whitespace=nowarn",
            "-",
        )
        if check_result.returncode != 0:
            return WorktreeDelivery(
                False,
                changed=True,
                preserved_path=str(handle.path),
                error=check_result.stderr.decode(errors="replace").strip() or "patch delivery preflight failed",
            )
        apply_result = await self._git_input(
            self.workspace_root,
            patch.stdout,
            "apply",
            "--3way",
            "--whitespace=nowarn",
            "-",
        )
        if apply_result.returncode != 0:
            return WorktreeDelivery(
                False,
                changed=True,
                preserved_path=str(handle.path),
                error=apply_result.stderr.decode(errors="replace").strip() or "patch delivery conflicted",
            )
        await self._git(self.workspace_root, "reset", "--quiet")
        await self.discard(handle)
        return WorktreeDelivery(True, changed=True)

    async def discard(self, handle: WorktreeHandle) -> None:
        await self._git(self.workspace_root, "worktree", "remove", "--force", str(handle.path))

    @staticmethod
    async def _git(cwd: Path, *args: str) -> _GitResult:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return _GitResult(process.returncode or 0, stdout, stderr)

    @staticmethod
    async def _git_input(cwd: Path, input_data: bytes, *args: str) -> _GitResult:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(input_data)
        return _GitResult(process.returncode or 0, stdout, stderr)
