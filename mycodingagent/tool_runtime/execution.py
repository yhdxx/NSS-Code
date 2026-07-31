from __future__ import annotations

import asyncio
import inspect
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from mycodingagent.tool_runtime.base import Tool
from mycodingagent.memory.models import ExecutionRecord


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
    execution_recorder: Any | None = None,
    session_id: str = "",
) -> ToolExecution:
    execution_id = uuid4().hex
    risk = _tool_risk(tool)
    sanitized = _sanitize_args(args)
    args_json = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, default=str)
    if execution_recorder is not None and session_id:
        execution_recorder.start_execution_record(
            ExecutionRecord(
                execution_id=execution_id,
                session_id=session_id,
                tool_name=tool.name,
                risk=risk,
                status="running",
                args_hash=hashlib.sha256(args_json.encode("utf-8")).hexdigest(),
                args_preview=args_json[:1000],
                effects_json=json.dumps(_tool_effects(tool, args), ensure_ascii=False),
            )
        )
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
            execution = ToolExecution("Tool skipped because the user interrupted this turn.", is_error=True)
            _finish_record(execution_recorder, execution_id, "interrupted", execution.output)
            return execution
        else:
            cancel_task = asyncio.create_task(cancel_event.wait())
            done, _pending = await asyncio.wait({task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
            if cancel_task in done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                execution = ToolExecution("Tool interrupted by the user.", is_error=True)
                _finish_record(execution_recorder, execution_id, "interrupted", execution.output)
                return execution
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)
            result = task.result()
    except Exception as exc:
        execution = ToolExecution(f"Tool execution error: {exc}", is_error=True)
        _finish_record(execution_recorder, execution_id, "failed", execution.output)
        return execution
    execution = ToolExecution(str(result.output), is_error=bool(result.is_error))
    _finish_record(
        execution_recorder,
        execution_id,
        "failed" if execution.is_error else "succeeded",
        execution.output if execution.is_error else "",
    )
    return execution


def _finish_record(recorder: Any | None, execution_id: str, status: str, error: str = "") -> None:
    if recorder is not None:
        recorder.finish_execution_record(execution_id, status=status, error=error)


def _tool_risk(tool: Tool) -> str:
    return {"read": "read", "write": "write", "command": "process"}.get(tool.category, "unknown")


def _tool_effects(tool: Tool, args: dict[str, Any]) -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    if isinstance(args.get("file_path"), str):
        effects.append({"kind": "file", "path": args["file_path"], "reversible": tool.category == "write"})
    if tool.category == "command":
        effects.append({"kind": "external", "reversible": False})
    return effects


def _sanitize_args(value: Any, key: str = "") -> Any:
    if key.lower() in {"token", "password", "secret", "authorization", "api_key", "headers", "env"}:
        return "<redacted>"
    if isinstance(value, dict):
        return {str(item_key): _sanitize_args(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_sanitize_args(item) for item in value]
    if isinstance(value, str) and len(value) > 2000:
        return value[:2000] + "...<truncated>"
    return value


class RepeatedFailureTracker:
    NOTICE = (
        "\nRepeated tool failure with the same tool and arguments in this user turn. "
        "Do not retry unchanged; correct the arguments or use the information already available."
    )

    def __init__(self) -> None:
        self._failures: dict[tuple[str, str], int] = {}
        self._consecutive_mutation_failures = 0

    def preflight(self, tool_name: str, raw_args: str, *, is_mutation: bool = False) -> ToolExecution | None:
        key = self._key(tool_name, raw_args)
        if self._failures.get(key, 0) >= 2:
            return ToolExecution(
                "Tool execution blocked after two identical failures. Change the arguments or use diagnostics.",
                is_error=True,
            )
        if is_mutation and self._consecutive_mutation_failures >= 3:
            return ToolExecution(
                "Mutation gate is closed after three consecutive write failures. Use read-only diagnostics or ask the user before continuing.",
                is_error=True,
            )
        return None

    def annotate(
        self,
        tool_name: str,
        raw_args: str,
        execution: ToolExecution,
        *,
        is_mutation: bool = False,
    ) -> ToolExecution:
        if not execution.is_error:
            if is_mutation:
                self._consecutive_mutation_failures = 0
            return execution
        key = self._key(tool_name, raw_args)
        self._failures[key] = self._failures.get(key, 0) + 1
        if is_mutation:
            self._consecutive_mutation_failures += 1
        if self._failures[key] < 2:
            return execution
        return ToolExecution(execution.output + self.NOTICE, is_error=True)

    @staticmethod
    def _key(tool_name: str, raw_args: str) -> tuple[str, str]:
        args, parse_error = parse_tool_arguments_object(raw_args)
        canonical = raw_args.strip() if parse_error else json.dumps(args, ensure_ascii=False, sort_keys=True)
        return tool_name, canonical
