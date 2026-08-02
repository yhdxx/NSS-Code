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


class GeminiProvider:
    provider_name = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"
    models = ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash")

    def __init__(self, profile: ModelProfile) -> None:
        self.profile = profile
        self._client = httpx.AsyncClient(
            base_url=profile.base_url or self.default_base_url,
            timeout=profile.timeout or 600.0,
            trust_env=False,
            headers=profile.extra_headers,
        )

    @property
    def model(self) -> str:
        return self.profile.model

    @property
    def display_name(self) -> str:
        return f"gemini/{self.model}"

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
        tool_calls: list[PendingToolCall] = []
        try:
            path = f"/models/{self.model}:streamGenerateContent"
            async with self._client.stream("POST", path, params={"key": self.profile.api, "alt": "sse"}, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if request.cancel_event is not None and request.cancel_event.is_set():
                        return StreamRoundResult("".join(text_parts), [], interrupted=True)
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    _consume_gemini_event(event, text_parts, tool_calls)
        except Exception as exc:
            error = f"Error: API request failed: {exc}"
            if request.display:
                render_assistant_text(error, label=request.output_label)
            return StreamRoundResult(error, [])

        text = "".join(text_parts)
        if request.display:
            if tool_calls:
                if text:
                    render_assistant_text(text, label=request.output_label)
                render_tool_calls(tool_calls, bash_classifier=request.bash_classifier or default_bash_display_level)
            else:
                render_assistant_markdown(text, label=request.output_label)
        return StreamRoundResult(text, tool_calls)

    async def close(self) -> None:
        await self._client.aclose()

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        contents: list[dict[str, Any]] = []
        system_parts: list[str] = []
        for message in request.messages:
            role = message.get("role")
            if role == "system":
                if message.get("content"):
                    system_parts.append(str(message["content"]))
                continue
            if role == "tool":
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": str(message.get("tool_call_id") or "tool_result"),
                                    "response": {"content": str(message.get("content") or "")},
                                }
                            }
                        ],
                    }
                )
                continue
            parts: list[dict[str, Any]] = []
            if message.get("content"):
                parts.append({"text": str(message.get("content") or "")})
            for tool_call in message.get("tool_calls") or []:
                function = tool_call.get("function") or {}
                parts.append(
                    {
                        "functionCall": {
                            "name": str(function.get("name") or ""),
                            "args": _json_object(function.get("arguments")),
                        }
                    }
                )
            if parts:
                contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
        payload: dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        if request.tools:
            payload["tools"] = [{"functionDeclarations": [_gemini_tool(tool) for tool in request.tools]}]
        generation_config = dict(self.profile.extra_body.get("generationConfig") or {})
        budget = self._thinking_budget()
        if budget is not None:
            generation_config["thinkingConfig"] = {"thinkingBudget": budget}
        if generation_config:
            payload["generationConfig"] = generation_config
        payload.update({key: value for key, value in self.profile.extra_body.items() if key != "generationConfig"})
        if request.extra_body:
            payload.update(request.extra_body)
        return payload

    def _thinking_budget(self) -> int | None:
        if isinstance(self.profile.reasoning, dict):
            value = self.profile.reasoning.get("thinkingBudget")
            return int(value) if isinstance(value, int) else None
        return {"low": 1024, "medium": 4096, "high": 8192}.get(str(self.profile.reasoning or ""))


def _consume_gemini_event(event: dict[str, Any], text_parts: list[str], tool_calls: list[PendingToolCall]) -> None:
    for candidate in event.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            if part.get("text"):
                text_parts.append(str(part["text"]))
            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                tool_calls.append(
                    PendingToolCall(
                        tool_id=f"gemini_call_{len(tool_calls)}",
                        tool_name=str(function_call.get("name") or ""),
                        arguments=json.dumps(function_call.get("args") or {}, ensure_ascii=False),
                    )
                )


def _gemini_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function") or tool
    return {
        "name": function.get("name", ""),
        "description": function.get("description", ""),
        "parameters": function.get("parameters", {"type": "object", "properties": {}}),
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
