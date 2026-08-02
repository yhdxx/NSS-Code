from __future__ import annotations

import asyncio
from typing import Any

import httpx
from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI

from mycodingagent.configuration import CONFIG
from mycodingagent.llm_runtime.providers.base import (
    ChatRequest,
    ModelProfile,
    PendingToolCall,
    ReasoningOption,
    StreamRoundResult,
    default_bash_display_level,
)
from mycodingagent.terminal_ui.output import (
    render_assistant_markdown,
    render_assistant_text,
    render_tool_calls,
    processing_status,
)


RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})


class OpenAICompatibleProvider:
    provider_name = "openai_compatible"
    default_base_url = ""
    models: tuple[str, ...] = ()
    _reasoning_options: tuple[ReasoningOption, ...] = ()

    def __init__(self, profile: ModelProfile) -> None:
        self.profile = profile
        self._client = AsyncOpenAI(
            api_key=profile.api,
            base_url=profile.base_url or self.default_base_url or None,
            default_headers=profile.extra_headers or None,
            timeout=profile.timeout,
            http_client=httpx.AsyncClient(trust_env=False, timeout=profile.timeout or 600.0),
        )

    @property
    def model(self) -> str:
        return self.profile.model

    @property
    def display_name(self) -> str:
        return f"{self.profile.provider}/{self.profile.model}"

    def list_models(self) -> list[str]:
        values = [self.profile.model, *self.models]
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result

    def reasoning_options(self, model: str | None = None) -> list[ReasoningOption]:
        return list(self._reasoning_options)

    async def stream_chat(self, request: ChatRequest) -> StreamRoundResult:
        payload: dict[str, Any] = {"model": self.model, "messages": request.messages, "stream": True}
        if request.tools:
            payload["tools"] = request.tools
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tool_choice is not None:
            payload["tool_choice"] = request.tool_choice

        extra_body = self._merged_extra_body(request.extra_body)
        if extra_body:
            payload["extra_body"] = extra_body

        content_parts: list[str] = []
        pending_tool_calls: dict[int, PendingToolCall] = {}
        last_usage = None
        stream = None

        for attempt in range(CONFIG.client.api_max_retries + 1):
            content_parts = []
            pending_tool_calls = {}
            last_usage = None
            try:
                async with processing_status("分析中", enabled=request.display):
                    stream, interrupted = await _wait_or_cancel(
                        self._client.chat.completions.create(**payload),
                        request.cancel_event,
                    )
                    if interrupted:
                        return StreamRoundResult("", [], interrupted=True)
                    iterator = stream.__aiter__()
                    while True:
                        try:
                            chunk, interrupted = await _wait_or_cancel(iterator.__anext__(), request.cancel_event)
                        except StopAsyncIteration:
                            break
                        if interrupted:
                            await stream.close()
                            text = "".join(content_parts)
                            if request.display and text:
                                render_assistant_text(text, label=request.output_label)
                            return StreamRoundResult(text, [], last_usage, interrupted=True)
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        text = getattr(delta, "content", None)
                        if text:
                            content_parts.append(text)
                        for tool_delta in getattr(delta, "tool_calls", None) or []:
                            state = pending_tool_calls.setdefault(tool_delta.index, PendingToolCall())
                            if tool_delta.id:
                                state.tool_id = tool_delta.id
                            function_delta = getattr(tool_delta, "function", None)
                            if function_delta is None:
                                continue
                            if function_delta.name:
                                state.tool_name = function_delta.name
                            if function_delta.arguments:
                                state.arguments += function_delta.arguments
                        if getattr(chunk, "usage", None):
                            last_usage = chunk.usage
                break
            except (APIConnectionError, APITimeoutError, APIError) as exc:
                if not _retryable_api_error(exc) or attempt >= CONFIG.client.api_max_retries:
                    error = _api_error_message(exc)
                    if request.display:
                        render_assistant_text(error, label=request.output_label)
                    return StreamRoundResult(error, [])
                delay = CONFIG.client.api_retry_base_delay * (2**attempt)
                if request.display:
                    print(
                        f"[连接中断，{delay:.1f}s 后重试 {attempt + 1}/{CONFIG.client.api_max_retries}] {exc}",
                        flush=True,
                    )
                _unused, interrupted = await _wait_or_cancel(asyncio.sleep(delay), request.cancel_event)
                if interrupted:
                    return StreamRoundResult("", [], interrupted=True)

        calls = [pending_tool_calls[index] for index in sorted(pending_tool_calls)]
        text = "".join(content_parts)
        if request.display:
            if calls:
                if text:
                    render_assistant_text(text, label=request.output_label)
                render_tool_calls(
                    calls,
                    bash_classifier=request.bash_classifier or default_bash_display_level,
                )
            else:
                render_assistant_markdown(text, label=request.output_label)
        return StreamRoundResult(text, calls, last_usage)

    async def close(self) -> None:
        await self._client.close()

    def _merged_extra_body(self, request_extra: dict[str, Any] | None) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        if self.profile.extra_body:
            merged.update(self.profile.extra_body)
        reasoning_payload = self._reasoning_payload(self.profile.reasoning)
        if reasoning_payload:
            merged.update(reasoning_payload)
        if request_extra:
            merged.update(request_extra)
        return merged

    def _reasoning_payload(self, reasoning: str | dict[str, Any] | None) -> dict[str, Any]:
        if isinstance(reasoning, dict):
            return dict(reasoning)
        return {}


async def _wait_or_cancel(awaitable: Any, cancel_event: Any) -> tuple[Any, bool]:
    task = asyncio.ensure_future(awaitable)
    if cancel_event is None:
        return await task, False
    if cancel_event.is_set():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return None, True
    cancel_task = asyncio.create_task(cancel_event.wait())
    done, _pending = await asyncio.wait({task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
    if cancel_task in done:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return None, True
    cancel_task.cancel()
    await asyncio.gather(cancel_task, return_exceptions=True)
    return task.result(), False


def _retryable_api_error(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
    return isinstance(status_code, int) and status_code in RETRYABLE_STATUS_CODES


def _api_error_message(exc: Exception) -> str:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return f"Error: API connection failed: {exc}"
    return f"Error: API request failed: {exc}"
