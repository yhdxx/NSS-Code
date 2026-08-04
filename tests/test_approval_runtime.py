from __future__ import annotations

import asyncio

import pytest

from mycodingagent.approval import ApprovalMode, ApprovalRuntime
from mycodingagent.configuration.settings import ApprovalConfig
from mycodingagent.mcp_integration.hooks import (
    CLIApprovalHook,
    CLILaunchApprovalHook,
    MCPServerLaunchRequest,
)
from mycodingagent.mcp_integration.policy import MCPApprovalRequest
from mycodingagent.tool_runtime.command_policy import (
    CLICommandApprovalHook,
    CommandApprovalRequest,
)


class _FailIfPrompted:
    async def read_choice(self, _prompt: str, *, allowed: set[str]) -> str:
        raise AssertionError(f"auto mode must not prompt; allowed={allowed}")


class _ApproveCoordinator:
    def __init__(self) -> None:
        self.calls = 0

    async def read_choice(self, _prompt: str, *, allowed: set[str]) -> str:
        self.calls += 1
        return "y" if "y" in allowed else ""


def test_approval_runtime_accepts_only_explicit_modes() -> None:
    runtime = ApprovalRuntime("DEFAULT")

    assert runtime.mode is ApprovalMode.DEFAULT
    assert runtime.auto_approve is False
    assert runtime.set_mode("auto") is ApprovalMode.AUTO
    assert runtime.auto_approve is True
    with pytest.raises(ValueError):
        runtime.set_mode("unsafe")


def test_approval_config_reports_invalid_mode() -> None:
    assert ApprovalConfig(mode="default").validation_errors() == []
    assert ApprovalConfig(mode="auto").validation_errors() == []
    assert ApprovalConfig(mode="unsafe").validation_errors() == [
        "approval.mode 只能是 default 或 auto"
    ]


def test_auto_mode_bypasses_bash_and_mcp_prompts() -> None:
    runtime = ApprovalRuntime(ApprovalMode.AUTO)
    coordinator = _FailIfPrompted()
    bash_hook = CLICommandApprovalHook(coordinator, approval_runtime=runtime)
    mcp_hook = CLIApprovalHook(coordinator, approval_runtime=runtime)
    launch_hook = CLILaunchApprovalHook(coordinator, approval_runtime=runtime)

    bash_decision = asyncio.run(
        bash_hook.approve(
            CommandApprovalRequest("rm -rf /workspace/build", "high", "recursive delete")
        )
    )
    mcp_decision = asyncio.run(
        mcp_hook.approve(
            MCPApprovalRequest("github", "delete_repo", "destructive", "delete", {})
        )
    )
    launch_decision = asyncio.run(
        launch_hook.approve(
            MCPServerLaunchRequest("github", "stdio", "npx", False, "write", True)
        )
    )

    assert bash_decision.allowed and "auto" in bash_decision.reason
    assert mcp_decision.allowed and "auto" in mcp_decision.reason
    assert launch_decision.allowed and "auto" in launch_decision.reason
    assert mcp_hook._always_allowed == set()
    assert launch_hook._approved == set()


def test_switching_back_to_default_restores_interactive_approval() -> None:
    runtime = ApprovalRuntime(ApprovalMode.AUTO)
    coordinator = _ApproveCoordinator()
    bash_hook = CLICommandApprovalHook(coordinator, approval_runtime=runtime)
    request = CommandApprovalRequest("rm -rf /workspace/build", "high", "recursive delete")

    assert asyncio.run(bash_hook.approve(request)).allowed
    assert coordinator.calls == 0

    runtime.set_mode(ApprovalMode.DEFAULT)

    assert asyncio.run(bash_hook.approve(request)).allowed
    assert coordinator.calls == 1
