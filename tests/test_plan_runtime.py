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


class _InvokeSkillParams(BaseModel):
    skill_name: str
    instruction: str
    context: str = ""


class _InvokeSkillTool(Tool):
    name = "invoke_skill"
    description = "test plan skill loader"
    params_model = _InvokeSkillParams
    category = "read"

    async def execute(self, params: _InvokeSkillParams) -> ToolResult:
        assert params.skill_name == "skill_code_plan"
        return ToolResult(f"PLAN SKILL FOR: {params.instruction}")


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


def test_plan_runtime_context_contains_state_without_prompt_instruction() -> None:
    runtime = PlanRuntime(session_id=lambda: "session")
    runtime.enter_plan_mode()
    messages = [{"role": "system", "content": "stable-system"}]

    payload = client._plan_runtime_context(runtime)

    assert messages == [{"role": "system", "content": "stable-system"}]
    assert payload == {"status": "planning", "proposal": None}
    assert "instruction" not in payload


def test_plan_mode_listener_tracks_activation_and_exit() -> None:
    runtime = PlanRuntime(session_id=lambda: "session")
    modes: list[InteractionMode] = []
    runtime.bind_mode_listener(modes.append)

    runtime.enter_plan_mode()
    proposal = runtime.create_proposal("完成需求", ["分析", "测试"])
    runtime.activate_proposal(proposal.id)

    assert modes == [InteractionMode.PLAN, InteractionMode.NORMAL]


def test_plan_skill_load_is_pending_once_per_plan_epoch(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    runtime = PlanRuntime(store=store, session_id=lambda: "session")
    runtime.enter_plan_mode()
    assert runtime.should_load_plan_skill()
    runtime.mark_plan_skill_loaded()

    runtime.restore_current_session()

    assert runtime.is_planning
    assert not runtime.should_load_plan_skill()

    restored = PlanRuntime(store=store, session_id=lambda: "session")
    restored.restore_current_session()
    assert restored.should_load_plan_skill()


def test_plan_skill_is_appended_after_current_user_query() -> None:
    runtime = PlanRuntime(session_id=lambda: "session")
    runtime.enter_plan_mode()
    registry = ToolRegistry()
    registry.register(_InvokeSkillTool())
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": "为认证功能制定计划"},
    ]

    asyncio.run(
        client._append_plan_skill_for_current_query(
            messages,
            prompt="为认证功能制定计划",
            registry=registry,
            plan_runtime=runtime,
        )
    )

    assert [message["role"] for message in messages[-3:]] == ["user", "assistant", "tool"]
    tool_call = messages[-2]["tool_calls"][0]
    arguments = json.loads(tool_call["function"]["arguments"])
    assert tool_call["function"]["name"] == "invoke_skill"
    assert arguments["skill_name"] == "skill_code_plan"
    assert arguments["instruction"] == "为认证功能制定计划"
    assert messages[-1]["tool_call_id"] == tool_call["id"]
    assert messages[-1]["content"] == "PLAN SKILL FOR: 为认证功能制定计划"
    assert messages[-1]["metadata"]["plan_skill_bootstrap"] is True
    assert not runtime.should_load_plan_skill()


def test_plan_execution_rewrite_selects_create_plan_after_automatic_skill_call() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "制定计划"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "skill-call",
                    "type": "function",
                    "function": {"name": "invoke_skill", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "skill-call", "content": "plan skill"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "plan-call",
                    "type": "function",
                    "function": {"name": "create_plan", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "plan-call", "content": "plan result"},
    ]

    asyncio.run(
        client._rewrite_context_for_plan_execution(
            messages,
            turn_start=1,
            project_graph=None,
            work_mode="general",
        )
    )

    assert [message["role"] for message in messages] == ["system", "user", "assistant", "tool"]
    assert messages[-2]["tool_calls"][0]["function"]["name"] == "create_plan"
    assert messages[-1]["tool_call_id"] == "plan-call"


def test_create_plan_rejection_keeps_protocol_complete_messages(monkeypatch) -> None:
    runtime = PlanRuntime(session_id=lambda: "session")
    runtime.enter_plan_mode()
    registry = ToolRegistry()
    registry.register(_InvokeSkillTool())
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
    assistant = next(
        message
        for message in messages
        if message.get("role") == "assistant"
        and any(
            call.get("function", {}).get("name") == "create_plan"
            for call in message.get("tool_calls", [])
        )
    )
    plan_call_id = assistant["tool_calls"][0]["id"]
    tool = next(
        message
        for message in messages
        if message.get("role") == "tool" and message.get("tool_call_id") == plan_call_id
    )
    assert assistant["tool_calls"][0]["id"] == tool["tool_call_id"]
    assert json.loads(tool["content"])["decision"] == "rejected"


def test_plan_mode_rejects_workspace_write_at_execution_even_when_schema_is_visible() -> None:
    runtime = PlanRuntime(session_id=lambda: "session")
    runtime.enter_plan_mode()
    registry = ToolRegistry()
    registry.register(_InvokeSkillTool())
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

    tool_message = next(
        message
        for message in messages
        if message.get("role") == "tool" and message.get("tool_call_id") == "write-call"
    )
    assert "不允许调用工具 WriteFile" in tool_message["content"]
