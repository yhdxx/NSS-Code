from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from mycodingagent.memory.budget import estimate_tokens


FORMAT_VERSION = "runtime-context-v1"
RECOVERY_HINT = "Recover additional context only if required for correctness."


@dataclass(frozen=True)
class WorkspaceChanges:
    paths: tuple[str, ...] = ()
    omitted: int = 0


@dataclass(frozen=True)
class ContextBudgetState:
    usage_ratio: float
    stage: str
    budget_is_tight: bool
    emergency: bool


@dataclass(frozen=True)
class RuntimeContextMetadata:
    format_version: str = FORMAT_VERSION
    source: str = "current_turn"


@dataclass(frozen=True)
class RuntimeContext:
    tool_outputs_virtualized: bool = True
    workspace_changes: WorkspaceChanges = field(default_factory=WorkspaceChanges)
    context_budget: ContextBudgetState | None = None
    capabilities: dict[str, Any] | None = None
    task_snapshot: str | None = None
    recovery_hint: str | None = RECOVERY_HINT
    metadata: RuntimeContextMetadata = field(default_factory=RuntimeContextMetadata)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RenderedPrompt:
    role: str
    content: str
    raw_user_prompt: str
    runtime_context: RuntimeContext
    runtime_context_json: str
    runtime_context_hash: str
    runtime_context_tokens: int
    user_prompt_tokens: int
    total_tokens: int
    format_version: str = FORMAT_VERSION


class RuntimeContextBuilder:
    def __init__(
        self,
        *,
        workspace_tracker: Any | None = None,
        context_budget: ContextBudgetState | None = None,
        capabilities: Any | None = None,
        task_snapshot: str | None = None,
        recovery_hint: str | None = RECOVERY_HINT,
    ) -> None:
        self.workspace_tracker = workspace_tracker
        self.context_budget = context_budget
        self.capabilities = capabilities
        self.task_snapshot = task_snapshot
        self.recovery_hint = recovery_hint

    def build(self) -> RuntimeContext:
        return RuntimeContext(
            workspace_changes=self._workspace_changes(),
            context_budget=self.context_budget,
            capabilities=self._capability_payload(),
            task_snapshot=self.task_snapshot or None,
            recovery_hint=self.recovery_hint,
        )

    def _workspace_changes(self) -> WorkspaceChanges:
        if self.workspace_tracker is None:
            return WorkspaceChanges()
        consume = getattr(self.workspace_tracker, "consume_external_changes", None)
        if not callable(consume):
            return WorkspaceChanges()
        changed_paths, omitted = consume()
        return WorkspaceChanges(paths=tuple(str(path) for path in changed_paths), omitted=int(omitted or 0))

    def _capability_payload(self) -> dict[str, Any] | None:
        if self.capabilities is None:
            return None
        to_runtime_payload = getattr(self.capabilities, "to_runtime_payload", None)
        if callable(to_runtime_payload):
            payload = to_runtime_payload()
        else:
            payload = self.capabilities
        return payload if isinstance(payload, dict) else None


class PromptRenderer:
    @staticmethod
    def render_current_user_message(runtime_context: RuntimeContext, user_prompt: str) -> RenderedPrompt:
        runtime_context_json = json.dumps(
            runtime_context.to_payload(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        content = (
            "<RUNTIME_CONTEXT>\n"
            f"{runtime_context_json}\n"
            "</RUNTIME_CONTEXT>\n\n"
            "<USER_REQUEST>\n"
            f"{user_prompt}\n"
            "</USER_REQUEST>"
        )
        runtime_context_hash = hashlib.sha256(runtime_context_json.encode("utf-8")).hexdigest()[:12]
        runtime_context_tokens = estimate_tokens(runtime_context_json)
        user_prompt_tokens = estimate_tokens(user_prompt)
        return RenderedPrompt(
            role="user",
            content=content,
            raw_user_prompt=user_prompt,
            runtime_context=runtime_context,
            runtime_context_json=runtime_context_json,
            runtime_context_hash=runtime_context_hash,
            runtime_context_tokens=runtime_context_tokens,
            user_prompt_tokens=user_prompt_tokens,
            total_tokens=estimate_tokens(content),
        )


def render_current_turn_for_model(
    messages: list[dict[str, Any]],
    *,
    current_turn_start: int,
    rendered_prompt: RenderedPrompt,
) -> list[dict[str, Any]]:
    model_messages = [dict(message) for message in messages]
    if not model_messages:
        return model_messages
    for index in range(len(model_messages) - 1, -1, -1):
        if model_messages[index].get("role") == "user":
            model_messages[index]["content"] = rendered_prompt.content
            return model_messages
    return model_messages


def is_rendered_runtime_prompt(content: str) -> bool:
    return "<RUNTIME_CONTEXT>" in content and "<USER_REQUEST>" in content


def extract_user_request_from_rendered_prompt(content: str) -> str | None:
    if not is_rendered_runtime_prompt(content):
        return None
    start_tag = "<USER_REQUEST>"
    end_tag = "</USER_REQUEST>"
    start = content.find(start_tag)
    end = content.find(end_tag, start + len(start_tag))
    if start == -1 or end == -1:
        return None
    return content[start + len(start_tag):end].strip()
