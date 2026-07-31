from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


COMMANDS = {
    "python": (("pyright-langserver", "--stdio"), ("pylsp",)),
    "go": (("gopls",),),
    "typescript": (("typescript-language-server", "--stdio"),),
    "javascript": (("typescript-language-server", "--stdio"),),
    "rust": (("rust-analyzer",),),
    "java": (("jdtls",),),
}
LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".go": "go", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".rs": "rust", ".java": "java",
}


@dataclass
class _LSPProcess:
    process: asyncio.subprocess.Process
    lock: asyncio.Lock
    next_id: int = 1


class LSPManager:
    def __init__(self, workspace_root: Path, *, timeout: float = 15.0) -> None:
        self.workspace_root = workspace_root.resolve(strict=False)
        self.timeout = timeout
        self._processes: dict[str, _LSPProcess] = {}
        self._startup_locks: dict[str, asyncio.Lock] = {}

    async def query(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        path = self._resolve(str(kwargs.get("path", "")))
        if path is None:
            return {"error": "path is outside the workspace or unsupported"}
        language = LANGUAGE_BY_SUFFIX[path.suffix.lower()]
        client = await self._ensure(language)
        if client is None:
            return {"available": False, "language": language, "error": "language server is not installed"}
        line = max(0, int(kwargs.get("line", 1)) - 1)
        column = max(0, int(kwargs.get("column", 0)))
        uri = path.as_uri()
        await self._notify(
            client,
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": language, "version": 1, "text": path.read_text(encoding="utf-8", errors="replace")}},
        )
        position = {"textDocument": {"uri": uri}, "position": {"line": line, "character": column}}
        methods = {
            "definition": ("textDocument/definition", position),
            "references": ("textDocument/references", {**position, "context": {"includeDeclaration": True}}),
            "hover": ("textDocument/hover", position),
            "diagnostics": ("textDocument/diagnostic", {"textDocument": {"uri": uri}}),
        }
        if operation not in methods:
            return {"error": f"unsupported LSP operation: {operation}"}
        method, params = methods[operation]
        try:
            result = await self._request(client, method, params)
            return {"available": True, "language": language, "operation": operation, "result": result}
        except Exception as exc:
            await self._close_language(language)
            return {"available": False, "language": language, "error": str(exc)}

    async def close(self) -> None:
        for language in list(self._processes):
            await self._close_language(language)

    async def _ensure(self, language: str) -> _LSPProcess | None:
        existing = self._processes.get(language)
        if existing is not None and existing.process.returncode is None:
            return existing
        lock = self._startup_locks.setdefault(language, asyncio.Lock())
        async with lock:
            existing = self._processes.get(language)
            if existing is not None and existing.process.returncode is None:
                return existing
            return await self._start(language)

    async def _start(self, language: str) -> _LSPProcess | None:
        command = next((candidate for candidate in COMMANDS[language] if shutil.which(candidate[0])), None)
        override = os.getenv(f"MYCODINGAGENT_LSP_{language.upper()}_COMMAND", "").strip()
        if override:
            command = tuple(override.split())
        if command is None:
            return None
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=self.workspace_root,
        )
        client = _LSPProcess(process=process, lock=asyncio.Lock())
        self._processes[language] = client
        try:
            await self._request(
                client,
                "initialize",
                {
                    "processId": os.getpid(),
                    "rootUri": self.workspace_root.as_uri(),
                    "capabilities": {"textDocument": {"definition": {}, "references": {}, "hover": {}, "diagnostic": {}}},
                },
            )
            await self._notify(client, "initialized", {})
            return client
        except Exception:
            await self._close_language(language)
            raise

    async def _request(self, client: _LSPProcess, method: str, params: dict[str, Any]) -> Any:
        async with client.lock:
            request_id = client.next_id
            client.next_id += 1
            await self._write(client, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            while True:
                message = await asyncio.wait_for(self._read(client), timeout=self.timeout)
                if message.get("id") == request_id:
                    if "error" in message:
                        raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
                    return message.get("result")
                if "id" in message and "method" in message:
                    await self._write(client, {"jsonrpc": "2.0", "id": message["id"], "result": None})

    async def _notify(self, client: _LSPProcess, method: str, params: dict[str, Any]) -> None:
        async with client.lock:
            await self._write(client, {"jsonrpc": "2.0", "method": method, "params": params})

    @staticmethod
    async def _write(client: _LSPProcess, payload: dict[str, Any]) -> None:
        if client.process.stdin is None:
            raise RuntimeError("language server stdin is closed")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        client.process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        await client.process.stdin.drain()

    @staticmethod
    async def _read(client: _LSPProcess) -> dict[str, Any]:
        if client.process.stdout is None:
            raise RuntimeError("language server stdout is closed")
        length = 0
        while True:
            line = await client.process.stdout.readline()
            if not line:
                raise RuntimeError("language server exited")
            if line in {b"\r\n", b"\n"}:
                break
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
        if length <= 0:
            raise RuntimeError("invalid language server response")
        return json.loads(await client.process.stdout.readexactly(length))

    async def _close_language(self, language: str) -> None:
        client = self._processes.pop(language, None)
        if client is None:
            return
        if client.process.returncode is None:
            client.process.terminate()
            try:
                await asyncio.wait_for(client.process.wait(), timeout=2)
            except asyncio.TimeoutError:
                client.process.kill()
                await client.process.wait()

    def _resolve(self, raw_path: str) -> Path | None:
        path = Path(raw_path)
        path = path if path.is_absolute() else self.workspace_root / path
        try:
            path = path.resolve(strict=False)
            path.relative_to(self.workspace_root)
        except ValueError:
            return None
        return path if path.is_file() and path.suffix.lower() in LANGUAGE_BY_SUFFIX else None
