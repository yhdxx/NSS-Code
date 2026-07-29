from __future__ import annotations

from typing import Any

from mycodingagent.long_term_memory.models import MemoryScope, MemoryType


GLOBAL_WORKSPACE_FINGERPRINT = "__USER_GLOBAL__"
GLOBAL_WORKSPACE_LABEL = "User Global Memory"
WORKFLOW_STAGING_FINGERPRINT = "__WORKFLOW_STAGING__"
WORKFLOW_STAGING_LABEL = "Workflow Staging Memory"


def namespace_for_bucket(bucket_name: str, current_workspace_fingerprint: str) -> str:
    if bucket_name in {"user_profiles", "user_preferences", "skill_candidates"}:
        return GLOBAL_WORKSPACE_FINGERPRINT
    if bucket_name == "workflows":
        return WORKFLOW_STAGING_FINGERPRINT
    if bucket_name == "project_facts":
        return current_workspace_fingerprint
    raise ValueError(f"unknown memory bucket: {bucket_name}")


def label_for_namespace(namespace: str, current_workspace_label: str) -> str:
    if namespace == GLOBAL_WORKSPACE_FINGERPRINT:
        return GLOBAL_WORKSPACE_LABEL
    if namespace == WORKFLOW_STAGING_FINGERPRINT:
        return WORKFLOW_STAGING_LABEL
    return current_workspace_label


def type_for_bucket(bucket_name: str) -> MemoryType:
    mapping = {
        "user_profiles": MemoryType.USER_PROFILE,
        "user_preferences": MemoryType.USER_PREFERENCE,
        "project_facts": MemoryType.PROJECT_FACT,
        "workflows": MemoryType.WORKFLOW_CANDIDATE,
        "skill_candidates": MemoryType.SKILL_CANDIDATE,
    }
    try:
        return mapping[bucket_name]
    except KeyError as exc:
        raise ValueError(f"unknown memory bucket: {bucket_name}") from exc


def default_scope_for_type(memory_type: MemoryType) -> MemoryScope:
    if memory_type in {MemoryType.USER_PROFILE, MemoryType.USER_PREFERENCE, MemoryType.SKILL_CANDIDATE}:
        return MemoryScope.USER
    if memory_type == MemoryType.PROJECT_FACT:
        return MemoryScope.PROJECT
    return MemoryScope.WORKSPACE


def validate_type_namespace(*, memory_type: MemoryType, namespace: str) -> None:
    if memory_type in {MemoryType.USER_PROFILE, MemoryType.USER_PREFERENCE, MemoryType.SKILL_CANDIDATE}:
        if namespace != GLOBAL_WORKSPACE_FINGERPRINT:
            raise ValueError(f"{memory_type.value} must be stored in global memory")
    elif memory_type == MemoryType.WORKFLOW_CANDIDATE:
        if namespace != WORKFLOW_STAGING_FINGERPRINT:
            raise ValueError("new workflow_candidate must be stored in workflow staging memory")
    elif memory_type == MemoryType.PROJECT_FACT:
        if namespace in {GLOBAL_WORKSPACE_FINGERPRINT, WORKFLOW_STAGING_FINGERPRINT}:
            raise ValueError("project_fact must be stored in the current workspace memory")


def validate_type_scope(*, memory_type: MemoryType, scope: MemoryScope) -> None:
    if memory_type in {MemoryType.USER_PROFILE, MemoryType.USER_PREFERENCE, MemoryType.SKILL_CANDIDATE} and scope != MemoryScope.USER:
        raise ValueError(f"{memory_type.value} must use user scope")
    if memory_type == MemoryType.PROJECT_FACT and scope == MemoryScope.USER:
        raise ValueError("project_fact cannot use user scope")


def item_namespace(item: Any) -> str:
    metadata = getattr(item, "metadata", {}) or {}
    namespace = metadata.get("namespace")
    if isinstance(namespace, str) and namespace:
        return namespace
    memory_type = getattr(item, "memory_type", None)
    if memory_type in {MemoryType.USER_PROFILE, MemoryType.USER_PREFERENCE, MemoryType.SKILL_CANDIDATE}:
        return GLOBAL_WORKSPACE_FINGERPRINT
    if memory_type == MemoryType.WORKFLOW_CANDIDATE:
        return WORKFLOW_STAGING_FINGERPRINT
    return str(metadata.get("workspace_fingerprint", ""))
