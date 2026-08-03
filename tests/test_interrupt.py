from __future__ import annotations

import asyncio

from mycodingagent.llm_runtime import client as agent_client
from mycodingagent.llm_runtime.streaming import PendingToolCall, StreamRoundResult
from mycodingagent.tool_runtime.execution import ToolExecution
from tests.model_manager_stub import ask_model_with_raw_client


def test_interruption_between_tools_keeps_protocol_pairs(monkeypatch):
    async def scenario():
        cancel_event = asyncio.Event()
        calls = [
            PendingToolCall("call_1", "FakeTool", "{}"),
            PendingToolCall("call_2", "FakeTool", "{}"),
        ]

        async def fake_stream(*args, **kwargs):
            return StreamRoundResult("", calls)

        executed: list[str] = []

        async def fake_execute(registry, tool_name, raw_args, **kwargs):
            executed.append(tool_name)
            cancel_event.set()
            return ToolExecution("first completed")

        monkeypatch.setattr(agent_client, "stream_one_round", fake_stream)
        monkeypatch.setattr(agent_client, "execute_local_tool", fake_execute)

        text, messages = await ask_model_with_raw_client(
            raw_client=object(),
            prompt="do two things",
            registry=object(),
            tools=[],
            messages=[{"role": "system", "content": "fixed"}],
            cancel_event=cancel_event,
        )

        assistant_calls = next(message["tool_calls"] for message in messages if message.get("tool_calls"))
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert {call["id"] for call in assistant_calls} == {
            message["tool_call_id"] for message in tool_messages
        }
        assert executed == ["FakeTool"]
        assert tool_messages[0]["content"] == "first completed"
        assert "未执行" in tool_messages[1]["content"]
        assert "Error: API" not in text
        assert messages[-1]["metadata"]["interrupted"] is True

    asyncio.run(scenario())


def test_stream_interruption_is_not_an_api_error(monkeypatch):
    async def scenario():
        cancel_event = asyncio.Event()
        cancel_event.set()

        class _Completions:
            async def create(self, **kwargs):
                raise AssertionError("request should be cancelled before it starts")

        class _Client:
            class _Chat:
                completions = _Completions()

            chat = _Chat()

        result = await agent_client.stream_one_round(
            _Client(), "model", [], [], display=False, cancel_event=cancel_event
        )
        assert result.interrupted is True
        assert not result.text.startswith("Error: API")

    asyncio.run(scenario())


def test_queued_follow_up_pauses_after_completed_tool_and_keeps_protocol_pairs(monkeypatch):
    async def scenario():
        follow_up_event = asyncio.Event()
        calls = [
            PendingToolCall("call_1", "FakeTool", "{}"),
            PendingToolCall("call_2", "FakeTool", "{}"),
        ]

        async def fake_stream(*args, **kwargs):
            return StreamRoundResult("", calls)

        executed: list[str] = []

        async def fake_execute(registry, tool_name, raw_args, **kwargs):
            executed.append(tool_name)
            follow_up_event.set()
            return ToolExecution("first completed")

        monkeypatch.setattr(agent_client, "stream_one_round", fake_stream)
        monkeypatch.setattr(agent_client, "execute_local_tool", fake_execute)

        text, messages = await ask_model_with_raw_client(
            raw_client=object(),
            prompt="do two things",
            registry=object(),
            tools=[],
            messages=[{"role": "system", "content": "fixed"}],
            follow_up_event=follow_up_event,
        )

        assistant_calls = next(message["tool_calls"] for message in messages if message.get("tool_calls"))
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert {call["id"] for call in assistant_calls} == {
            message["tool_call_id"] for message in tool_messages
        }
        assert executed == ["FakeTool"]
        assert tool_messages[0]["content"] == "first completed"
        assert "排队消息" in tool_messages[1]["content"]
        assert "工具调用结束后暂停" in text
        assert messages[-1]["metadata"]["queued_follow_up"] is True

    asyncio.run(scenario())
