from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from mycodingagent.tool_runtime.base import Tool, ToolResult
from mycodingagent.terminal_ui.interrupt import PromptCancelled, TerminalInputCoordinator


class AskUserParams(BaseModel):
    query: str = Field(description="要向终端用户提出的问题")
    choice: str | None = Field(default=None, description="可选的候选项文本")
    intent: str = Field(description="需要用户输入的简短原因")


class AskUser(Tool):
    name = "ask_user"
    description = (
        "向终端用户询问无法通过现有工具或上下文可靠确认的必要信息。"
        "涉及用户特有数据时使用本工具，不要猜测。"
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
        print("[需要用户输入]", flush=True)
        if intent:
            print(f"目的：{intent}", flush=True)
        if choice:
            print(f"问题：{query}\n{choice}", flush=True)
        else:
            print(f"问题：{query}", flush=True)
        try:
            answer = (
                await self._coordinator.read_text("回答：")
                if self._coordinator is not None
                else await asyncio.to_thread(input, "回答：")
            )
        except PromptCancelled:
            return ToolResult(output="用户取消了本次输入", is_error=True)
        return ToolResult(output=answer)
