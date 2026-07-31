from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


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
OPERATIONS = ("definition", "references", "hover", "diagnostics")


@dataclass
class _OpenDocument:
    version: int
    content_hash: str


@dataclass
class _LSPProcess:
    process: asyncio.subprocess.Process
    lock: asyncio.Lock
    server_name: str
    capabilities: dict[str, Any] = field(default_factory=dict)
    open_documents: dict[str, _OpenDocument] = field(default_factory=dict)
    diagnostics: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    next_id: int = 1


class LSPManager:
    def __init__(self, workspace_root: Path, *, timeout: float = 15.0) -> None:
        self.workspace_root = workspace_root.resolve(strict=False)
        self.timeout = timeout
        self._processes: dict[str, _LSPProcess] = {}
        self._startup_locks: dict[str, asyncio.Lock] = {}
        self._last_errors: dict[str, str] = {}

    def runtime_payload(self) -> dict[str, Any]:
        languages: dict[str, Any] = {}
        for language in COMMANDS:
            command = self._command_for(language)
            languages[language] = {
                "available": command is not None,
                "server": command[0] if command else "",
                "operations": list(OPERATIONS) if command else [],
                "last_error": self._last_errors.get(self._process_key(language), ""),
            }
        return {
            "available": any(item["available"] for item in languages.values()),
            "languages": languages,
            "policy": "conditional_semantic_verification",
        }

    async def query(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        if operation not in OPERATIONS:
            return {"error": f"不支持的 LSP 操作：{operation}", "error_code": "unsupported_operation"}
        path = self._resolve(str(kwargs.get("path", "")))
        if path is None:
            return {
                "error": "路径位于工作区之外或文件类型不受支持",
                "error_code": "invalid_path",
                "workspace_root": "/workspace",
                "fallback": "使用 code_index 定位工作区内的源码文件和位置",
            }
        language = LANGUAGE_BY_SUFFIX[path.suffix.lower()]
        process_key = self._process_key(language)
        try:
            client = await self._ensure(language)
            if client is None:
                return {
                    "available": False,
                    "language": language,
                    "error": "未安装对应的语言服务器",
                    "error_code": "server_unavailable",
                    "retryable": False,
                    "fallback": "继续使用 code_index、定向 Grep 和 ReadFile",
                }
            uri = path.as_uri()
            await self._sync_document(client, uri=uri, language=language, path=path)
            line = max(0, int(kwargs.get("line", 1)) - 1)
            column = max(0, int(kwargs.get("column", 0)))
            position = {"textDocument": {"uri": uri}, "position": {"line": line, "character": column}}
            if operation == "definition":
                raw = await self._request(client, "textDocument/definition", position)
                result = self._normalize_locations(raw)
            elif operation == "references":
                raw = await self._request(
                    client, "textDocument/references", {**position, "context": {"includeDeclaration": True}}
                )
                result = self._normalize_locations(raw)
            elif operation == "hover":
                result = await self._request(client, "textDocument/hover", position)
            else:
                if client.capabilities.get("diagnosticProvider"):
                    raw = await self._request(client, "textDocument/diagnostic", {"textDocument": {"uri": uri}})
                    result = raw.get("items", []) if isinstance(raw, dict) else raw or []
                else:
                    await self._collect_notifications(client, uri=uri)
                    result = client.diagnostics.get(uri, [])
            self._last_errors.pop(process_key, None)
            return {
                "available": True,
                "language": language,
                "server": client.server_name,
                "operation": operation,
                "result": result,
            }
        except Exception as exc:
            await self._close_language(process_key)
            self._last_errors[process_key] = str(exc)
            return {
                "available": False,
                "language": language,
                "error": str(exc),
                "error_code": "server_failure",
                "retryable": False,
                "fallback": "本轮不要重复调用相同 LSP 查询；继续使用 code_index、定向 Grep 和 ReadFile",
            }

    async def close(self) -> None:
        for language in list(self._processes):
            await self._close_language(language)

    async def _ensure(self, language: str) -> _LSPProcess | None:
        process_key = self._process_key(language)
        existing = self._processes.get(process_key)
        if existing is not None and existing.process.returncode is None:
            return existing
        lock = self._startup_locks.setdefault(process_key, asyncio.Lock())
        async with lock:
            existing = self._processes.get(process_key)
            if existing is not None and existing.process.returncode is None:
                return existing
            return await self._start(language, process_key)

    async def _start(self, language: str, process_key: str) -> _LSPProcess | None:
        command = self._command_for(language)
        if command is None:
            return None
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=self.workspace_root,
        )
        client = _LSPProcess(process=process, lock=asyncio.Lock(), server_name=command[0])
        self._processes[process_key] = client
        try:
            result = await self._request(
                client,
                "initialize",
                {
                    "processId": os.getpid(),
                    "rootUri": self.workspace_root.as_uri(),
                    "workspaceFolders": [{"uri": self.workspace_root.as_uri(), "name": self.workspace_root.name}],
                    "capabilities": {
                        "textDocument": {
                            "definition": {}, "references": {}, "hover": {},
                            "diagnostic": {"dynamicRegistration": False},
                            "publishDiagnostics": {"relatedInformation": True},
                            "synchronization": {"didSave": True},
                        }
                    },
                },
            )
            if isinstance(result, dict) and isinstance(result.get("capabilities"), dict):
                client.capabilities = dict(result["capabilities"])
            await self._notify(client, "initialized", {})
            return client
        except Exception:
            await self._close_language(process_key)
            raise

    async def _sync_document(self, client: _LSPProcess, *, uri: str, language: str, path: Path) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        opened = client.open_documents.get(uri)
        if opened is None:
            await self._notify(
                client,
                "textDocument/didOpen",
                {"textDocument": {"uri": uri, "languageId": language, "version": 1, "text": text}},
            )
            client.open_documents[uri] = _OpenDocument(1, content_hash)
            return
        if opened.content_hash == content_hash:
            return
        version = opened.version + 1
        client.diagnostics.pop(uri, None)
        await self._notify(
            client,
            "textDocument/didChange",
            {"textDocument": {"uri": uri, "version": version}, "contentChanges": [{"text": text}]},
        )
        client.open_documents[uri] = _OpenDocument(version, content_hash)

    async def _request(self, client: _LSPProcess, method: str, params: dict[str, Any]) -> Any:
        async with client.lock:
            request_id = client.next_id
            client.next_id += 1
            await self._write(client, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            while True:
                message = await asyncio.wait_for(self._read(client), timeout=self.timeout)
                self._consume_notification(client, message)
                if message.get("id") == request_id:
                    if "error" in message:
                        raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
                    return message.get("result")
                if "id" in message and "method" in message:
                    await self._write(client, {"jsonrpc": "2.0", "id": message["id"], "result": None})

    async def _notify(self, client: _LSPProcess, method: str, params: dict[str, Any]) -> None:
        async with client.lock:
            await self._write(client, {"jsonrpc": "2.0", "method": method, "params": params})

    async def _collect_notifications(self, client: _LSPProcess, *, uri: str) -> None:
        async with client.lock:
            deadline = asyncio.get_running_loop().time() + min(self.timeout, 0.2)
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return
                try:
                    message = await asyncio.wait_for(self._read(client), timeout=remaining)
                except asyncio.TimeoutError:
                    return
                self._consume_notification(client, message)
                if uri in client.diagnostics:
                    return
                if "id" in message and "method" in message:
                    await self._write(client, {"jsonrpc": "2.0", "id": message["id"], "result": None})

    @staticmethod
    def _consume_notification(client: _LSPProcess, message: dict[str, Any]) -> None:
        if message.get("method") != "textDocument/publishDiagnostics":
            return
        params = message.get("params", {})
        if isinstance(params, dict) and isinstance(params.get("uri"), str):
            diagnostics = params.get("diagnostics", [])
            client.diagnostics[params["uri"]] = diagnostics if isinstance(diagnostics, list) else []

    @staticmethod
    async def _write(client: _LSPProcess, payload: dict[str, Any]) -> None:
        if client.process.stdin is None:
            raise RuntimeError("语言服务器的标准输入已关闭")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        client.process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        await client.process.stdin.drain()

    @staticmethod
    async def _read(client: _LSPProcess) -> dict[str, Any]:
        if client.process.stdout is None:
            raise RuntimeError("语言服务器的标准输出已关闭")
        length = 0
        while True:
            line = await client.process.stdout.readline()
            if not line:
                raise RuntimeError("语言服务器已退出")
            if line in {b"\r\n", b"\n"}:
                break
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
        if length <= 0:
            raise RuntimeError("语言服务器响应无效")
        return json.loads(await client.process.stdout.readexactly(length))

    async def _close_language(self, process_key: str) -> None:
        client = self._processes.pop(process_key, None)
        if client is None:
            return
        if client.process.returncode is None:
            for uri in list(client.open_documents):
                with contextlib.suppress(Exception):
                    await self._notify(client, "textDocument/didClose", {"textDocument": {"uri": uri}})
            with contextlib.suppress(Exception):
                await self._request(client, "shutdown", {})
                await self._notify(client, "exit", {})
            if client.process.returncode is None:
                client.process.terminate()
                try:
                    await asyncio.wait_for(client.process.wait(), timeout=2)
                except asyncio.TimeoutError:
                    client.process.kill()
                    await client.process.wait()

    def _command_for(self, language: str) -> tuple[str, ...] | None:
        override = os.getenv(f"MYCODINGAGENT_LSP_{language.upper()}_COMMAND", "").strip()
        if language == "javascript" and not override:
            override = os.getenv("MYCODINGAGENT_LSP_TYPESCRIPT_COMMAND", "").strip()
        if override:
            parsed = tuple(shlex.split(override))
            return parsed or None
        return next((candidate for candidate in COMMANDS[language] if shutil.which(candidate[0])), None)

    @staticmethod
    def _process_key(language: str) -> str:
        return "typescript" if language == "javascript" else language

    def _resolve(self, raw_path: str) -> Path | None:
        path = Path(raw_path)
        if path.is_absolute() and (path == Path("/workspace") or Path("/workspace") in path.parents):
            path = self.workspace_root / path.relative_to("/workspace")
        elif not path.is_absolute():
            path = self.workspace_root / path
        try:
            path = path.resolve(strict=False)
            path.relative_to(self.workspace_root)
        except ValueError:
            return None
        return path if path.is_file() and path.suffix.lower() in LANGUAGE_BY_SUFFIX else None

    def _normalize_locations(self, raw: Any) -> list[dict[str, Any]]:
        items = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
        normalized: list[dict[str, Any]] = []
        for item in items:
            uri = item.get("uri") or item.get("targetUri")
            location_range = item.get("range") or item.get("targetSelectionRange") or item.get("targetRange")
            if not isinstance(uri, str) or not isinstance(location_range, dict):
                continue
            normalized.append({"uri": uri, "path": self._display_uri(uri), "range": location_range})
        return normalized

    def _display_uri(self, uri: str) -> str:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            return uri
        path = Path(unquote(parsed.path)).resolve(strict=False)
        try:
            return path.relative_to(self.workspace_root).as_posix()
        except ValueError:
            return str(path)
