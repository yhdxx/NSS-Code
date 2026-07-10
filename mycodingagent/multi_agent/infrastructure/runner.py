from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from mycodingagent.llm_runtime import client as agent_client
from mycodingagent.multi_agent.domain.contracts import RuntimeEventSink
from mycodingagent.multi_agent.domain.models import AgentRequest, AgentResult
from mycodingagent.multi_agent.domain.models import RuntimeEvent
from mycodingagent.multi_agent.infrastructure.permissions import ToolAccessPolicy, ToolPermissionError
from mycodingagent.tool_runtime import ToolRegistry


class AgentOutputError(ValueError):
    pass


class AgentRunner:
    def __init__(
        self,
        *,
        api_client: AsyncOpenAI,
        registry: ToolRegistry,
        workspace_root: Any,
        event_sink: RuntimeEventSink | None = None,
    ) -> None:
        self.api_client = api_client
        self.registry = registry
        self.workspace_root = workspace_root
        self.event_sink = event_sink

    async def run(self, request: AgentRequest) -> AgentResult:
        await self._emit("agent", "Agent started", role=request.role.value)
        policy = ToolAccessPolicy(
            allowed_tools=request.allowed_tools,
            workspace_root=self.workspace_root,
            allowed_paths=request.allowed_paths,
            allow_validation_bash=request.allow_validation_bash,
        )
        tools = agent_client.format_openai_tools(policy.schemas(self.registry))
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt},
        ]
        tool_call_count = 0
        for round_index in range(1, request.max_tool_rounds + 1):
            await self._emit(
                "agent",
                "Model round started",
                role=request.role.value,
                round=round_index,
            )
            text, tool_calls, _usage = await agent_client.stream_one_round(
                self.api_client,
                request.model,
                messages,
                tools,
                display=False,
                output_label=request.role.value,
            )
            assistant_message: dict[str, Any] = {"role": "assistant", "content": text}
            if tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": call.tool_id or f"{request.role.value}_tool_{index}",
                        "type": "function",
                        "function": {"name": call.tool_name, "arguments": call.arguments},
                    }
                    for index, call in enumerate(tool_calls)
                ]
            messages.append(assistant_message)
            if not tool_calls:
                await self._emit(
                    "agent",
                    "Agent completed",
                    role=request.role.value,
                    rounds=round_index,
                    tool_calls=tool_call_count,
                )
                return AgentResult(text=text, messages=tuple(messages), tool_calls=tool_call_count)
            for index, call in enumerate(tool_calls):
                tool_call_count += 1
                tool_call_id = call.tool_id or f"{request.role.value}_tool_{index}"
                arguments = _parse_arguments(call.arguments)
                await self._emit(
                    "tool",
                    "Tool call started",
                    role=request.role.value,
                    tool=call.tool_name,
                    round=round_index,
                )
                try:
                    policy.authorize(call.tool_name, arguments)
                    output = await agent_client.execute_local_tool(
                        self.registry,
                        call.tool_name,
                        call.arguments,
                        skill_runtime=None,
                    )
                except ToolPermissionError as exc:
                    output = f"Permission denied: {exc}"
                messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": output})
                await self._emit(
                    "tool",
                    "Tool call completed",
                    role=request.role.value,
                    tool=call.tool_name,
                    round=round_index,
                )
        await self._emit(
            "agent",
            "Agent stopped at tool-round limit",
            role=request.role.value,
            rounds=request.max_tool_rounds,
            tool_calls=tool_call_count,
        )
        return AgentResult(
            text="",
            messages=tuple(messages),
            tool_calls=tool_call_count,
            error=f"exceeded max tool rounds ({request.max_tool_rounds})",
        )

    async def _emit(self, phase: str, message: str, **metadata: Any) -> None:
        if self.event_sink is not None:
            await self.event_sink.emit(RuntimeEvent(phase=phase, message=message, metadata=metadata))


def parse_json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise AgentOutputError("agent did not return a JSON object")
        try:
            parsed = json.loads(value[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AgentOutputError(f"invalid agent JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise AgentOutputError("agent JSON root must be an object")
    return parsed


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
