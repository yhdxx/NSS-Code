from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable

from mycodingagent.tool_runtime.base import Tool


@dataclass(frozen=True)
class ToolExecution:
    output: str
    is_error: bool = False


def parse_tool_arguments_object(raw_args: str) -> tuple[dict[str, Any], str]:
    try:
        parsed = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError as exc:
        return {}, f"Tool execution error: invalid JSON arguments: {exc}"
    if not isinstance(parsed, dict):
        return {}, "Tool execution error: tool arguments must be a JSON object"
    return parsed, ""


async def execute_tool(
    tool: Tool,
    args: dict[str, Any],
    *,
    on_notice: Callable[[], Any] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> ToolExecution:
    try:
        params = tool.params_model.model_validate(args)
        if on_notice is not None:
            notice_result = on_notice()
            if inspect.isawaitable(notice_result):
                await notice_result
        task = asyncio.create_task(tool.execute(params))
        if cancel_event is None:
            result = await task
        elif cancel_event.is_set():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return ToolExecution("Tool skipped because the user interrupted this turn.", is_error=True)
        else:
            cancel_task = asyncio.create_task(cancel_event.wait())
            done, _pending = await asyncio.wait({task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
            if cancel_task in done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return ToolExecution("Tool interrupted by the user.", is_error=True)
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)
            result = task.result()
    except Exception as exc:
        return ToolExecution(f"Tool execution error: {exc}", is_error=True)
    return ToolExecution(str(result.output), is_error=bool(result.is_error))


class RepeatedFailureTracker:
    NOTICE = (
        "\nRepeated tool failure with the same tool and arguments in this user turn. "
        "Do not retry unchanged; correct the arguments or use the information already available."
    )

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    def annotate(self, tool_name: str, raw_args: str, execution: ToolExecution) -> ToolExecution:
        if not execution.is_error:
            return execution
        args, parse_error = parse_tool_arguments_object(raw_args)
        canonical = raw_args.strip() if parse_error else json.dumps(args, ensure_ascii=False, sort_keys=True)
        key = (tool_name, canonical)
        repeated = key in self._seen
        self._seen.add(key)
        if not repeated:
            return execution
        return ToolExecution(execution.output + self.NOTICE, is_error=True)
