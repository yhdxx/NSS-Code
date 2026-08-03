from __future__ import annotations

from mycodingagent.memory import MemoryRuntime, SessionListItem
from mycodingagent.terminal_ui.application import request_selection


async def select_session_interactively(
    memory_runtime: MemoryRuntime,
    *,
    limit: int = 20,
    include_all: bool = False,
    action: str = "恢复",
) -> str:
    sessions = memory_runtime.list_sessions(limit=limit, include_all=include_all)
    if not sessions:
        if include_all:
            print(f"暂无可{action}会话。", flush=True)
        else:
            command = command_for_session_action(action)
            print(f"当前工作目录下没有历史会话。可使用 {command} --all 查看其他工作目录会话。", flush=True)
            migrated_sessions = memory_runtime.list_migrated_workspace_sessions(limit=limit)
            if migrated_sessions:
                print(f"检测到可能来自迁移前同一项目的会话，可使用 {command} --all 查看。", flush=True)
        return ""
    selected = await request_selection(
        f"请选择要{action}的会话：",
        [
            format_session_option(session, selected=False, include_workspace=include_all).strip()
            for session in sessions
        ],
    )
    return sessions[selected].session_id if selected is not None else ""


def print_session_options(sessions: list[SessionListItem], *, include_workspace: bool = False) -> None:
    for session in sessions:
        print(format_session_option(session, selected=False, include_workspace=include_workspace), flush=True)


def command_for_session_action(action: str) -> str:
    return {
        "恢复": "/resume",
        "分叉": "/fork",
        "清空": "/clear",
        "删除": "/delete",
    }.get(action, "/resume")


def format_session_option(session: SessionListItem, *, selected: bool, include_workspace: bool = False) -> str:
    marker = ">" if selected else " "
    short_id = session.session_id[:8]
    workspace = f" [{session.workspace_label or session.workspace_root}]" if include_workspace else ""
    return f"{marker} [{short_id}]{workspace} {session.preview}（{session.message_count} 条消息）"
