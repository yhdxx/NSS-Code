from __future__ import annotations

from mycodingagent.memory import SessionListItem
from mycodingagent.terminal_ui.application import request_confirmation
from mycodingagent.terminal_ui.session_selector import print_session_options


async def confirm_force_rewind(conflicts: tuple[str, ...]) -> bool:
    print("检测到外部修改：" + "、".join(conflicts), flush=True)
    return await request_confirmation("确认覆盖这些修改？输入 y 确认，其它任意键取消：")


async def confirm_cross_workspace_restore(source_workspace: str, current_workspace: str) -> bool:
    return await confirm_cross_workspace_action("恢复", source_workspace, current_workspace)


async def confirm_delete_sessions(sessions: list[SessionListItem], *, include_all: bool) -> bool:
    scope = "全部工作目录" if include_all else "当前工作目录"
    print(f"将删除{scope}下 {len(sessions)} 个会话：", flush=True)
    print_session_options(sessions[:10], include_workspace=include_all)
    if len(sessions) > 10:
        print(f"  ... 另有 {len(sessions) - 10} 个会话未列出", flush=True)
    return await request_confirmation(
        f"确认删除{scope}下全部会话？输入 y 确认，其它任意键取消："
    )


async def confirm_cross_workspace_action(action: str, source_workspace: str, current_workspace: str) -> bool:
    print("该会话来自其他工作目录：", flush=True)
    print(f"  来源：{source_workspace}", flush=True)
    print(f"  当前：{current_workspace}", flush=True)
    if action == "恢复":
        print("恢复后会加载历史对话，并按当前工作目录重新检查文件状态。", flush=True)
    elif action == "分叉":
        print("分叉后会复制历史对话到新会话，并按当前工作目录重新检查文件状态。", flush=True)
    else:
        print("删除后该会话及其关联消息、工具输出、压缩快照会从本地移除。", flush=True)
    return await request_confirmation(f"确认{action}？输入 y 确认，其它任意键取消：")
