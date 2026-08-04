from __future__ import annotations

import asyncio
import ipaddress
import mimetypes
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from mycodingagent.tool_runtime.base import resolve_sandbox_path


@dataclass(frozen=True)
class LoadedMedia:
    data: bytes
    mime_type: str
    filename: str


class MediaSourceError(ValueError):
    pass


class MediaSourceLoader:
    def __init__(self, client: httpx.AsyncClient, *, sandbox_root: Path | None = None) -> None:
        self._client = client
        self._sandbox_root = sandbox_root

    async def load(
        self,
        source: str,
        *,
        allowed_mime_types: frozenset[str],
        max_bytes: int,
        label: str,
    ) -> LoadedMedia:
        value = source.strip()
        if not value:
            raise MediaSourceError(f"{label}来源不能为空")
        parsed = urlsplit(value)
        if parsed.scheme:
            if parsed.scheme.lower() not in {"http", "https"}:
                raise MediaSourceError(f"{label} URL 只允许 http 或 https")
            data, content_type, filename = await self._download(value, max_bytes=max_bytes, label=label)
        else:
            path, error = resolve_sandbox_path(value, self._sandbox_root)
            if error:
                raise MediaSourceError(error)
            assert path is not None
            if not path.exists():
                raise MediaSourceError(f"{label}文件不存在：{value}")
            if not path.is_file():
                raise MediaSourceError(f"{label}路径不是普通文件：{value}")
            size = path.stat().st_size
            if size > max_bytes:
                raise MediaSourceError(f"{label}文件超过大小限制：{size} > {max_bytes} bytes")
            data = await asyncio.to_thread(path.read_bytes)
            content_type = ""
            filename = path.name
        mime_type = detect_media_type(data, filename=filename, content_type=content_type)
        if mime_type not in allowed_mime_types:
            supported = ", ".join(sorted(allowed_mime_types))
            raise MediaSourceError(f"不支持的{label}格式：{mime_type or 'unknown'}；支持：{supported}")
        return LoadedMedia(data=data, mime_type=mime_type, filename=filename)

    async def _download(self, url: str, *, max_bytes: int, label: str) -> tuple[bytes, str, str]:
        current = url
        for _redirect in range(6):
            await ensure_public_http_url(current)
            async with self._client.stream("GET", current, follow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location", "").strip()
                    if not location:
                        raise MediaSourceError(f"下载{label}失败：重定向缺少 Location")
                    current = urljoin(current, location)
                    continue
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise MediaSourceError(f"下载{label}失败：HTTP {response.status_code}") from exc
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > max_bytes:
                    raise MediaSourceError(
                        f"远程{label}超过大小限制：{declared} > {max_bytes} bytes"
                    )
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise MediaSourceError(
                            f"远程{label}超过大小限制：已接收超过 {max_bytes} bytes"
                        )
                    chunks.append(chunk)
                filename = Path(unquote(urlsplit(current).path)).name or f"remote-{label}"
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                return b"".join(chunks), content_type, filename
        raise MediaSourceError(f"下载{label}失败：重定向次数超过 5 次")


async def ensure_public_http_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise MediaSourceError("媒体 URL 必须是完整的公网 http/https 地址")
    if parsed.username is not None or parsed.password is not None:
        raise MediaSourceError("媒体 URL 不允许包含用户名或密码")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise MediaSourceError("媒体 URL 不允许访问本机地址")
    try:
        direct_ip = ipaddress.ip_address(host)
    except ValueError:
        direct_ip = None
    if direct_ip is not None:
        addresses = {direct_ip}
    else:
        try:
            infos = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise MediaSourceError(f"无法解析媒体 URL 主机：{host}") from exc
        addresses = {ipaddress.ip_address(item[4][0]) for item in infos}
    if not addresses or any(not address.is_global for address in addresses):
        raise MediaSourceError("媒体 URL 不允许访问本机、私网或保留地址")


def detect_media_type(data: bytes, *, filename: str, content_type: str = "") -> str:
    detected = _detect_signature(data)
    if detected:
        return detected
    normalized_content_type = _normalize_media_type(content_type)
    if normalized_content_type.startswith(("audio/", "image/")):
        return normalized_content_type
    guessed, _encoding = mimetypes.guess_type(filename)
    return _normalize_media_type(guessed or "")


def _normalize_media_type(value: str) -> str:
    normalized = value.strip().lower()
    return {
        "audio/x-m4a": "audio/m4a",
        "audio/x-wav": "audio/wav",
        "image/jpg": "image/jpeg",
        "image/x-ms-bmp": "image/bmp",
    }.get(normalized, normalized)


def _detect_signature(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:12] in {b"ftypheic", b"ftypheix", b"ftypmif1"}:
        return "image/heic"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"fLaC"):
        return "audio/flac"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    return ""
