from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from mycodingagent.llm_runtime.client import PendingToolCall, format_openai_tools, stream_one_round
from mycodingagent.long_term_memory.tools import SubmitLongTermMemoryPatch


PROMPT_PATH = Path(__file__).resolve().parents[2] / "multiAgent" / "prompts" / "long_term_memory_storage" / "SYSTEM.md"


class LongTermMemoryStorageModel:
    def __init__(self, *, api_client: AsyncOpenAI, model: str) -> None:
        self.api_client = api_client
        self.model = model

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
            assistant_text, tool_calls, _usage = await stream_one_round(
                self.api_client,
                self.model,
                messages,
                tools,
                display=False,
                output_label="long_term_memory_storage",
            )
            messages.append(_assistant_message(assistant_text, tool_calls))
            if not tool_calls:
                continue
            for index, call in enumerate(tool_calls):
                call_id = call.tool_id or f"ltm_storage_call_{index}"
                if call.tool_name != submit_tool.name:
                    output = f"Error: storage model may only call {submit_tool.name}."
                else:
                    output = await _execute_submit_tool(submit_tool, call)
                messages.append({"role": "tool", "tool_call_id": call_id, "content": output})
            if collector.get("payload") is not None:
                return dict(collector["payload"])
        raise ValueError("storage model did not submit a valid long-term memory patch")


async def _execute_submit_tool(tool: SubmitLongTermMemoryPatch, call: PendingToolCall) -> str:
    try:
        params = tool.params_model.model_validate_json(call.arguments or "{}")
        result = await tool.execute(params)
    except Exception as exc:
        return f"Tool execution error: {exc}"
    return result.output


def _assistant_message(assistant_text: str, tool_calls: list[PendingToolCall]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant"}
    if assistant_text or not tool_calls:
        message["content"] = assistant_text
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


def _read_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return (
            "You extract durable long-term memory from a completed session. "
            "Call SubmitLongTermMemoryPatch with the complete structured patch."
        )


def _openai_schema(tool: SubmitLongTermMemoryPatch) -> dict[str, Any]:
    schema = tool.get_schema()
    return {
        "name": schema["name"],
        "description": schema["description"],
        "parameters": schema["input_schema"],
    }
