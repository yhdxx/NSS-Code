from __future__ import annotations

from pydantic import BaseModel, Field

from mycodingagent.tool_runtime.base import Tool, ToolResult


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
        answer = input("Answer: ")
        return ToolResult(output=answer)
