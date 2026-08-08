from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from mycodingagent.terminal_ui.output import BashDisplayLevel


BashDisplayClassifier = Any


@dataclass
class PendingToolCall:
    tool_id: str = ""
    tool_name: str = ""
    arguments: str = ""


@dataclass(frozen=True)
class StreamRoundResult:
    text: str
    tool_calls: list[PendingToolCall]
    usage: Any = None
    interrupted: bool = False
    reasoning_content: str = ""


@dataclass(frozen=True)
class ReasoningOption:
    name: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class ModelProfile:
    key: str
    provider: str
    model: str
    api: str
    base_url: str = ""
    reasoning: str | dict[str, Any] | None = None
    timeout: float | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, key: str, raw: dict[str, Any]) -> "ModelProfile":
        return cls(
            key=key,
            provider=str(raw.get("provider") or "").strip().lower(),
            model=str(raw.get("model") or "").strip(),
            api=str(raw.get("api") or "").strip(),
            base_url=str(raw.get("base_url") or "").strip(),
            reasoning=raw.get("reasoning"),
            timeout=_optional_float(raw.get("timeout")),
            extra_headers=_string_dict(raw.get("extra_headers")),
            extra_body=dict(raw.get("extra_body") or {}) if isinstance(raw.get("extra_body"), dict) else {},
        )


@dataclass(frozen=True)
class ChatRequest:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    display: bool = True
    output_label: str = "模型"
    cancel_event: Any = None
    bash_classifier: BashDisplayClassifier | None = None
    extra_body: dict[str, Any] | None = None
    temperature: float | None = None
    tool_choice: Any = None
    stream_sink: Any = None


class InferenceProvider(Protocol):
    profile: ModelProfile
    provider_name: str

    @property
    def model(self) -> str:
        ...

    @property
    def display_name(self) -> str:
        ...

    def list_models(self) -> list[str]:
        ...

    def reasoning_options(self, model: str | None = None) -> list[ReasoningOption]:
        ...

    async def stream_chat(self, request: ChatRequest) -> StreamRoundResult:
        ...

    async def close(self) -> None:
        ...


def normalize_stream_result(value: Any) -> StreamRoundResult:
    if isinstance(value, StreamRoundResult):
        return value
    if hasattr(value, "text") and hasattr(value, "tool_calls"):
        return StreamRoundResult(
            text=str(getattr(value, "text") or ""),
            tool_calls=list(getattr(value, "tool_calls") or []),
            usage=getattr(value, "usage", None),
            interrupted=bool(getattr(value, "interrupted", False)),
            reasoning_content=str(getattr(value, "reasoning_content", "") or ""),
        )
    text, tool_calls, usage = value
    return StreamRoundResult(text=text, tool_calls=tool_calls, usage=usage)


def default_bash_display_level(command: str) -> tuple[BashDisplayLevel, str]:
    try:
        from mycodingagent.tool_runtime.command_policy import analyze_command

        risk, reason = analyze_command(command)
    except Exception as exc:  # pragma: no cover - defensive display fallback
        return "approval", f"无法分类：{exc}"
    if risk == "dangerous":
        return "high", reason
    if risk == "read":
        return "low", reason
    return "approval", reason


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(raw) for key, raw in value.items() if str(key).strip()}
