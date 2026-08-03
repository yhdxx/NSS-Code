from __future__ import annotations

import asyncio

from mycodingagent.tool_runtime import create_default_registry
from mycodingagent.tool_runtime.command_policy import BashPolicyEvaluator, BashPolicyStore
from mycodingagent.tool_runtime.write_file import WriteFile
from mycodingagent.tool_runtime.write_policy import (
    CLIWriteApprovalHook,
    USER_DENIED_WRITE_MESSAGE,
    WriteApprovalDecision,
    WriteApprovalHook,
)


class _DenyHook(WriteApprovalHook):
    async def approve(self, request):  # noqa: ANN001
        return WriteApprovalDecision(allowed=False, reason="user_denied")


class _Coordinator:
    def __init__(self, answers: list[str]) -> None:
        self.answers = answers
        self.prompts = 0

    async def read_choice(self, prompt: str, *, allowed: set[str]) -> str:
        self.prompts += 1
        answer = self.answers.pop(0)
        return answer if answer in allowed else ""


def _write(tool: WriteFile, path: str, content: str):
    return asyncio.run(
        tool.execute(tool.params_model(file_path=path, content=content, intent="test write"))
    )


def test_rejected_write_does_not_touch_disk(tmp_path):
    tool = WriteFile(sandbox_root=tmp_path, approval_hook=_DenyHook())

    result = _write(tool, "denied.txt", "secret")

    assert result.is_error is True
    assert USER_DENIED_WRITE_MESSAGE in result.output
    assert not (tmp_path / "denied.txt").exists()


def test_always_approval_is_remembered_per_resolved_file(tmp_path):
    coordinator = _Coordinator(["a", "y"])
    hook = CLIWriteApprovalHook(coordinator)
    tool = WriteFile(sandbox_root=tmp_path, approval_hook=hook)

    assert not _write(tool, "same.txt", "one").is_error
    assert not _write(tool, "same.txt", "two").is_error
    assert not _write(tool, "other.txt", "three").is_error

    assert coordinator.prompts == 2
    assert (tmp_path / "same.txt").read_text() == "two"


def test_no_hook_preserves_non_interactive_write_behavior(tmp_path):
    result = _write(WriteFile(sandbox_root=tmp_path), "plain.txt", "ok")

    assert result.is_error is False
    assert (tmp_path / "plain.txt").read_text() == "ok"


def test_default_registry_does_not_prompt_for_core_write_tools(tmp_path):
    registry = create_default_registry(
        bash_policy_evaluator=BashPolicyEvaluator(BashPolicyStore(tmp_path / "policy.sqlite3")),
    )

    write_tool = registry.get("WriteFile")
    edit_tool = registry.get("EditFile")

    assert getattr(write_tool, "_approval_hook") is None
    assert getattr(edit_tool, "_approval_hook") is None
