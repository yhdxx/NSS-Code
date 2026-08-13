from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any
from uuid import uuid4


REPRODUCIBLE_TOOLS = {
    "ReadFile",
    "Glob",
    "Grep",
    "Get_skill_reference",
    "search_skill_references",
    "search_skill",
    "list_dynamic_skills",
    "invoke_skill",
}


def is_reproducible_tool(tool_name: str, output: str = "") -> bool:
    if output.startswith(("Tool execution error:", "Error:", "工具执行错误：", "错误：")):
        return False
    return tool_name in REPRODUCIBLE_TOOLS


class ContextContentType(str, Enum):
    TEXT = "text"
    JSON = "json"
    ERROR = "error"
    UNKNOWN = "unknown"


class ContextLifecycleState(str, Enum):
    WORKING = "working"
    EXTERNAL = "external"
    ARCHIVED = "archived"
    DELETED = "deleted"


@dataclass
class RecoverableContextObject:
    id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    storage_key: str
    short_summary: str
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time)
    reproducible: bool = False
    token_count: int = 0
    source_tool: str = ""
    content_type: ContextContentType = ContextContentType.TEXT
    content_length: int = 0
    lifecycle_state: ContextLifecycleState = ContextLifecycleState.EXTERNAL
    access_count: int = 0
    last_accessed_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["content_type"] = self.content_type.value
        payload["lifecycle_state"] = self.lifecycle_state.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RecoverableContextObject:
        data = dict(payload)
        data["content_type"] = ContextContentType(data.get("content_type") or ContextContentType.UNKNOWN.value)
        data["lifecycle_state"] = ContextLifecycleState(
            data.get("lifecycle_state") or ContextLifecycleState.EXTERNAL.value
        )
        return cls(**data)


def build_recoverable_context(
    *,
    session_id: str,
    tool_call_id: str,
    tool_name: str,
    arguments_json: str,
    content: str,
    reproducible: bool,
    token_count: int,
    metadata: dict[str, Any] | None = None,
) -> RecoverableContextObject:
    context_id = uuid4().hex
    content_type = infer_content_type(content)
    related_files = extract_related_files(arguments_json, content)
    return RecoverableContextObject(
        id=context_id,
        session_id=session_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        storage_key=context_id,
        short_summary=short_summary_for_tool_output(tool_name, arguments_json, content),
        keywords=extract_keywords(tool_name, arguments_json, content),
        entities=extract_entities(content),
        related_files=related_files,
        reproducible=reproducible,
        token_count=token_count,
        source_tool=tool_name,
        content_type=content_type,
        content_length=len(content),
        metadata={"arguments_json": arguments_json, **(metadata or {})},
    )


def infer_content_type(content: str) -> ContextContentType:
    stripped = content.lstrip()
    if stripped.startswith(("Tool execution error:", "Error:", "工具执行错误：", "错误：")):
        return ContextContentType.ERROR
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            return ContextContentType.TEXT
        return ContextContentType.JSON
    return ContextContentType.TEXT


def short_summary_for_tool_output(tool_name: str, arguments_json: str, content: str) -> str:
    target = ""
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        args = {}
    if isinstance(args, dict):
        for key in ("file_path", "path", "command", "query"):
            if args.get(key):
                target = str(args[key])
                break
    target_part = f" for {target}" if target else ""
    return f"{tool_name} output{target_part}; {len(content)} chars"


def extract_related_files(arguments_json: str, content: str) -> list[str]:
    candidates: list[str] = []
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        args = {}
    if isinstance(args, dict):
        for key in ("file_path", "path"):
            value = args.get(key)
            if isinstance(value, str) and value:
                candidates.append(value)
    candidates.extend(re.findall(r"(?<!\w)(?:/workspace/)?[\w./-]+\.[A-Za-z0-9]{1,8}(?!\w)", content[:4000]))
    return dedupe_keep_order(candidates)[:20]


def extract_keywords(tool_name: str, arguments_json: str, content: str) -> list[str]:
    words = [tool_name]
    words.extend(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", arguments_json))
    words.extend(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", content[:2000]))
    stop = {"true", "false", "null", "none", "content", "output", "error"}
    return [word for word in dedupe_keep_order(words) if word.lower() not in stop][:30]


def extract_entities(content: str) -> list[str]:
    entities = re.findall(r"\b[A-Z][A-Za-z0-9_]*(?:\.[A-Z][A-Za-z0-9_]*)?\b", content[:4000])
    return dedupe_keep_order(entities)[:30]


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
