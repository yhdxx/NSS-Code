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
    estimated_tokens: int
    remaining_tokens: int
    reserved_reasoning_tokens: int
    reserved_output_tokens: int
    reserved_tool_tokens: int
    usable_tokens: int
    usage_ratio: float
    stage: BudgetStage
    calibrated_from_api: bool = False

    def to_prompt_text(self) -> str:
        return (
            "PROMPT 预算\n"
            f"context_window: {self.context_window}\n"
            f"current_tokens: {self.current_tokens}\n"
            f"estimated_tokens: {self.estimated_tokens}\n"
            f"remaining_tokens: {self.remaining_tokens}\n"
            f"reserved_reasoning_tokens: {self.reserved_reasoning_tokens}\n"
            f"reserved_output_tokens: {self.reserved_output_tokens}\n"
            f"reserved_tool_tokens: {self.reserved_tool_tokens}\n"
            f"usable_tokens: {self.usable_tokens}\n"
            f"usage_ratio: {self.usage_ratio:.2%}\n"
            f"stage: {self.stage.value}"
        )


@dataclass(frozen=True)
class PromptTokenBaseline:
    exact_tokens: int
    estimated_tokens: int
    model: str = ""


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
        baseline: PromptTokenBaseline | None = None,
    ) -> PromptBudgetSnapshot:
        estimated_tokens = (
            estimate_tokens(messages)
            + estimate_tokens(tools or [])
            + estimate_tokens(current_prompt)
            + extra_tokens
        )
        calibrated_from_api = bool(
            baseline is not None
            and baseline.exact_tokens > 0
            and baseline.estimated_tokens > 0
        )
        current_tokens = estimated_tokens
        if calibrated_from_api and baseline is not None:
            estimated_delta = estimated_tokens - baseline.estimated_tokens
            current_tokens = max(0, baseline.exact_tokens + estimated_delta)
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
            estimated_tokens=estimated_tokens,
            remaining_tokens=remaining_tokens,
            reserved_reasoning_tokens=self.reserved_reasoning_tokens,
            reserved_output_tokens=self.reserved_output_tokens,
            reserved_tool_tokens=self.reserved_tool_tokens,
            usable_tokens=usable_tokens,
            usage_ratio=usage_ratio,
            stage=self.stage_for_usage(usage_ratio),
            calibrated_from_api=calibrated_from_api,
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
    if not text:
        return 0
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return (ascii_chars + 3) // 4 + non_ascii_chars
