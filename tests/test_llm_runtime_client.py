from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel

from mycodingagent.llm_runtime import client
from mycodingagent.llm_runtime.system_prompt import PromptFeatures, build_system_prompt
from mycodingagent.tool_runtime import ToolRegistry
from mycodingagent.tool_runtime.base import Tool, ToolResult


class _Delta:
    def __init__(self, content: str | None = None, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, delta: _Delta) -> None:
        self.delta = delta


class _Chunk:
    def __init__(self, delta: _Delta, usage=None) -> None:
        self.choices = [_Choice(delta)]
        self.usage = usage


class _FunctionDelta:
    def __init__(self, name: str | None = None, arguments: str | None = None) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCallDelta:
    def __init__(self, index: int, tool_id: str | None = None, function: _FunctionDelta | None = None) -> None:
        self.index = index
        self.id = tool_id
        self.function = function


def _text_chunk(text: str) -> _Chunk:
    return _Chunk(_Delta(content=text))


def _tool_call_chunks(tool_id: str, name: str, arguments: str) -> list[_Chunk]:
    """Split a tool call across chunks the way the real streaming API does."""
    return [
        _Chunk(_Delta(tool_calls=[_ToolCallDelta(0, tool_id=tool_id, function=_FunctionDelta(name=name))])),
        _Chunk(_Delta(tool_calls=[_ToolCallDelta(0, function=_FunctionDelta(arguments=arguments))])),
    ]


class _FakeStream:
    """Async-iterable stream. Raises `raise_at` partway through if provided."""

    def __init__(self, chunks: list[_Chunk], raise_at: int | None = None, error: Exception | None = None) -> None:
        self._chunks = chunks
        self._raise_at = raise_at
        self._error = error

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for index, chunk in enumerate(self._chunks):
            if self._raise_at is not None and index == self._raise_at:
                raise self._error or APIConnectionError(request=_request())
            yield chunk


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.deepseek.com/chat/completions")


def _status_error(status_code: int) -> APIStatusError:
    response = httpx.Response(status_code, request=_request())
    return APIStatusError("boom", response=response, body=None)


class _FakeCompletions:
    """Records each request and returns the next scripted outcome."""

    def __init__(self, outcomes: list) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._outcomes:
            raise AssertionError("unexpected extra API request")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeClient:
    def __init__(self, outcomes: list) -> None:
        self.completions = _FakeCompletions(outcomes)
        self.chat = type("_Chat", (), {"completions": self.completions})()


class _EchoParams(BaseModel):
    text: str = ""


class _EchoTool(Tool):
    name = "EchoTool"
    description = "Return the provided text verbatim."
    params_model = _EchoParams
    category = "read"

    def __init__(self, output: str = "ok", is_error: bool = False) -> None:
        self._output = output
        self._is_error = is_error

    async def execute(self, params) -> ToolResult:  # noqa: ANN001
        return ToolResult(output=self._output, is_error=self._is_error)


def _registry(tool: Tool | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool or _EchoTool())
    return registry


def _no_sleep(monkeypatch) -> list[float]:
    """Make retry backoff instant while recording the delays that were requested."""
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(client.asyncio, "sleep", fake_sleep)
    return delays


def _run_stream(fake_client, tools=None):
    result = asyncio.run(
        client.stream_one_round(fake_client, "test-model", [{"role": "user", "content": "hi"}], tools or [])
    )
    return result.text, result.tool_calls, result.usage


def test_system_prompt_requires_mcp_tool_discovery_before_execution():
    prompt = build_system_prompt(PromptFeatures(mcp_enabled=True))

    assert "call_mcp_tool 前必须先通过 list_mcp_tools 或 search_mcp_tools" in prompt
    assert "名称、描述和参数元数据" in prompt
    assert "仅知道 Server 或工具名称不满足门禁" in prompt


def test_system_prompt_includes_only_enabled_capability_modules():
    core = build_system_prompt(PromptFeatures())
    full = build_system_prompt(
        PromptFeatures(skills_enabled=True, mcp_enabled=True, memory_enabled=True),
        skill_hint="Use project-skill for release work.",
    )

    assert "## Skills" not in core
    assert "## MCP" not in core
    assert "## 记忆" not in core
    assert "## Skills" in full
    assert "## MCP" in full
    assert "## 记忆" in full
    assert "Use project-skill for release work." in full
    assert len(core) < 6500


def test_system_prompt_uses_chinese_for_agent_authored_instructions():
    prompt = build_system_prompt(
        PromptFeatures(skills_enabled=True, mcp_enabled=True, memory_enabled=True, code_intelligence_enabled=True)
    )

    assert "## 角色" in prompt
    assert "## 工具选择" in prompt
    assert "## 代码智能" in prompt
    assert "## Role" not in prompt
    assert "## Tool Selection" not in prompt
    assert "Before producing the final answer" not in prompt


# --- retry behaviour -------------------------------------------------------


def test_stream_retries_connection_error_then_succeeds(monkeypatch, capsys):
    delays = _no_sleep(monkeypatch)
    fake = _FakeClient([APIConnectionError(request=_request()), _FakeStream([_text_chunk("hello")])])

    text, tool_calls, _ = _run_stream(fake)

    assert text == "hello"
    assert tool_calls == []
    assert len(fake.completions.calls) == 2
    assert delays, "expected a backoff sleep between attempts"


def test_stream_renders_final_answer_as_markdown(capsys):
    fake = _FakeClient([_FakeStream([_text_chunk("**Done**\n\n- `app.py` updated")])])

    text, tool_calls, _ = _run_stream(fake)
    output = capsys.readouterr().out

    assert text == "**Done**\n\n- `app.py` updated"
    assert tool_calls == []
    assert "模型：" in output
    assert "Done" in output
    assert "app.py updated" in output
    assert "**Done**" not in output


def test_stream_retry_does_not_duplicate_partial_output(monkeypatch):
    """A stream that dies mid-iteration must not leave its partial text in the retried result."""
    _no_sleep(monkeypatch)
    dying = _FakeStream([_text_chunk("par"), _text_chunk("tial")], raise_at=1)
    fake = _FakeClient([dying, _FakeStream([_text_chunk("complete")])])

    text, tool_calls, _ = _run_stream(fake)

    assert text == "complete"
    assert "par" not in text
    assert tool_calls == []


def test_stream_retry_does_not_duplicate_partial_tool_calls(monkeypatch):
    """Half-streamed tool-call arguments must be discarded, not concatenated across attempts."""
    _no_sleep(monkeypatch)
    chunks = _tool_call_chunks("call_1", "EchoTool", '{"text":"a"}')
    dying = _FakeStream(chunks, raise_at=1)
    fake = _FakeClient([dying, _FakeStream(_tool_call_chunks("call_1", "EchoTool", '{"text":"a"}'))])

    _, tool_calls, _ = _run_stream(fake)

    assert len(tool_calls) == 1
    assert tool_calls[0].arguments == '{"text":"a"}'
    json.loads(tool_calls[0].arguments)


def test_stream_retries_timeout_error(monkeypatch):
    _no_sleep(monkeypatch)
    fake = _FakeClient([APITimeoutError(request=_request()), _FakeStream([_text_chunk("ok")])])

    text, _, _ = _run_stream(fake)

    assert text == "ok"
    assert len(fake.completions.calls) == 2


@pytest.mark.parametrize("status_code", [500, 503, 429])
def test_stream_retries_retryable_status_codes(monkeypatch, status_code):
    _no_sleep(monkeypatch)
    fake = _FakeClient([_status_error(status_code), _FakeStream([_text_chunk("ok")])])

    text, _, _ = _run_stream(fake)

    assert text == "ok"
    assert len(fake.completions.calls) == 2


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
def test_stream_does_not_retry_client_errors(monkeypatch, status_code):
    """4xx means the request itself is wrong -- retrying it is pure waste."""
    _no_sleep(monkeypatch)
    fake = _FakeClient([_status_error(status_code)])

    text, tool_calls, usage = _run_stream(fake)

    assert text.startswith("Error: API ")
    assert tool_calls == []
    assert usage is None
    assert len(fake.completions.calls) == 1, "4xx must not be retried"


def test_stream_gives_up_after_max_retries(monkeypatch):
    _no_sleep(monkeypatch)
    attempts = client.API_MAX_RETRIES + 1
    fake = _FakeClient([APIConnectionError(request=_request()) for _ in range(attempts)])

    text, _, _ = _run_stream(fake)

    assert text.startswith("Error: API ")
    assert len(fake.completions.calls) == attempts


def test_mid_stream_failure_does_not_propagate(monkeypatch):
    """An exception during chunk iteration must be converted to an error string, never bubble out."""
    _no_sleep(monkeypatch)
    attempts = client.API_MAX_RETRIES + 1
    outcomes = [
        _FakeStream([_text_chunk("x"), _text_chunk("y")], raise_at=1) for _ in range(attempts)
    ]
    fake = _FakeClient(outcomes)

    text, _, _ = _run_stream(fake)

    assert text.startswith("Error: API ")


# --- tool failure detection ----------------------------------------------


def test_execute_local_tool_reports_success():
    execution = asyncio.run(
        client.execute_local_tool(_registry(), "EchoTool", '{"text":"hi"}')
    )

    assert execution.output == "ok"
    assert execution.is_error is False


def test_execute_local_tool_propagates_tool_is_error():
    registry = _registry(_EchoTool(output="Something broke", is_error=True))

    execution = asyncio.run(client.execute_local_tool(registry, "EchoTool", "{}"))

    assert execution.output == "Something broke"
    assert execution.is_error is True


def test_execute_local_tool_flags_unknown_tool():
    execution = asyncio.run(client.execute_local_tool(_registry(), "NoSuchTool", "{}"))

    assert execution.is_error is True
    assert "未知工具" in execution.output


def test_execute_local_tool_flags_invalid_json():
    execution = asyncio.run(client.execute_local_tool(_registry(), "EchoTool", "{not json"))

    assert execution.is_error is True
    assert "JSON 参数无效" in execution.output


def test_successful_output_containing_error_word_is_not_a_failure():
    """Reading a JSON file whose body contains "error" must not be misread as a tool failure."""
    payload = json.dumps({"status": "passed", "error": None, "detail": "all good"})
    registry = _registry(_EchoTool(output=payload, is_error=False))

    execution = asyncio.run(client.execute_local_tool(registry, "EchoTool", "{}"))

    assert execution.output == payload
    assert execution.is_error is False, 'a successful result must stay successful even when it contains "error"'


# --- API failure must not discard completed work ---------------------------


def _run_ask_deepseek(monkeypatch, stream_outcomes: list, tool_output: tuple[str, bool] = ("tool ok", False)):
    """Drive ask_deepseek with scripted stream_one_round results, bypassing memory/skill runtimes."""
    executed: list[str] = []

    async def fake_build_round_tools(default_tools, core_tool_schemas):
        return []

    outcomes = list(stream_outcomes)

    async def fake_stream_one_round(_client, _model, _messages, _tools):
        return outcomes.pop(0)

    async def fake_execute_local_tool(registry, tool_name, raw_args, skill_runtime):
        executed.append(tool_name)
        return client.ToolExecution(tool_output[0], tool_output[1])

    monkeypatch.setattr(client, "build_round_tools", fake_build_round_tools)
    monkeypatch.setattr(client, "stream_one_round", fake_stream_one_round)
    monkeypatch.setattr(client, "execute_local_tool", fake_execute_local_tool)

    history = [{"role": "system", "content": "fixed system"}]
    text, updated = asyncio.run(
        client.ask_deepseek(
            client=object(),
            prompt="do work",
            registry=object(),
            tools=[],
            messages=history,
        )
    )
    return text, updated, executed


def test_api_failure_preserves_completed_tool_rounds(monkeypatch):
    """The core regression: a late API failure must not wipe out tool results already obtained."""
    api_error = ("Error: API connection failed: boom", [], None)
    outcomes = [
        ("", [client.PendingToolCall("call_1", "FakeTool", "{}")], None),
        ("", [client.PendingToolCall("call_2", "FakeTool", "{}")], None),
        api_error,
    ]

    text, updated, executed = _run_ask_deepseek(monkeypatch, outcomes)

    assert text.startswith("Error: API ")
    assert executed == ["FakeTool", "FakeTool"], "both tool rounds should have run"

    roles = [message.get("role") for message in updated]
    assert "user" in roles, "the user message must survive"
    tool_messages = [message for message in updated if message.get("role") == "tool"]
    assert len(tool_messages) == 2, "completed tool results must be preserved, not discarded"
    assert any("继续" in str(message.get("content", "")) for message in updated), (
        "the user should be told the work was kept and can be resumed"
    )


def test_api_failure_with_no_progress_rolls_back_cleanly(monkeypatch):
    """When nothing was accomplished, the turn should roll back rather than leave a stray user message."""
    outcomes = [("Error: API connection failed: boom", [], None)]

    text, updated, executed = _run_ask_deepseek(monkeypatch, outcomes)

    assert text.startswith("Error: API ")
    assert executed == []
    assert updated == [{"role": "system", "content": "fixed system"}], (
        "a turn with no progress should roll back to the pre-turn state"
    )
