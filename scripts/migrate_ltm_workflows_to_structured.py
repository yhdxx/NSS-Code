#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path
from time import strftime
from typing import Any


DEFAULT_DB = Path.home() / ".local" / "state" / "myCodingAgent" / "sessions.sqlite3"


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
        "when_to_use": "仅当当前项目重新启用模型可见的多智能体委托工具，且任务确实需要统一的 plan-execute-test 闭环时使用。",
        "when_not_use": [
            "当前项目已删除模型可见的多智能体工具时不要使用",
            "用户未显式要求多智能体执行时不要使用",
        ],
    },
    "72d3d9651b354fd39b4f76b8a15665fd": {
        "name": "resume_tech_stack_differentiation_review",
        "description": "用于审阅简历项目经历时识别多个项目技术栈高度重叠的问题，并指导差异化表达。",
        "when_to_use": "用户要求修改、审阅或优化简历项目经历，且存在多个项目或多个项目技术栈相似时使用。",
        "when_not_use": [
            "用户只要求描述单个项目事实且不涉及简历包装时不要使用",
        ],
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy long-term memory workflows to structured metadata.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to sessions.sqlite3.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned updates without writing.")
    args = parser.parse_args()

    db_path = args.db.expanduser()
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT rowid, memory_uid, memory_type, scope, content, metadata_json
        FROM long_term_memory_items
        WHERE status = 'active'
          AND memory_type IN ('workflow_candidate', 'skill_candidate')
        ORDER BY updated_at DESC
        """
    ).fetchall()

    updates: list[tuple[str, int, str]] = []
    unknown: list[str] = []
    for row in rows:
        metadata = _load_metadata(row["metadata_json"])
        workflow = metadata.get("workflow")
        if isinstance(workflow, dict) and _has_required_workflow_fields(workflow):
            continue
        definition = WORKFLOW_DEFINITIONS.get(str(row["memory_uid"]))
        if definition is None:
            unknown.append(str(row["memory_uid"]))
            continue
        metadata["workflow"] = definition
        updates.append((json.dumps(metadata, ensure_ascii=False, sort_keys=True), int(row["rowid"]), str(row["memory_uid"])))

    print(f"database: {db_path}")
    print(f"candidate_rows: {len(rows)}")
    print(f"updates: {len(updates)}")
    if unknown:
        print("unknown_uids:")
        for uid in sorted(set(unknown)):
            print(f"  {uid}")

    for _metadata_json, rowid, uid in updates:
        print(f"  update rowid={rowid} uid={uid}")

    if args.dry_run or not updates:
        conn.close()
        return 0

    backup_path = db_path.with_suffix(db_path.suffix + f".bak-{strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(db_path, backup_path)
    print(f"backup: {backup_path}")

    with conn:
        conn.executemany(
            "UPDATE long_term_memory_items SET metadata_json = ? WHERE rowid = ?",
            [(metadata_json, rowid) for metadata_json, rowid, _uid in updates],
        )
    conn.close()
    print("done")
    return 0


def _load_metadata(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _has_required_workflow_fields(workflow: dict[str, Any]) -> bool:
    return (
        bool(str(workflow.get("name", "")).strip())
        and bool(str(workflow.get("description", "")).strip())
        and bool(str(workflow.get("when_to_use", "")).strip())
        and isinstance(workflow.get("when_not_use"), list)
        and len(workflow.get("when_not_use")) <= 3
    )


if __name__ == "__main__":
    raise SystemExit(main())
