from __future__ import annotations

import json
from typing import Any

from mcp_client.models import MCPExecutionResult


def normalize_mcp_result(*, server: str, operation: str, name: str, result: Any) -> MCPExecutionResult:
    is_error = bool(getattr(result, "isError", False) or getattr(result, "is_error", False))
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    content = getattr(result, "content", None)
    metadata: dict[str, Any] = {}
    if structured is not None:
        return MCPExecutionResult(
            server=server,
            operation=operation,
            name=name,
            is_error=is_error,
            content_text=json.dumps(structured, ensure_ascii=False, indent=2, default=str),
            content_type="json",
            metadata=metadata,
        )
    if isinstance(content, list):
        text_parts: list[str] = []
        other_parts: list[dict[str, Any]] = []
        for item in content:
            item_type = str(getattr(item, "type", "") or "")
            text = getattr(item, "text", None)
            if text is not None:
                text_parts.append(str(text))
                continue
            other_parts.append(_content_metadata(item))
            if item_type:
                metadata.setdefault("content_types", []).append(item_type)
        if text_parts:
            content_type = "error" if is_error else "text"
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
        if other_parts:
            return MCPExecutionResult(
                server=server,
                operation=operation,
                name=name,
                is_error=is_error,
                content_text=json.dumps(other_parts, ensure_ascii=False, indent=2, default=str),
                content_type="metadata",
                metadata={"non_text_content": other_parts},
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
