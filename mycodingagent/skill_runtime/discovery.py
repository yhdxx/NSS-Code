from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from mycodingagent.configuration import CONFIG
from mycodingagent.skill_runtime.models import SkillRecord, SkillReferenceRecord

SKILL_MARKDOWN_NAME = CONFIG.skills.markdown_filename
SKILL_JSON_SUFFIX = CONFIG.skills.json_suffix
REFERENCE_DIR_NAME = "references"
REFERENCE_TEXT_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".py",
    ".js",
    ".ts",
    ".sh",
    ".ps1",
}


def discover_skill_records(
    skills_root: Path | tuple[Path, ...] | list[Path],
    *,
    tier: str | None = None,
) -> list[SkillRecord]:
    if isinstance(skills_root, Path):
        return _discover_single_root(skills_root, tier=tier)

    records_by_tool_name: dict[str, SkillRecord] = {}
    for root in skills_root:
        for record in _discover_single_root(root, tier=tier):
            records_by_tool_name[record.tool_name] = record
    return list(records_by_tool_name.values())


def discover_reference_records(records: dict[str, SkillRecord] | list[SkillRecord]) -> list[SkillReferenceRecord]:
    values = records.values() if isinstance(records, dict) else records
    reference_records: list[SkillReferenceRecord] = []
    seen: set[str] = set()
    for record in values:
        for reference in _discover_record_references(record):
            if reference.ref_id in seen:
                continue
            seen.add(reference.ref_id)
            reference_records.append(reference)
    return reference_records


def _discover_single_root(skills_root: Path, *, tier: str | None = None) -> list[SkillRecord]:
    if not skills_root.exists():
        return []

    records: list[SkillRecord] = []
    for path in sorted(_iter_skill_files(skills_root)):
        record = _load_skill_file(path, tier=tier or _tier_from_path(path))
        if record is not None:
            records.append(record)
    return records


def _discover_record_references(record: SkillRecord) -> list[SkillReferenceRecord]:
    references_root = record.source_path.parent / REFERENCE_DIR_NAME
    if not references_root.exists() or not references_root.is_dir():
        return []

    result: list[SkillReferenceRecord] = []
    for path in sorted(references_root.rglob("*")):
        if not path.is_file():
            continue
        if _should_skip(path) or not _is_reference_text_file(path):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except OSError:
            continue
        relative_path = path.relative_to(record.source_path.parent).as_posix()
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        result.append(
            SkillReferenceRecord(
                ref_id=f"{record.tool_name}:{relative_path}",
                skill_tool_name=record.tool_name,
                skill_name=record.name,
                reference_path=relative_path,
                file_name=path.name,
                content=content,
                source_path=path.resolve(strict=False),
                content_hash=content_hash,
                updated_at=time.time(),
            )
        )
    return result


def _iter_skill_files(skills_root: Path) -> list[Path]:
    skill_files: list[Path] = []
    for path in skills_root.rglob("*"):
        if not path.is_file():
            continue
        if _should_skip(path):
            continue
        if path.name == SKILL_MARKDOWN_NAME or path.name.endswith(SKILL_JSON_SUFFIX):
            skill_files.append(path)
    return skill_files


def _should_skip(path: Path) -> bool:
    return any(part in CONFIG.skills.skip_dirs for part in path.parts)


def _is_reference_text_file(path: Path) -> bool:
    if path.name.startswith("._"):
        return False
    return path.suffix.lower() in REFERENCE_TEXT_SUFFIXES


def _load_skill_file(path: Path, *, tier: str) -> SkillRecord | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    if path.name.endswith(SKILL_JSON_SUFFIX):
        return _load_json_skill(path, content, tier=tier)
    return _load_markdown_skill(path, content, tier=tier)


def _load_json_skill(path: Path, content: str, *, tier: str) -> SkillRecord | None:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    name = str(data.get("name") or path.stem.removesuffix(".skill")).strip()
    description = str(data.get("description") or _first_nonempty_line(str(data.get("content") or "")) or name).strip()
    body = str(data.get("content") or content)
    return _make_record(path, name, description, body, metadata={"format": "json", "raw": data, "tier": tier})


def _load_markdown_skill(path: Path, content: str, *, tier: str) -> SkillRecord:
    frontmatter = _frontmatter(content)
    name = str(frontmatter.get("name") or _first_markdown_heading(content) or path.parent.name).strip()
    description = str(frontmatter.get("description") or _first_paragraph(content) or name).strip()
    metadata = {"format": "markdown", "tier": tier}
    for key in ("generated_by", "memory_uid"):
        if frontmatter.get(key):
            metadata[key] = str(frontmatter[key])
    return _make_record(path, name, description, content, metadata=metadata)


def _tier_from_path(path: Path) -> str:
    for part in reversed(path.parts):
        if part == "fixed":
            return "fixed"
        if part == "Dynamic":
            return "dynamic"
    return "dynamic"


def _make_record(path: Path, name: str, description: str, content: str, metadata: dict[str, Any]) -> SkillRecord:
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return SkillRecord(
        name=name,
        tool_name=normalize_tool_name(name),
        description=description,
        content=content,
        source_path=path.resolve(strict=False),
        content_hash=content_hash,
        updated_at=time.time(),
        metadata=metadata,
    )


def normalize_tool_name(name: str) -> str:
    lowered = name.strip().lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", lowered)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = "unnamed"
    if not normalized[0].isalpha():
        normalized = "skill_" + normalized
    if not normalized.startswith("skill_"):
        normalized = "skill_" + normalized
    return normalized[:64]


def _first_markdown_heading(content: str) -> str | None:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
    return None


def _frontmatter(content: str) -> dict[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    data: dict[str, str] = {}
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        data[key.strip()] = value.strip().strip("\"'")
    return data


def _first_paragraph(content: str) -> str | None:
    lines: list[str] = []
    in_frontmatter = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "---" and not lines:
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        if not stripped or stripped.startswith("#"):
            if lines:
                break
            continue
        lines.append(stripped)
    if not lines:
        return None
    return " ".join(lines)[:500]


def _first_nonempty_line(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
