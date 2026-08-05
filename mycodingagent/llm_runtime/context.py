from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from mycodingagent.memory.budget import estimate_tokens


FORMAT_VERSION = "runtime-context-v2"


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
class RuntimeContext:
    work_mode: str = "general"
    interaction_mode: str = "normal"
    context_render_mode: str = "raw"
    workspace_changes: WorkspaceChanges = field(default_factory=WorkspaceChanges)
    context_budget: ContextBudgetState | None = None
    capabilities: dict[str, Any] | None = None
    project_graph: dict[str, Any] | None = None
    task_snapshot: str | None = None
    long_term_memory: dict[str, Any] | None = None
    tool_policy: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    network_routing: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return self.stable_payload()

    def stable_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "work_mode": self.work_mode,
            "interaction_mode": self.interaction_mode,
            "context_render_mode": self.context_render_mode,
        }
        if self.tool_policy:
            payload["tool_policy"] = self.tool_policy
        if self.network_routing:
            payload["network_routing"] = self.network_routing
        if self.plan:
            payload["plan"] = self.plan
        if self.capabilities:
            payload["capabilities"] = self.capabilities
        if self.project_graph:
            payload["project_graph"] = self.project_graph
        if self.long_term_memory:
            payload["long_term_memory"] = self.long_term_memory
        if self.context_budget is not None:
            payload["context_budget"] = asdict(self.context_budget)
        if self.task_snapshot:
            payload["task_snapshot"] = self.task_snapshot
        workspace_changes = workspace_changes_payload(self.workspace_changes)
        if workspace_changes:
            payload["workspace_changes"] = workspace_changes
        return payload

def workspace_changes_payload(changes: WorkspaceChanges) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if changes.paths:
        payload["paths"] = list(changes.paths)
    if changes.omitted:
        payload["omitted"] = changes.omitted
    return payload


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
        context_mode: str = "raw",
        work_mode: str = "general",
        capabilities: Any | None = None,
        project_graph: Any | None = None,
        long_term_memory: dict[str, Any] | None = None,
        interaction_mode: str = "normal",
        tool_policy: dict[str, Any] | None = None,
        plan: dict[str, Any] | None = None,
        network_routing: dict[str, Any] | None = None,
        context_budget: ContextBudgetState | None = None,
    ) -> None:
        self.workspace_tracker = workspace_tracker
        self.context_mode = context_mode
        self.work_mode = work_mode
        self.capabilities = capabilities
        self.project_graph = project_graph
        self.long_term_memory = long_term_memory
        self.interaction_mode = interaction_mode
        self.tool_policy = tool_policy
        self.plan = plan
        self.network_routing = network_routing
        self.context_budget = context_budget

    def build(self) -> RuntimeContext:
        return RuntimeContext(
            work_mode=self.work_mode,
            interaction_mode=self.interaction_mode,
            context_render_mode=self.context_mode,
            workspace_changes=self._workspace_changes(),
            capabilities=self._capability_payload(),
            project_graph=self._project_graph_payload(),
            long_term_memory=self.long_term_memory,
            tool_policy=self.tool_policy,
            plan=self.plan,
            network_routing=self.network_routing,
            context_budget=self.context_budget,
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

    def _project_graph_payload(self) -> dict[str, Any] | None:
        if self.project_graph is None:
            return None
        runtime_payload = getattr(self.project_graph, "runtime_payload", None)
        payload = runtime_payload() if callable(runtime_payload) else self.project_graph
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
    allowed_keys = {"role", "content", "name", "tool_call_id", "tool_calls"}
    model_messages: list[dict[str, Any]] = []
    for message in messages:
        copied = {key: value for key, value in message.items() if key in allowed_keys}
        metadata = message.get("metadata")
        if message.get("role") == "user" and isinstance(metadata, dict) and metadata.get("model_content"):
            copied["content"] = str(metadata["model_content"])
        model_messages.append(copied)
    if not model_messages:
        return model_messages
    for index in range(current_turn_start, len(model_messages)):
        if model_messages[index].get("role") == "user":
            existing_content = str(model_messages[index].get("content") or "")
            if not is_rendered_runtime_prompt(existing_content):
                model_messages[index]["content"] = rendered_prompt.content
            return model_messages
    return model_messages


def freeze_model_visible_user_message(
    messages: list[dict[str, Any]],
    *,
    current_turn_start: int,
    content: str,
) -> bool:
    """Persist the exact user message sent to the model without changing UI text."""
    for index in range(current_turn_start, len(messages)):
        message = messages[index]
        if message.get("role") != "user":
            continue
        metadata = dict(message.get("metadata") or {})
        if metadata.get("model_content") == content:
            return False
        if metadata.get("model_content"):
            return False
        metadata["model_content"] = content
        message["metadata"] = metadata
        return True
    return False


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
