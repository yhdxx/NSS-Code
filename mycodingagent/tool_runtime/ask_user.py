from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from mycodingagent.tool_runtime.base import Tool, ToolResult
from mycodingagent.terminal_ui.interrupt import PromptCancelled, TerminalInputCoordinator


class AskUserParams(BaseModel):
    query: str = Field(description="Question to ask the terminal user")
    choice: str | None = Field(default=None, description="Optional choices to show under the question")
    intent: str = Field(description="Short reason why user input is required")


class AskUser(Tool):
    name = "ask_user"
    description = (
        "Ask the terminal user for missing information when it cannot be safely inferred "
        "from available tools or context. Use this instead of guessing user-specific data."
    )
    params_model = AskUserParams
    category = "read"
    is_concurrency_safe = False
    is_system_tool = True

    def __init__(self, coordinator: TerminalInputCoordinator | None = None) -> None:
        self._coordinator = coordinator

    async def execute(self, params: AskUserParams) -> ToolResult:
        intent = " ".join(params.intent.split())
        query = " ".join(params.query.split())
        choice = "\n".join(line.rstrip() for line in str(params.choice or "").splitlines()).strip()
        print("[User Input Required]", flush=True)
        if intent:
            print(f"Intent: {intent}", flush=True)
        if choice:
            print(f"Question: {query}\n{choice}", flush=True)
        else:
            print(f"Question: {query}", flush=True)
        try:
            answer = (
                await self._coordinator.read_text("Answer: ")
                if self._coordinator is not None
                else await asyncio.to_thread(input, "Answer: ")
            )
        except PromptCancelled:
            return ToolResult(output="用户取消了本次输入", is_error=True)
        return ToolResult(output=answer)
