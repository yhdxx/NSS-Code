from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from mycodingagent.llm_runtime.client import format_openai_tools
from mycodingagent.llm_runtime.providers import ChatRequest, InferenceProvider, normalize_stream_result
from mycodingagent.llm_runtime.streaming import assistant_message
from mycodingagent.long_term_memory.tools import SubmitLongTermMemoryPatch
from mycodingagent.tool_runtime.execution import ToolExecution, execute_tool, parse_tool_arguments_object


PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "storage" / "SYSTEM.md"


class LongTermMemoryStorageModel:
    def __init__(self, *, provider_getter: Callable[[], InferenceProvider]) -> None:
        self.provider_getter = provider_getter

    async def extract_patch(self, payload: dict[str, Any]) -> dict[str, Any]:
        extraction_id = str(payload.get("extraction_id", ""))
        collector: dict[str, Any] = {}
        submit_tool = SubmitLongTermMemoryPatch(extraction_id=extraction_id, collector=collector)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _read_prompt(PROMPT_PATH)},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2, default=str)},
        ]
        tools = format_openai_tools([_openai_schema(submit_tool)])
        for _ in range(3):
            stream_result = normalize_stream_result(
                await self.provider_getter().stream_chat(
                    ChatRequest(
                        messages=messages,
                        tools=tools,
                        display=False,
                        output_label="long_term_memory_storage",
                    )
                )
            )
            tool_calls = stream_result.tool_calls
            messages.append(assistant_message(stream_result.text, tool_calls))
            if not tool_calls:
                continue
            for index, call in enumerate(tool_calls):
                call_id = call.tool_id or f"ltm_storage_call_{index}"
                if call.tool_name != submit_tool.name:
                    execution = ToolExecution(
                        f"错误：存储模型只能调用 {submit_tool.name}。", is_error=True
                    )
                else:
                    execution = await _execute_submit_tool(submit_tool, call.arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": execution.output,
                        "metadata": {"is_error": execution.is_error},
                    }
                )
            if collector.get("payload") is not None:
                return dict(collector["payload"])
        raise ValueError("storage model did not submit a valid long-term memory patch")


async def _execute_submit_tool(tool: SubmitLongTermMemoryPatch, raw_args: str) -> ToolExecution:
    args, error = parse_tool_arguments_object(raw_args)
    return ToolExecution(error, is_error=True) if error else await execute_tool(tool, args)


def _read_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return (
            "从已完成会话中提取持久长期记忆，并使用完整的结构化补丁调用 SubmitLongTermMemoryPatch。"
        )


def _openai_schema(tool: SubmitLongTermMemoryPatch) -> dict[str, Any]:
    schema = tool.get_schema()
    return {
        "name": schema["name"],
        "description": schema["description"],
        "parameters": schema["input_schema"],
    }
