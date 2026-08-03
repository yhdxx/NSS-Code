from __future__ import annotations

from typing import Any

from mycodingagent.llm_runtime import client as agent_client
from mycodingagent.llm_runtime.providers import ChatRequest


class RawClientModelManager:
    """Test/evaluation adapter for scripted OpenAI-compatible clients."""

    def __init__(self, raw_client: Any, model: str = "test-model") -> None:
        self.active_model = model
        self._provider = RawClientProvider(raw_client, model)

    def active_provider(self) -> "RawClientProvider":
        return self._provider


class RawClientProvider:
    def __init__(self, raw_client: Any, model: str) -> None:
        self.raw_client = raw_client
        self.model = model

    async def stream_chat(self, request: ChatRequest) -> Any:
        kwargs: dict[str, Any] = {}
        if request.display is not True:
            kwargs["display"] = request.display
        if request.output_label != "模型":
            kwargs["output_label"] = request.output_label
        if request.cancel_event is not None:
            kwargs["cancel_event"] = request.cancel_event
        if request.bash_classifier is not None:
            kwargs["bash_classifier"] = request.bash_classifier
        if request.extra_body is not None:
            kwargs["extra_body"] = request.extra_body
        return await agent_client.stream_one_round(
            self.raw_client,
            self.model,
            request.messages,
            request.tools,
            **kwargs,
        )


async def ask_model_with_raw_client(
    raw_client: Any,
    prompt: str,
    registry: Any,
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    *,
    model: str = "test-model",
    **kwargs: Any,
) -> tuple[str, list[dict[str, Any]]]:
    return await agent_client.ask_model(
        RawClientModelManager(raw_client, model),
        prompt,
        registry,
        tools,
        messages,
        **kwargs,
    )
