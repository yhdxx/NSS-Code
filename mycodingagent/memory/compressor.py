from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mycodingagent.configuration import CONFIG
from mycodingagent.memory.models import CompressionResult

REPRODUCIBLE_TOOLS = {
    "ReadFile",
    "Glob",
    "Grep",
    "Get_skill_reference",
    "search_skill_references",
    "search_tool",
    "Get_tool_by_name",
    "Get_all_tool",
    "invoke_skill",
}


@dataclass
class ToolOutputRef:
    output_id: str
    tool_name: str
    original_length: int
    preview: str
    reproducible: bool


class ContextCompressor:
    def __init__(
        self,
        *,
        context_window: int | None = None,
        tool_preview_chars: int | None = None,
        recent_rounds_for_average: int | None = None,
        recent_messages_after_summary: int | None = None,
    ) -> None:
        self.context_window = context_window or CONFIG.memory.default_context_window
        self.tool_preview_chars = tool_preview_chars or CONFIG.memory.tool_preview_chars
        self.recent_rounds_for_average = recent_rounds_for_average or CONFIG.memory.recent_rounds_for_average
        self.recent_messages_after_summary = recent_messages_after_summary or CONFIG.memory.recent_messages_after_summary

    def compress_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        current_prompt: str = "",
        tool_output_refs: dict[str, ToolOutputRef] | None = None,
        summary_text: str = "",
    ) -> CompressionResult:
        current_size = estimate_size(messages) + estimate_size(tools or []) + len(current_prompt)
        predicted_size = self.predict_next_context_size(messages, tools=tools, current_prompt=current_prompt)
        pressure = predicted_size / max(1, self.context_window)
        refs = tool_output_refs or {}
        compressed = [dict(message) for message in messages]
        stage = "none"
        action = "none"

        if pressure < 0.30:
            stage = "full"
            action = "no compression"
        elif pressure < 0.50:
            stage = "preview_largest_tool_outputs"
            action = "preview largest tool outputs"
            compressed = self._preview_tool_outputs(compressed, refs, reproducible_only=False)
        elif pressure < 0.70:
            stage = "drop_reproducible_tool_outputs"
            action = "preview tool outputs and replace reproducible tool outputs"
            compressed = self._preview_tool_outputs(compressed, refs, reproducible_only=False)
            compressed = self._preview_tool_outputs(compressed, refs, reproducible_only=True)
        elif summary_text:
            stage = "summary"
            action = "summarize engineering state and keep recent context"
            compressed = self._summarized_context(compressed, summary_text)
        else:
            stage = "working_context"
            action = "preview recoverable tool outputs and preserve message order"
            compressed = self._preview_tool_outputs(compressed, refs, reproducible_only=False)
        compressed = [sanitize_message_for_model(message) for message in compressed]
        compressed_size = estimate_size(compressed)

        return CompressionResult(
            content=json.dumps(compressed, ensure_ascii=False),
            source_count=len(messages),
            metadata={
                "stage": stage,
                "action": action,
                "pressure_ratio": pressure,
                "current_size": current_size,
                "predicted_size": predicted_size,
                "compressed_size": compressed_size,
                "context_window": self.context_window,
                "messages": compressed,
                "summary_text": summary_text if stage == "summary" else "",
            },
        )

    def should_compress(self, messages: list[dict[str, Any]]) -> bool:
        return self.predict_next_context_size(messages) >= self.context_window * 0.30

    def predict_next_context_size(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        current_prompt: str = "",
    ) -> int:
        return (
            estimate_size(messages)
            + estimate_size(tools or [])
            + len(current_prompt)
            + self.average_recent_output_size(messages)
        )

    def average_recent_output_size(self, messages: list[dict[str, Any]]) -> int:
        outputs = [
            estimate_size(message)
            for message in messages
            if message.get("role") in {"assistant", "tool"}
        ][-self.recent_rounds_for_average:]
        if not outputs:
            return 0
        return int(sum(outputs) / len(outputs))

    def _preview_tool_outputs(
        self,
        messages: list[dict[str, Any]],
        refs: dict[str, ToolOutputRef],
        *,
        reproducible_only: bool,
    ) -> list[dict[str, Any]]:
        ordered_refs = sorted(refs.values(), key=lambda item: item.original_length, reverse=True)
        target_ids = {
            item.output_id
            for item in ordered_refs
            if not reproducible_only or item.reproducible
        }
        result: list[dict[str, Any]] = []
        for message in messages:
            if message.get("role") != "tool":
                result.append(message)
                continue
            output_id = message.get("metadata", {}).get("output_id")
            ref = refs.get(output_id or "")
            if ref is None or ref.output_id not in target_ids:
                result.append(message)
                continue
            replaced = dict(message)
            replaced["content"] = tool_output_reference_text(ref)
            result.append(replaced)
        return result

    def _summarized_context(self, messages: list[dict[str, Any]], summary_text: str) -> list[dict[str, Any]]:
        system_messages = [message for message in messages if message.get("role") == "system"][:1]
        recent = messages[-self.recent_messages_after_summary :]
        summary_message = {
            "role": "system",
            "content": "ENGINEERING STATE SNAPSHOT:\n" + (summary_text or "UNKNOWN"),
        }
        return [*system_messages, summary_message, *recent]


def estimate_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def sanitize_message_for_model(message: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {"role", "content", "name", "tool_call_id", "tool_calls"}
    return {key: value for key, value in message.items() if key in allowed_keys}


def is_reproducible_tool(tool_name: str, output: str = "") -> bool:
    if output.startswith("Tool execution error:") or output.startswith("Error:"):
        return False
    return tool_name in REPRODUCIBLE_TOOLS


def tool_output_reference_text(ref: ToolOutputRef) -> str:
    return (
        "[Tool output stored]\n"
        f"context_id: {ref.output_id}\n"
        f"tool_name: {ref.tool_name}\n"
        f"original_length: {ref.original_length}\n"
        f"preview:\n{ref.preview}\n"
        "recover: Use BatchRecoverContext with this exact context_id in items."
    )
