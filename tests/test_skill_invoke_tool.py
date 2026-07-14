from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mycodingagent.tool_runtime.skill_tools import InvokeSkillTool


class FakeSkillRuntime:
    def __init__(self) -> None:
        self.invocations: list[str] = []

    def get_record(self, tool_name: str):
        if tool_name != "skill_review":
            return None
        return SimpleNamespace(
            name="Review",
            tool_name="skill_review",
            description="Review code changes",
            content="Inspect diffs and identify correctness risks.",
        )

    def record_skill_invocation(self, tool_name: str) -> None:
        self.invocations.append(tool_name)

    def list_references_for_skill(self, tool_name: str) -> list[dict[str, str]]:
        return [{"reference_path": "references/review.md"}]


def test_invoke_skill_executes_named_skill_workflow():
    async def scenario():
        runtime = FakeSkillRuntime()
        tool = InvokeSkillTool(runtime)
        params = tool.params_model.model_validate(
            {
                "skill_name": "skill_review",
                "instruction": "Review this patch",
                "context": "diff summary",
                "intent": "验证固定 skill 调用工具",
            }
        )

        result = await tool.execute(params)

        assert result.is_error is False
        assert runtime.invocations == ["skill_review"]
        assert "SKILL: Review" in result.output
        assert "INSTRUCTIONS:" in result.output
        assert "Review this patch" in result.output
        assert "references/review.md" in result.output

    asyncio.run(scenario())

