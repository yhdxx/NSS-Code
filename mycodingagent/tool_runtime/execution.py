from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from mycodingagent.tool_runtime.base import Tool
from mycodingagent.memory.models import ExecutionRecord


@dataclass(frozen=True)
class ToolExecution:
    output: str
    is_error: bool = False


class CodeQueryLedger:
    """Avoid spending a model turn on an identical successful semantic read."""

    TRACKED_TOOLS = {"code_index", "lsp"}

    def __init__(self) -> None:
        self._successful: set[tuple[str, str]] = set()
        self._failed_lsp: set[tuple[str, str]] = set()

    def preflight(self, tool_name: str, raw_args: str) -> ToolExecution | None:
        key = self._key(tool_name, raw_args)
        if key is not None and (key in self._successful or key in self._failed_lsp):
            return ToolExecution(
                "已跳过重复的代码智能查询。请复用已有证据、按 fallback 降级或调整查询范围。",
                is_error=True,
            )
        return None

    def record(self, tool_name: str, raw_args: str, execution: ToolExecution) -> None:
        key = self._key(tool_name, raw_args)
        if key is not None and not execution.is_error:
            self._successful.add(key)
        elif key is not None and tool_name == "lsp":
            self._failed_lsp.add(key)

    @classmethod
    def _key(cls, tool_name: str, raw_args: str) -> tuple[str, str] | None:
        if tool_name not in cls.TRACKED_TOOLS:
            return None
        parsed, error = parse_tool_arguments_object(raw_args)
        if error:
            return None
        parsed.pop("intent", None)
        parsed.pop("analysis_intent", None)
        return tool_name, json.dumps(parsed, ensure_ascii=False, sort_keys=True, default=str)


def parse_tool_arguments_object(raw_args: str) -> tuple[dict[str, Any], str]:
    try:
        parsed = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError as exc:
        return {}, f"工具执行错误：JSON 参数无效：{exc}"
    if not isinstance(parsed, dict):
        return {}, "工具执行错误：工具参数必须是 JSON 对象"
    return parsed, ""


async def execute_tool(
    tool: Tool,
    args: dict[str, Any],
    *,
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
        task = asyncio.create_task(tool.execute(params))
        if cancel_event is None:
            result = await task
        elif cancel_event.is_set():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            execution = ToolExecution("用户中断了本轮操作，工具未执行。", is_error=True)
            _finish_record(execution_recorder, execution_id, "interrupted", execution.output)
            return execution
        else:
            cancel_task = asyncio.create_task(cancel_event.wait())
            done, _pending = await asyncio.wait({task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
            if cancel_task in done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                execution = ToolExecution("工具执行已被用户中断。", is_error=True)
                _finish_record(execution_recorder, execution_id, "interrupted", execution.output)
                return execution
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)
            result = task.result()
    except asyncio.CancelledError:
        execution = ToolExecution("工具执行已被取消。", is_error=True)
        _finish_record(execution_recorder, execution_id, "interrupted", execution.output)
        current_task = asyncio.current_task()
        if current_task is not None and current_task.cancelling():
            raise
        return execution
    except Exception as exc:
        execution = ToolExecution(f"工具执行错误：{exc}", is_error=True)
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
        "\n本用户轮次中，相同工具和参数已重复失败。"
        "不要原样重试；请修正参数或使用已有信息。"
    )

    def __init__(self) -> None:
        self._failures: dict[tuple[str, str], int] = {}
        self._consecutive_mutation_failures = 0

    def preflight(self, tool_name: str, raw_args: str, *, is_mutation: bool = False) -> ToolExecution | None:
        key = self._key(tool_name, raw_args)
        if self._failures.get(key, 0) >= 2:
            return ToolExecution(
                "相同调用已连续失败两次，工具执行被阻止。请修改参数或先进行诊断。",
                is_error=True,
            )
        if is_mutation and self._consecutive_mutation_failures >= 3:
            return ToolExecution(
                "连续三次写入失败后，修改操作门禁已关闭。请先执行只读诊断，或询问用户后再继续。",
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
