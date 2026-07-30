from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel

from mycodingagent.llm_runtime.client import execute_local_tool
from mycodingagent.multi_agent.models import AgentRole, MultiAgentRun
from mycodingagent.multi_agent.orchestrator import MultiAgentOrchestrator
from mycodingagent.multi_agent.store import MultiAgentStore
from mycodingagent.tool_runtime import ToolRegistry
from mycodingagent.tool_runtime.base import Tool, ToolResult
from mycodingagent.tool_runtime.execution import execute_tool, parse_tool_arguments_object


class _Params(BaseModel):
    value: str = "ok"


class _JsonTool(Tool):
    name = "JsonTool"
    description = "Return a successful JSON object containing an error field."
    params_model = _Params

    async def execute(self, params: _Params) -> ToolResult:
        return ToolResult(json.dumps({"error": params.value, "status": "ok"}))


def test_shared_executor_uses_explicit_error_flag():
    result = asyncio.run(execute_tool(_JsonTool(), {"value": "diagnostic only"}))

    assert result.is_error is False
    assert json.loads(result.output)["error"] == "diagnostic only"


def test_main_agent_does_not_sniff_error_text():
    registry = ToolRegistry()
    registry.register(_JsonTool())

    result = asyncio.run(
        execute_local_tool(registry, "JsonTool", '{"value":"normal payload"}')
    )

    assert result.is_error is False


def test_subagent_does_not_sniff_error_text(tmp_path):
    registry = ToolRegistry()
    registry.register(_JsonTool())
    store = MultiAgentStore(tmp_path / "multi_agent.sqlite3")
    run = MultiAgentRun.create(task="test shared execution")
    store.save_run(run)
    orchestrator = MultiAgentOrchestrator(
        store=store, registry=registry, api_client=object(), memory_runtime=None
    )

    result = asyncio.run(
        orchestrator._execute_subagent_tool(
            role=AgentRole.PLAN,
            run_id=run.run_id,
            tool_call_id="call_1",
            tool_name="JsonTool",
            raw_args='{"value":"normal payload"}',
        )
    )

    assert result.is_error is False
    assert json.loads(result.output)["error"] == "normal payload"


def test_argument_parser_rejects_invalid_or_non_object_json():
    assert parse_tool_arguments_object("[1]")[1]
    assert parse_tool_arguments_object("{")[1]
    assert parse_tool_arguments_object('{"value":1}')[0] == {"value": 1}
