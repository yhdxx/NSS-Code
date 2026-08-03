from __future__ import annotations

from collections.abc import Sequence

from mycodingagent.memory.models import WorkspaceCheckpoint
from mycodingagent.terminal_ui.application import request_selection


async def select_checkpoint_interactively(
    checkpoints: Sequence[WorkspaceCheckpoint],
    *,
    limit: int = 20,
) -> str:
    options = list(reversed(checkpoints[-limit:]))
    labels = [format_checkpoint_option(checkpoint) for checkpoint in options]
    selected = await request_selection("请选择要回退到的轮次：", labels)
    return options[selected].checkpoint_id if selected is not None else ""


async def select_rewind_scope_interactively() -> str:
    scopes = (
        ("both", "代码和会话"),
        ("conversation", "仅会话（保留 workspace snapshot）"),
        ("code", "仅代码"),
    )
    selected = await request_selection("请选择回退范围：", [label for _, label in scopes])
    return scopes[selected][0] if selected is not None else ""


def format_checkpoint_option(checkpoint: WorkspaceCheckpoint) -> str:
    prompt = " ".join(checkpoint.prompt.split())
    return f"turn {checkpoint.turn_index} | {checkpoint.checkpoint_id[:8]} | {prompt[:80]}"
