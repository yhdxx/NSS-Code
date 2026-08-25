from __future__ import annotations

import json
from typing import Any

import httpx

from mycodingagent.llm_runtime.providers.base import (
    ChatRequest,
    ModelProfile,
    PendingToolCall,
    ReasoningOption,
    StreamRoundResult,
    default_bash_display_level,
)
from mycodingagent.terminal_ui.output import render_assistant_markdown, render_assistant_text, render_tool_calls


class AnthropicProvider:
    provider_name = "anthropic"
    default_base_url = "https://api.anthropic.com/v1"
    models = ("claude-sonnet-4-5", "claude-opus-4-1", "claude-3-5-haiku-latest")

    def __init__(self, profile: ModelProfile) -> None:
        self.profile = profile
        self._client = httpx.AsyncClient(
            base_url=profile.base_url or self.default_base_url,
            timeout=profile.timeout or 600.0,
            trust_env=False,
            headers={
                "x-api-key": profile.api,
                "anthropic-version": str(profile.extra_headers.get("anthropic-version", "2023-06-01")),
                **{key: value for key, value in profile.extra_headers.items() if key != "anthropic-version"},
            },
        )

    @property
    def model(self) -> str:
        return self.profile.model

    @property
    def display_name(self) -> str:
        return f"anthropic/{self.model}"

    def list_models(self) -> list[str]:
        return _unique([self.model, *self.models])

    def reasoning_options(self, model: str | None = None) -> list[ReasoningOption]:
        return [
            ReasoningOption("low", "低", "较小 thinking budget。"),
            ReasoningOption("medium", "中", "中等 thinking budget。"),
            ReasoningOption("high", "高", "较大 thinking budget。"),
        ]

    async def stream_chat(self, request: ChatRequest) -> StreamRoundResult:
        payload = self._payload(request)
        text_parts: list[str] = []
        tool_calls: dict[int, PendingToolCall] = {}
        try:
            async with self._client.stream("POST", "/messages", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if request.cancel_event is not None and request.cancel_event.is_set():
                        text = "".join(text_parts)
                        if request.stream_sink is not None and text:
                            request.stream_sink.abort(text)
                        if request.display and text and not getattr(request.stream_sink, "commits_final", False):
                            render_assistant_text(text, label=request.output_label)
                        return StreamRoundResult(text, [], interrupted=True)
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    before = len(text_parts)
                    _consume_anthropic_event(event, text_parts, tool_calls)
                    if request.stream_sink is not None and len(text_parts) > before:
                        request.stream_sink.delta("".join(text_parts[before:]))
        except Exception as exc:
            error = f"Error: API request failed: {exc}"
            if request.stream_sink is not None:
                request.stream_sink.reset()
            if request.display:
                render_assistant_text(error, label=request.output_label)
            return StreamRoundResult(error, [])

        calls = [tool_calls[index] for index in sorted(tool_calls)]
        text = "".join(text_parts)
        if request.display:
            if request.stream_sink is not None and text:
                request.stream_sink.finish(text, markdown=not calls)
            if calls:
                if text and not getattr(request.stream_sink, "commits_final", False):
                    render_assistant_text(text, label=request.output_label)
                render_tool_calls(calls, bash_classifier=request.bash_classifier or default_bash_display_level)
            elif request.stream_sink is None or not getattr(request.stream_sink, "commits_final", False):
                render_assistant_markdown(text, label=request.output_label)
        return StreamRoundResult(text, calls)

    async def close(self) -> None:
        await self._client.aclose()

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        system_parts: list[str] = []
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            role = message.get("role")
            if role == "system":
                if message.get("content"):
                    system_parts.append(str(message["content"]))
                continue
            if role == "tool":
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": str(message.get("tool_call_id") or ""),
                                "content": str(message.get("content") or ""),
                            }
                        ],
                    }
                )
                continue
            if role == "assistant" and message.get("tool_calls"):
                content: list[dict[str, Any]] = []
                if message.get("content"):
                    content.append({"type": "text", "text": str(message["content"])})
                for tool_call in message.get("tool_calls") or []:
                    function = tool_call.get("function") or {}
                    content.append(
                        {
                            "type": "tool_use",
                            "id": str(tool_call.get("id") or ""),
                            "name": str(function.get("name") or ""),
                            "input": _json_object(function.get("arguments")),
                        }
                    )
                messages.append({"role": "assistant", "content": content})
                continue
            if role in {"user", "assistant"}:
                messages.append({"role": role, "content": str(message.get("content") or "")})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_tokens": int(self.profile.extra_body.get("max_tokens") or 4096),
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if request.tools:
            payload["tools"] = [_anthropic_tool(tool) for tool in request.tools]
        thinking = self._thinking_payload()
        if thinking:
            payload["thinking"] = thinking
        payload.update(self.profile.extra_body)
        if request.extra_body:
            payload.update(request.extra_body)
        return payload

    def _thinking_payload(self) -> dict[str, Any]:
        if isinstance(self.profile.reasoning, dict):
            return dict(self.profile.reasoning)
        budget_by_level = {"low": 1024, "medium": 4096, "high": 8192}
        budget = budget_by_level.get(str(self.profile.reasoning or ""))
        return {"type": "enabled", "budget_tokens": budget} if budget else {}


def _consume_anthropic_event(
    event: dict[str, Any],
    text_parts: list[str],
    tool_calls: dict[int, PendingToolCall],
) -> None:
    event_type = event.get("type")
    if event_type == "content_block_start":
        index = int(event.get("index", 0) or 0)
        block = event.get("content_block") or {}
        if block.get("type") == "tool_use":
            tool_calls[index] = PendingToolCall(
                tool_id=str(block.get("id") or ""),
                tool_name=str(block.get("name") or ""),
                arguments="",
            )
    elif event_type == "content_block_delta":
        index = int(event.get("index", 0) or 0)
        delta = event.get("delta") or {}
        if delta.get("type") == "text_delta":
            text_parts.append(str(delta.get("text") or ""))
        elif delta.get("type") == "input_json_delta":
            tool_calls.setdefault(index, PendingToolCall()).arguments += str(delta.get("partial_json") or "")


def _anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function") or tool
    return {
        "name": function.get("name", ""),
        "description": function.get("description", ""),
        "input_schema": function.get("parameters", {"type": "object", "properties": {}}),
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
