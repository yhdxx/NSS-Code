from __future__ import annotations

import json
import base64
import binascii
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from mycodingagent.mcp_integration.models import MCPExecutionResult


def normalize_mcp_result(
    *,
    server: str,
    operation: str,
    name: str,
    result: Any,
    artifact_root: Path | None = None,
    workspace_root: Path | None = None,
) -> MCPExecutionResult:
    is_error = bool(getattr(result, "isError", False) or getattr(result, "is_error", False))
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    content = getattr(result, "content", None)
    metadata: dict[str, Any] = {}
    text_parts: list[str] = []
    if structured is not None:
        text_parts.append(json.dumps(structured, ensure_ascii=False, indent=2, default=str))
    if isinstance(content, list):
        other_parts: list[dict[str, Any]] = []
        artifacts: list[dict[str, str]] = []
        for item in content:
            item_type = str(getattr(item, "type", "") or "")
            text = getattr(item, "text", None)
            if text is not None:
                text_parts.append(str(text))
                continue
            if item_type == "image" and artifact_root is not None:
                artifact = _save_image_artifact(
                    item,
                    artifact_root=artifact_root,
                    workspace_root=workspace_root,
                    server=server,
                    name=name,
                )
                if artifact is not None:
                    artifacts.append(artifact)
                    continue
            other_parts.append(_content_metadata(item))
            if item_type:
                metadata.setdefault("content_types", []).append(item_type)
        if artifacts:
            metadata["artifacts"] = artifacts
            text_parts.extend(f"[artifact] {item['path']}" for item in artifacts)
        if text_parts:
            content_type = "error" if is_error else ("json" if structured is not None else "text")
            if other_parts or artifacts:
                if other_parts:
                    metadata["omitted_non_text_content"] = other_parts
                content_type = "mixed"
            return MCPExecutionResult(
                server=server,
                operation=operation,
                name=name,
                is_error=is_error,
                content_text="\n".join(text_parts),
                content_type=content_type,
                metadata=metadata,
            )
        if other_parts or artifacts:
            return MCPExecutionResult(
                server=server,
                operation=operation,
                name=name,
                is_error=is_error,
                content_text=json.dumps(
                    {"artifacts": artifacts, "content": other_parts},
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                content_type="metadata",
                metadata={"non_text_content": other_parts, "artifacts": artifacts},
            )
    if text_parts:
        return MCPExecutionResult(
            server=server,
            operation=operation,
            name=name,
            is_error=is_error,
            content_text="\n".join(text_parts),
            content_type="json" if structured is not None else "text",
            metadata=metadata,
        )
    return MCPExecutionResult(
        server=server,
        operation=operation,
        name=name,
        is_error=is_error,
        content_text=json.dumps(result, ensure_ascii=False, indent=2, default=str),
        content_type="json",
        metadata=metadata,
    )


def _content_metadata(item: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in ("type", "mimeType", "mime_type", "uri", "name"):
        value = getattr(item, key, None)
        if value:
            payload[key] = str(value)
    return payload or {"type": type(item).__name__}


def _save_image_artifact(
    item: Any,
    *,
    artifact_root: Path,
    workspace_root: Path | None,
    server: str,
    name: str,
) -> dict[str, str] | None:
    encoded = getattr(item, "data", None)
    mime_type = str(getattr(item, "mimeType", None) or getattr(item, "mime_type", None) or "")
    extensions = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
    extension = extensions.get(mime_type.lower())
    if not isinstance(encoded, str) or extension is None:
        return None
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    if not data or len(data) > 15_000_000 or not _valid_image_signature(data, extension):
        return None
    safe_server = _safe_name(server)
    safe_name = _safe_name(name)
    target_dir = artifact_root.resolve(strict=False) / safe_server
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{safe_name}-{uuid4().hex}{extension}"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(target)
    display_path = str(target)
    if workspace_root is not None:
        try:
            display_path = str(target.relative_to(workspace_root.resolve(strict=False)))
        except ValueError:
            pass
    return {"path": display_path, "mime_type": mime_type}


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
    return cleaned[:80] or "mcp"


def _valid_image_signature(data: bytes, extension: str) -> bool:
    if extension == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == ".jpg":
        return data.startswith(b"\xff\xd8\xff")
    if extension == ".webp":
        return data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False
