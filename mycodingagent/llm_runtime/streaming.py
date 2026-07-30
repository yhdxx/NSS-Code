from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI

from mycodingagent.configuration import CONFIG

RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})


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


def normalize_stream_result(value: Any) -> StreamRoundResult:
    if isinstance(value, StreamRoundResult):
        return value
    text, tool_calls, usage = value
    return StreamRoundResult(text=text, tool_calls=tool_calls, usage=usage)


def assistant_message(text: str, tool_calls: list[PendingToolCall]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant"}
    if text or not tool_calls:
        message["content"] = text
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": call.tool_id or f"tool_call_{index}",
                "type": "function",
                "function": {"name": call.tool_name, "arguments": call.arguments},
            }
            for index, call in enumerate(tool_calls)
        ]
    return message


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


async def _wait_or_cancel(awaitable: Any, cancel_event: asyncio.Event | None) -> tuple[Any, bool]:
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


async def stream_one_round(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    display: bool = True,
    output_label: str = "模型",
    cancel_event: asyncio.Event | None = None,
) -> StreamRoundResult:
    request: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    if tools:
        request["tools"] = tools

    content_parts: list[str] = []
    pending_tool_calls: dict[int, PendingToolCall] = {}
    last_usage = None
    printed_any_text = False
    stream = None

    for attempt in range(CONFIG.client.api_max_retries + 1):
        content_parts = []
        pending_tool_calls = {}
        last_usage = None
        printed_any_text = False
        try:
            stream, interrupted = await _wait_or_cancel(
                client.chat.completions.create(**request), cancel_event
            )
            if interrupted:
                return StreamRoundResult("", [], interrupted=True)
            if display:
                print(f"{output_label}：", end="", flush=True)
            iterator = stream.__aiter__()
            while True:
                try:
                    chunk, interrupted = await _wait_or_cancel(iterator.__anext__(), cancel_event)
                except StopAsyncIteration:
                    break
                if interrupted:
                    await stream.close()
                    if display and printed_any_text:
                        print()
                    # Tool call arguments received before finish_reason may be incomplete.
                    return StreamRoundResult("".join(content_parts), [], last_usage, interrupted=True)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    if display:
                        print(text, end="", flush=True)
                        printed_any_text = True
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
                if display:
                    if printed_any_text:
                        print()
                    print(f"{output_label}：{error}", flush=True)
                return StreamRoundResult(error, [])
            delay = CONFIG.client.api_retry_base_delay * (2**attempt)
            if display:
                if printed_any_text:
                    print()
                print(
                    f"[连接中断，{delay:.1f}s 后重试 {attempt + 1}/{CONFIG.client.api_max_retries}] {exc}",
                    flush=True,
                )
            _unused, interrupted = await _wait_or_cancel(asyncio.sleep(delay), cancel_event)
            if interrupted:
                return StreamRoundResult("", [], interrupted=True)

    if display and content_parts:
        print()
    calls = [pending_tool_calls[index] for index in sorted(pending_tool_calls)]
    if display and calls:
        print("工具调用：", flush=True)
        for call in calls:
            try:
                args = json.dumps(json.loads(call.arguments or "{}"), ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                args = call.arguments
            print(f"- {call.tool_name} {args}", flush=True)
    return StreamRoundResult("".join(content_parts), calls, last_usage)
