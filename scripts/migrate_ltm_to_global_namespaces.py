#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import time, strftime
from typing import Any
from uuid import uuid4


DEFAULT_DB = Path.home() / ".local" / "state" / "myCodingAgent" / "sessions.sqlite3"
GLOBAL_WORKSPACE_FINGERPRINT = "__USER_GLOBAL__"
GLOBAL_WORKSPACE_LABEL = "User Global Memory"
WORKFLOW_STAGING_FINGERPRINT = "__WORKFLOW_STAGING__"
WORKFLOW_STAGING_LABEL = "Workflow Staging Memory"


WORKFLOW_DEFINITIONS: dict[str, dict[str, Any]] = {
    "4318d0bdfb6c4ac1818cf7101470be37": {
        "name": "three_phase_task_confirmation",
        "description": "用于控制 Agent 在执行用户任务前先确认能力和用户意愿，避免未经确认就消耗资源或改变状态。",
        "when_to_use": "用户提出需要执行、修改、生成、运行测试、调用外部工具或消耗较多资源的任务，但尚未明确要求立即执行时使用。",
        "when_not_use": [
            "用户明确要求立即执行或已经确认继续时不要再次确认",
            "用户只是询问事实、解释概念或要求分析建议时不要使用",
        ],
    },
    "4c85d68f904440259b7643fefae27de8": {
        "name": "legacy_multi_agent_delegation",
        "description": "历史多智能体委托流程，用于记录曾经的 DelegateToMultiAgent 使用边界。",
        "when_to_use": "仅当当前项目重新启用模型可见的多智能体委托工具，且任务确实需要统一的计划、执行、测试闭环时使用。",
        "when_not_use": [
            "当前项目已删除模型可见的多智能体工具时不要使用",
            "用户未显式要求多智能体执行时不要使用",
        ],
    },
    "72d3d9651b354fd39b4f76b8a15665fd": {
        "name": "resume_tech_stack_differentiation_review",
        "description": "用于审阅简历项目经历时识别多个项目技术栈高度重叠的问题，并指导差异化表达。",
        "when_to_use": "用户要求修改、审阅或优化简历项目经历，且存在多个项目或多个项目技术栈相似时使用。",
        "when_not_use": ["用户只要求描述单个项目事实且不涉及简历包装时不要使用"],
    },
    "939e33fdf5ac4381a643265bce8b8201": {
        "name": "recover_coding_agent_project_context",
        "description": "用于在当前上下文缺失时恢复 myCodingAgent 项目架构、实现细节和历史讨论结论。",
        "when_to_use": "用户询问 myCodingAgent 项目事实、简历描述、架构设计或历史决策，而当前上下文缺少足够项目细节时使用。",
        "when_not_use": [
            "当前工作区源码已经可读且用户要求基于最新代码判断时不要只依赖历史恢复",
            "用户询问无关项目或通用概念时不要使用",
        ],
    },
    "e292a7bff06646e68173f038c7d74f77": {
        "name": "progressive_context_recovery",
        "description": "用于在上下文缺失时按长期记忆、可恢复上下文、文件系统探查的顺序恢复项目证据。",
        "when_to_use": "用户追问历史项目事实、历史会话结论或上下文中断后的任务状态，而当前热上下文没有足够信息时使用。",
        "when_not_use": [
            "当前问题可以直接通过当前上下文回答时不要使用",
            "用户明确要求不要检索历史上下文时不要使用",
        ],
    },
}


@dataclass(frozen=True)
class Item:
    memory_uid: str
    memory_type: str
    scope: str
    content: str
    confidence: float
    evidence: list[str]
    metadata: dict[str, Any]
    status: str
    created_at: float
    updated_at: float


def main() -> int:
    parser = argparse.ArgumentParser(description="Move long-term memory items into global/workflow namespaces.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to sessions.sqlite3.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned migration without writing.")
    args = parser.parse_args()

    db_path = args.db.expanduser()
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    active_items = _load_active_items(conn)
    global_items = _collect_global_items(active_items)
    workflow_items = _collect_workflow_items(active_items)

    print(f"database: {db_path}")
    print(f"global_items: {len(global_items)}")
    print(f"workflow_items: {len(workflow_items)}")
    print("global types:", _count_by_type(global_items))
    print("workflow types:", _count_by_type(workflow_items))

    if args.dry_run:
        conn.close()
        return 0

    backup_path = db_path.with_suffix(db_path.suffix + f".bak-{strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(db_path, backup_path)
    print(f"backup: {backup_path}")

    now = time()
    with conn:
        if global_items:
            _write_version(
                conn,
                user_id="djia",
                workspace_fingerprint=GLOBAL_WORKSPACE_FINGERPRINT,
                workspace_label=GLOBAL_WORKSPACE_LABEL,
                source_session_id="ltm-global-namespace-migration",
                items=global_items,
                now=now,
            )
        if workflow_items:
            _write_version(
                conn,
                user_id="djia",
                workspace_fingerprint=WORKFLOW_STAGING_FINGERPRINT,
                workspace_label=WORKFLOW_STAGING_LABEL,
                source_session_id="ltm-workflow-namespace-migration",
                items=workflow_items,
                now=now,
            )
    conn.close()
    print("done")
    return 0


def _load_active_items(conn: sqlite3.Connection) -> list[Item]:
    rows = conn.execute(
        """
        SELECT i.*
        FROM long_term_memory_items i
        JOIN long_term_memory_versions v ON v.version_id = i.version_id
        WHERE i.status = 'active'
        ORDER BY i.updated_at ASC
        """
    ).fetchall()
    return [_item_from_row(row) for row in rows]


def _collect_global_items(items: list[Item]) -> list[Item]:
    selected: list[Item] = []
    for item in items:
        if item.memory_type not in {"user_profile", "user_preference", "skill_candidate"}:
            continue
        metadata = dict(item.metadata)
        metadata["namespace"] = GLOBAL_WORKSPACE_FINGERPRINT
        selected.append(_replace(item, scope="user", metadata=metadata))
    return _dedupe_items(selected)


def _collect_workflow_items(items: list[Item]) -> list[Item]:
    selected: list[Item] = []
    latest_by_uid: dict[str, Item] = {}
    for item in items:
        if item.memory_type != "workflow_candidate":
            continue
        latest_by_uid[item.memory_uid] = item
    for item in latest_by_uid.values():
        metadata = dict(item.metadata)
        metadata["namespace"] = WORKFLOW_STAGING_FINGERPRINT
        metadata["workflow"] = WORKFLOW_DEFINITIONS.get(item.memory_uid) or _generic_workflow_metadata(item)
        metadata.setdefault("origin_workspace_fingerprint", WORKFLOW_STAGING_FINGERPRINT)
        metadata.setdefault("origin_workspace_label", WORKFLOW_STAGING_LABEL)
        metadata.setdefault("queried_workspaces", [])
        metadata.setdefault("used_workspaces", [])
        metadata.setdefault("unused_queried_workspaces", [])
        metadata.setdefault("exposure_count", 0)
        metadata.setdefault("success_count", 0)
        metadata.setdefault("lifecycle_status", "staging")
        selected.append(_replace(item, scope="workspace", metadata=metadata))
    return _dedupe_items(selected)


def _write_version(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    workspace_fingerprint: str,
    workspace_label: str,
    source_session_id: str,
    items: list[Item],
    now: float,
) -> str:
    parent = conn.execute(
        """
        SELECT version_id
        FROM long_term_memory_versions
        WHERE user_id = ? AND workspace_fingerprint = ? AND status = 'committed'
        ORDER BY committed_at DESC, created_at DESC
        LIMIT 1
        """,
        (user_id, workspace_fingerprint),
    ).fetchone()
    version_id = uuid4().hex
    conn.execute(
        """
        INSERT INTO long_term_memory_versions(
            version_id, user_id, workspace_fingerprint, workspace_label, status,
            parent_version_id, source_session_id, created_at, committed_at
        )
        VALUES (?, ?, ?, ?, 'committed', ?, ?, ?, ?)
        """,
        (
            version_id,
            user_id,
            workspace_fingerprint,
            workspace_label,
            str(parent["version_id"]) if parent is not None else "",
            source_session_id,
            now,
            now,
        ),
    )
    conn.executemany(
        """
        INSERT INTO long_term_memory_items(
            version_id, memory_uid, memory_type, scope, content, confidence,
            evidence_json, metadata_json, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                version_id,
                item.memory_uid,
                item.memory_type,
                item.scope,
                item.content,
                item.confidence,
                json.dumps(item.evidence, ensure_ascii=False),
                json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
                item.status,
                item.created_at,
                now,
            )
            for item in items
        ],
    )
    return version_id


def _dedupe_items(items: list[Item]) -> list[Item]:
    by_key: dict[tuple[str, str], Item] = {}
    used_uids: set[str] = set()
    result: list[Item] = []
    for item in sorted(items, key=lambda value: value.updated_at, reverse=True):
        key = (item.memory_type, " ".join(item.content.split()))
        if key in by_key:
            continue
        by_key[key] = item
        uid = item.memory_uid
        if uid in used_uids:
            uid = uuid4().hex
        used_uids.add(uid)
        result.append(_replace(item, memory_uid=uid))
    return sorted(result, key=lambda value: (value.memory_type, value.content))


def _generic_workflow_metadata(item: Item) -> dict[str, Any]:
    return {
        "name": f"workflow_{item.memory_uid[:8]}",
        "description": item.content[:300],
        "when_to_use": item.content[:300],
        "when_not_use": [],
    }


def _item_from_row(row: sqlite3.Row) -> Item:
    return Item(
        memory_uid=str(row["memory_uid"]),
        memory_type=str(row["memory_type"]),
        scope=str(row["scope"]),
        content=str(row["content"]),
        confidence=float(row["confidence"]),
        evidence=_load_json_list(str(row["evidence_json"] or "[]")),
        metadata=_load_json_dict(str(row["metadata_json"] or "{}")),
        status=str(row["status"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


def _replace(
    item: Item,
    *,
    memory_uid: str | None = None,
    scope: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Item:
    return Item(
        memory_uid=memory_uid or item.memory_uid,
        memory_type=item.memory_type,
        scope=scope or item.scope,
        content=item.content,
        confidence=item.confidence,
        evidence=list(item.evidence),
        metadata=dict(item.metadata if metadata is None else metadata),
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _load_json_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _load_json_dict(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _count_by_type(items: list[Item]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.memory_type] = counts.get(item.memory_type, 0) + 1
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
