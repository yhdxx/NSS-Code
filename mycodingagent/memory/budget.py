from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class BudgetStage(str, Enum):
    NORMAL = "normal"
    SOFT = "soft"
    WORKING = "working"
    EMERGENCY = "emergency"


@dataclass(frozen=True)
class PromptBudgetSnapshot:
    context_window: int
    current_tokens: int
    remaining_tokens: int
    reserved_reasoning_tokens: int
    reserved_output_tokens: int
    reserved_tool_tokens: int
    usable_tokens: int
    usage_ratio: float
    stage: BudgetStage

    def to_prompt_text(self) -> str:
        return (
            "PROMPT 预算\n"
            f"context_window: {self.context_window}\n"
            f"current_tokens: {self.current_tokens}\n"
            f"remaining_tokens: {self.remaining_tokens}\n"
            f"reserved_reasoning_tokens: {self.reserved_reasoning_tokens}\n"
            f"reserved_output_tokens: {self.reserved_output_tokens}\n"
            f"reserved_tool_tokens: {self.reserved_tool_tokens}\n"
            f"usable_tokens: {self.usable_tokens}\n"
            f"usage_ratio: {self.usage_ratio:.2%}\n"
            f"stage: {self.stage.value}"
        )


class PromptBudgetManager:
    def __init__(
        self,
        *,
        context_window: int,
        soft_ratio: float,
        working_ratio: float,
        emergency_ratio: float,
        reserved_reasoning_tokens: int,
        reserved_output_tokens: int,
        reserved_tool_tokens: int,
    ) -> None:
        self.context_window = context_window
        self.soft_ratio = soft_ratio
        self.working_ratio = working_ratio
        self.emergency_ratio = emergency_ratio
        self.reserved_reasoning_tokens = reserved_reasoning_tokens
        self.reserved_output_tokens = reserved_output_tokens
        self.reserved_tool_tokens = reserved_tool_tokens

    def snapshot(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        current_prompt: str = "",
        extra_tokens: int = 0,
    ) -> PromptBudgetSnapshot:
        current_tokens = estimate_tokens(messages) + estimate_tokens(tools or []) + estimate_tokens(current_prompt) + extra_tokens
        remaining_tokens = max(0, self.context_window - current_tokens)
        usable_tokens = max(
            0,
            remaining_tokens
            - self.reserved_reasoning_tokens
            - self.reserved_output_tokens
            - self.reserved_tool_tokens,
        )
        usage_ratio = current_tokens / max(1, self.context_window)
        return PromptBudgetSnapshot(
            context_window=self.context_window,
            current_tokens=current_tokens,
            remaining_tokens=remaining_tokens,
            reserved_reasoning_tokens=self.reserved_reasoning_tokens,
            reserved_output_tokens=self.reserved_output_tokens,
            reserved_tool_tokens=self.reserved_tool_tokens,
            usable_tokens=usable_tokens,
            usage_ratio=usage_ratio,
            stage=self.stage_for_usage(usage_ratio),
        )

    def stage_for_usage(self, usage_ratio: float) -> BudgetStage:
        if usage_ratio >= self.emergency_ratio:
            return BudgetStage.EMERGENCY
        if usage_ratio >= self.working_ratio:
            return BudgetStage.WORKING
        if usage_ratio >= self.soft_ratio:
            return BudgetStage.SOFT
        return BudgetStage.NORMAL


def estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return max(1, len(text) // 4)
