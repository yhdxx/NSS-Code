from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel

from mycodingagent.llm_runtime import client
from mycodingagent.llm_runtime.providers.base import PendingToolCall, StreamRoundResult
from mycodingagent.memory.stores import SQLiteMemoryStore
from mycodingagent.plan_runtime import (
    CreatePlan,
    InteractionMode,
    PlanRuntime,
    PlanStatus,
    PlanStepStatus,
    TurnToolPolicy,
    UpdatePlanStep,
)
from mycodingagent.plan_runtime.tools import UpdatePlanStepParams
from mycodingagent.tool_runtime import ToolRegistry
from mycodingagent.tool_runtime.base import Tool, ToolResult


class _NoParams(BaseModel):
    pass


class _WorkspaceWriteTool(Tool):
    name = "WriteFile"
    description = "test write"
    params_model = _NoParams
    category = "write"

    async def execute(self, _params) -> ToolResult:
        raise AssertionError("Plan execution gate must reject this tool")


def test_plan_runtime_persists_mode_plan_and_atomic_progress(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    session_id = "session-1"
    runtime = PlanRuntime(store=store, session_id=lambda: session_id)

    runtime.enter_plan_mode()
    proposal = runtime.create_proposal("完成需求", ["分析代码", "实现修改"])
    runtime.activate_proposal(proposal.id)
    runtime.update_step(
        plan_id=proposal.id,
        step_id=proposal.steps[0].id,
        status=PlanStepStatus.IN_PROGRESS,
    )

    restored = PlanRuntime(store=store, session_id=lambda: session_id)
    restored.restore_current_session()
    plan = restored.active_plan()

    assert restored.mode is InteractionMode.NORMAL
    assert plan is not None
    assert plan.id == proposal.id
    assert plan.steps[0].status is PlanStepStatus.IN_PROGRESS


def test_update_plan_step_returns_the_complete_plan() -> None:
    runtime = PlanRuntime(session_id=lambda: "session")
    runtime.enter_plan_mode()
    proposal = runtime.create_proposal("完成需求", ["第一步", "第二步"])
    runtime.activate_proposal(proposal.id)
    tool = UpdatePlanStep(runtime)

    result = asyncio.run(
        tool.execute(
            UpdatePlanStepParams(
                plan_id=proposal.id,
                step_id=proposal.steps[0].id,
                status=PlanStepStatus.IN_PROGRESS,
                note="开始处理",
            )
        )
    )
    payload = json.loads(result.output)

    assert payload["objective"] == "完成需求"
    assert [step["text"] for step in payload["steps"]] == ["第一步", "第二步"]
    assert payload["steps"][0]["status"] == "in_progress"
    assert payload["steps"][0]["note"] == "开始处理"


def test_plan_policy_blocks_workspace_writes_bash_and_mcp_but_allows_requested_runtime_tools() -> None:
    policy = TurnToolPolicy(InteractionMode.PLAN)

    class Tool:
        def __init__(self, name: str, category: str = "read") -> None:
            self.name = name
            self.category = category

    assert not policy.allows(Tool("WriteFile", "write"))
    assert not policy.allows(Tool("EditFile", "write"))
    assert not policy.allows(Tool("Bash", "command"))
    assert not policy.allows(Tool("call_mcp_tool", "command"))
    assert policy.allows(Tool("invoke_skill", "command"))
    assert policy.allows(Tool("CommitWorkingContext", "command"))
    assert policy.allows(Tool("RestoreSession", "read"))
    assert policy.allows(Tool("UpdateProjectDescription", "read"))


def test_plan_instruction_is_in_runtime_context_without_changing_system_message() -> None:
    runtime = PlanRuntime(session_id=lambda: "session")
    runtime.enter_plan_mode()
    messages = [{"role": "system", "content": "stable-system"}]

    payload = client._plan_runtime_context(runtime)

    assert messages == [{"role": "system", "content": "stable-system"}]
    assert payload is not None
    assert "测试策略" in payload["instruction"]
    assert "验收标准" in payload["instruction"]
    runtime.mark_planning_instruction_delivered()
    later_payload = client._plan_runtime_context(runtime)
    assert later_payload is not None
    assert "instruction" not in later_payload


def test_plan_mode_listener_tracks_activation_and_exit() -> None:
    runtime = PlanRuntime(session_id=lambda: "session")
    modes: list[InteractionMode] = []
    runtime.bind_mode_listener(modes.append)

    runtime.enter_plan_mode()
    proposal = runtime.create_proposal("完成需求", ["分析", "测试"])
    runtime.activate_proposal(proposal.id)

    assert modes == [InteractionMode.PLAN, InteractionMode.NORMAL]


def test_restoring_same_plan_epoch_does_not_reinject_instruction(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    runtime = PlanRuntime(store=store, session_id=lambda: "session")
    runtime.enter_plan_mode()
    runtime.mark_planning_instruction_delivered()

    runtime.restore_current_session()

    assert runtime.is_planning
    assert not runtime.should_inject_planning_instruction()


def test_create_plan_rejection_keeps_protocol_complete_messages(monkeypatch) -> None:
    runtime = PlanRuntime(session_id=lambda: "session")
    runtime.enter_plan_mode()
    registry = ToolRegistry()
    registry.register(CreatePlan(runtime))
    registry.register(_WorkspaceWriteTool())
    seen_tools: list[str] = []

    class Provider:
        model = "test-model"

        async def stream_chat(self, request):
            seen_tools.extend(tool["function"]["name"] for tool in request.tools)
            return StreamRoundResult(
                "",
                [
                    PendingToolCall(
                        "plan-call",
                        "create_plan",
                        json.dumps(
                            {
                                "objective": "完成修改",
                                "steps": [{"text": "分析"}, {"text": "实现"}],
                                "intent": "提交计划",
                            },
                            ensure_ascii=False,
                        ),
                    )
                ],
            )

    class ModelManager:
        active_model = "test-model"

        def active_provider(self):
            return Provider()

    async def reject(_preview, _options):
        return 2

    monkeypatch.setattr(client, "request_plan_selection", reject)
    monkeypatch.setattr(client, "render_assistant_markdown", lambda *_args, **_kwargs: None)

    _text, messages = asyncio.run(
        client.ask_model(
            ModelManager(),
            "请制定计划",
            registry,
            client.format_openai_tools(registry.get_all_schemas("openai")),
            [{"role": "system", "content": "stable-system"}],
            plan_runtime=runtime,
        )
    )

    assert runtime.current_plan() is not None
    assert runtime.current_plan().status is PlanStatus.REJECTED
    assert "create_plan" in seen_tools
    assert "WriteFile" in seen_tools
    assistant = next(message for message in messages if message.get("role") == "assistant")
    tool = next(message for message in messages if message.get("role") == "tool")
    assert assistant["tool_calls"][0]["id"] == tool["tool_call_id"]
    assert json.loads(tool["content"])["decision"] == "rejected"


def test_plan_mode_rejects_workspace_write_at_execution_even_when_schema_is_visible() -> None:
    runtime = PlanRuntime(session_id=lambda: "session")
    runtime.enter_plan_mode()
    registry = ToolRegistry()
    registry.register(_WorkspaceWriteTool())

    class Provider:
        model = "test-model"

        def __init__(self) -> None:
            self.calls = 0

        async def stream_chat(self, _request):
            self.calls += 1
            if self.calls == 1:
                return StreamRoundResult(
                    "",
                    [PendingToolCall("write-call", "WriteFile", '{"intent":"test"}')],
                )
            return StreamRoundResult("无法在 Plan 模式写入。", [])

    provider = Provider()

    class ModelManager:
        active_model = "test-model"

        def active_provider(self):
            return provider

    _text, messages = asyncio.run(
        client.ask_model(
            ModelManager(),
            "请先规划",
            registry,
            client.format_openai_tools(registry.get_all_schemas("openai")),
            [{"role": "system", "content": "stable-system"}],
            plan_runtime=runtime,
        )
    )

    tool_message = next(message for message in messages if message.get("role") == "tool")
    assert "不允许调用工具 WriteFile" in tool_message["content"]
