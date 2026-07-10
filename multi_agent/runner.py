from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

import client as agent_client
from multi_agent.models import AgentRequest, AgentResult
from multi_agent.permissions import ToolAccessPolicy, ToolPermissionError
from tools import ToolRegistry


class AgentOutputError(ValueError):
    pass


class AgentRunner:
    def __init__(
        self,
        *,
        api_client: AsyncOpenAI,
        registry: ToolRegistry,
        workspace_root: Any,
    ) -> None:
        self.api_client = api_client
        self.registry = registry
        self.workspace_root = workspace_root

    async def run(self, request: AgentRequest) -> AgentResult:
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
        for _ in range(request.max_tool_rounds):
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
                return AgentResult(text=text, messages=tuple(messages), tool_calls=tool_call_count)
            for index, call in enumerate(tool_calls):
                tool_call_count += 1
                tool_call_id = call.tool_id or f"{request.role.value}_tool_{index}"
                arguments = _parse_arguments(call.arguments)
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
        return AgentResult(
            text="",
            messages=tuple(messages),
            tool_calls=tool_call_count,
            error=f"exceeded max tool rounds ({request.max_tool_rounds})",
        )


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
