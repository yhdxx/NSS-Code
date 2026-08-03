from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel

from mycodingagent.llm_runtime.client import execute_local_tool
from mycodingagent.multi_agent.models import AgentRole, MultiAgentRun
from mycodingagent.multi_agent.orchestrator import MultiAgentOrchestrator
from tests.model_manager_stub import RawClientModelManager
from mycodingagent.multi_agent.store import MultiAgentStore
from mycodingagent.tool_runtime import ToolRegistry
from mycodingagent.tool_runtime.base import Tool, ToolResult
from mycodingagent.tool_runtime.execution import (
    CodeQueryLedger,
    RepeatedFailureTracker,
    ToolExecution,
    execute_tool,
    parse_tool_arguments_object,
)


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
        store=store,
        registry=registry,
        model_manager=RawClientModelManager(object()),
        memory_runtime=None,
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


def test_repeated_failure_tracker_blocks_third_identical_call():
    tracker = RepeatedFailureTracker()
    failure = ToolExecution("failed", is_error=True)

    tracker.annotate("Bash", '{"command":"false"}', failure)
    tracker.annotate("Bash", '{"command": "false"}', failure)

    blocked = tracker.preflight("Bash", '{"command":"false"}')
    assert blocked is not None
    assert blocked.is_error is True


def test_mutation_gate_is_not_reset_by_read_only_success():
    tracker = RepeatedFailureTracker()
    for index in range(3):
        tracker.annotate(
            "WriteFile",
            json.dumps({"file_path": f"{index}.txt"}),
            ToolExecution("failed", is_error=True),
            is_mutation=True,
        )
    tracker.annotate("ReadFile", '{"file_path":"a.txt"}', ToolExecution("ok"))

    blocked = tracker.preflight(
        "WriteFile", '{"file_path":"next.txt"}', is_mutation=True
    )
    assert blocked is not None
    assert "修改操作门禁" in blocked.output


def test_write_failure_gate_does_not_block_bash_when_not_marked_as_write():
    tracker = RepeatedFailureTracker()
    for index in range(3):
        tracker.annotate(
            "WriteFile",
            json.dumps({"file_path": f"{index}.txt"}),
            ToolExecution("failed", is_error=True),
            is_mutation=True,
        )

    blocked = tracker.preflight(
        "Bash",
        '{"command":"python3 -m pytest -q"}',
        is_mutation=False,
    )

    assert blocked is None


def test_code_query_ledger_blocks_identical_success_but_allows_changed_scope():
    ledger = CodeQueryLedger()
    first = '{"operation":"impact","query":"Bash","intent":"first"}'
    same_query = '{"query":"Bash","operation":"impact","intent":"again"}'

    ledger.record("code_index", first, ToolExecution("ok"))

    assert ledger.preflight("code_index", same_query) is not None
    assert ledger.preflight("code_index", '{"operation":"impact","query":"Bash","depth":2}') is None
    assert ledger.preflight("Grep", first) is None


def test_code_query_ledger_blocks_repeated_failed_lsp_query():
    ledger = CodeQueryLedger()
    query = '{"operation":"references","path":"sample.py","line":1}'

    ledger.record("lsp", query, ToolExecution("unavailable", is_error=True))

    blocked = ledger.preflight("lsp", query)

    assert blocked is not None
    assert "fallback" in blocked.output
