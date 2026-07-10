from __future__ import annotations

import json

from pydantic import BaseModel, Field

from mycodingagent.multi_agent.domain.contracts import RunJournal
from mycodingagent.tool_runtime.base import Tool, ToolResult


class GetMultiAgentRunParams(BaseModel):
    run_id: str = Field(
        default="",
        description="Optional exact run id. Leave empty to return the latest multi-agent run.",
    )


class GetMultiAgentRun(Tool):
    name = "get_multicoding_run"
    description = (
        "Return the latest or specified multi-agent workflow record, including route, audit, work items, "
        "executor summaries, validation, changed files, and failure details."
    )
    params_model = GetMultiAgentRunParams
    category = "read"
    is_concurrency_safe = True
    is_system_tool = True

    def __init__(self, journal: RunJournal) -> None:
        self._journal = journal

    async def execute(self, params: GetMultiAgentRunParams) -> ToolResult:
        record = self._journal.get(params.run_id) if params.run_id else self._journal.latest()
        if record is None:
            return ToolResult(output="No matching multi-agent run record was found.", is_error=True)
        return ToolResult(output=json.dumps(record, ensure_ascii=False, indent=2))
