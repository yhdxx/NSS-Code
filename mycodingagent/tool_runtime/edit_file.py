from __future__ import annotations  # 启用未来版本语法特性。

from pathlib import Path  # 导入当前模块需要的依赖。
from typing import TYPE_CHECKING, Any  # 导入当前模块需要的依赖。

from pydantic import BaseModel, Field  # 导入当前模块需要的依赖。

from mycodingagent.tool_runtime.base import Tool, ToolResult, resolve_write_path  # 导入当前模块需要的依赖。
from mycodingagent.tool_runtime.text_files import (
    read_text_preserving_newlines,
    write_text_preserving_newlines,
)
from mycodingagent.tool_runtime.write_policy import (
    USER_DENIED_WRITE_MESSAGE,
    WriteApprovalHook,
    WriteApprovalRequest,
    write_preview,
)

if TYPE_CHECKING:  # 根据条件决定是否执行后续分支。
    from mycodingagent.workspace.file_cache import FileCache  # 导入当前模块需要的依赖。
    from mycodingagent.tool_runtime.file_state_cache import FileStateCache  # 导入当前模块需要的依赖。


class Params(BaseModel):  # 定义用于封装相关状态和行为的类。
    file_path: str = Field(description="要编辑的文件路径")  # 保存配置值或中间计算结果。
    old_string: str = Field(description="要查找并替换的准确字符串，在文件中必须唯一")  # 保存配置值或中间计算结果。
    new_string: str = Field(description="替换后的字符串")  # 保存配置值或中间计算结果。
    intent: str = Field(default="", description="本次编辑的简短目的")


class EditFile(Tool):  # 定义用于封装相关状态和行为的类。
    name = "EditFile"  # 保存配置值或中间计算结果。
    description = (  # 保存配置值或中间计算结果。
        "精确替换沙箱内文件中的字符串。old_string 在文件中必须只出现一次。\n"  # 提供上方表达式需要的文本内容。
        "编辑前必须先使用 ReadFile 读取文件，否则本工具会失败。"  # 提供上方表达式需要的文本内容。
    )  # 结束上方的多行结构。
    params_model = Params  # 保存配置值或中间计算结果。
    category = "write"  # 保存配置值或中间计算结果。


    def __init__(  # 定义函数，封装可复用逻辑。
        self,  # 执行当前步骤的业务逻辑。
        file_cache: FileCache | None = None,  # 保存配置值或中间计算结果。
        file_history: Any = None,  # 保存配置值或中间计算结果。
        file_state_cache: FileStateCache | None = None,  # 保存配置值或中间计算结果。
        workspace_tracker: Any = None,
        sandbox_root: Path | None = None,  # 保存配置值或中间计算结果。
        approval_hook: WriteApprovalHook | None = None,
        checkpoint_hook: Any = None,
    ) -> None:  # 开启一个新的代码块。
        self._cache = file_cache  # 保存配置值或中间计算结果。
        self.file_history = file_history  # 保存配置值或中间计算结果。
        self._state_cache = file_state_cache  # 保存配置值或中间计算结果。
        self._workspace_tracker = workspace_tracker
        self._sandbox_root = sandbox_root  # 保存配置值或中间计算结果。
        self._approval_hook = approval_hook
        self._checkpoint_hook = checkpoint_hook


    async def execute(self, params: Params) -> ToolResult:  # 定义异步函数，供事件循环调用。
        path, error = resolve_write_path(params.file_path, self._sandbox_root)  # 保存配置值或中间计算结果。
        if error:  # 根据条件决定是否执行后续分支。
            return ToolResult(output=error, is_error=True)  # 返回当前函数的处理结果。
        if not path.exists():  # 根据条件决定是否执行后续分支。
            return ToolResult(output=f"错误：文件不存在：{params.file_path}", is_error=True)  # 返回当前函数的处理结果。
        if not path.is_file():
            return ToolResult(output=f"错误：路径不是文件：{params.file_path}", is_error=True)

        if self._state_cache:  # 根据条件决定是否执行后续分支。
            ok, err_msg = self._state_cache.check(str(path))  # 保存配置值或中间计算结果。
            if not ok:  # 根据条件决定是否执行后续分支。
                return ToolResult(output=err_msg, is_error=True)  # 返回当前函数的处理结果。

        try:  # 开始可能抛出异常的保护代码块。
            content = read_text_preserving_newlines(path)  # 保存配置值或中间计算结果。
        except Exception as e:  # 捕获并处理指定异常。
            return ToolResult(output=f"读取文件失败：{e}", is_error=True)  # 返回当前函数的处理结果。

        count = content.count(params.old_string)  # 保存配置值或中间计算结果。
        if count == 0:  # 根据条件决定是否执行后续分支。
            return ToolResult(output="错误：文件中未找到 old_string", is_error=True)  # 返回当前函数的处理结果。
        if count > 1:  # 根据条件决定是否执行后续分支。
            return ToolResult(  # 返回当前函数的处理结果。
                output=f"错误：old_string 在文件中出现 {count} 次，必须保持唯一",  # 保存配置值或中间计算结果。
                is_error=True,  # 保存配置值或中间计算结果。
            )  # 结束上方的多行结构。

        new_content = content.replace(params.old_string, params.new_string, 1)  # 保存配置值或中间计算结果。
        if self._approval_hook is not None:
            decision = await self._approval_hook.approve(
                WriteApprovalRequest(
                    tool_name=self.name,
                    path=str(path),
                    intent=params.intent,
                    is_new_file=False,
                    preview=write_preview(str(path), content, new_content),
                )
            )
            if not decision.allowed:
                return ToolResult(output=f"{USER_DENIED_WRITE_MESSAGE}：{decision.reason}", is_error=True)
        if self._checkpoint_hook is not None:
            self._checkpoint_hook.capture_before(path)
        if self.file_history is not None:
            self.file_history.track_edit(str(path))
        try:  # 开始可能抛出异常的保护代码块。
            write_text_preserving_newlines(path, new_content)  # 保存配置值或中间计算结果。
            if self._cache:  # 根据条件决定是否执行后续分支。
                self._cache.invalidate(str(path))  # 执行当前步骤的业务逻辑。
            if self._state_cache:  # 根据条件决定是否执行后续分支。
                self._state_cache.update(str(path))  # 执行当前步骤的业务逻辑。
            if self._workspace_tracker is not None:
                self._workspace_tracker.mark_agent_write(str(path))
            if self._checkpoint_hook is not None:
                self._checkpoint_hook.capture_after(path)
        except Exception as e:  # 捕获并处理指定异常。
            return ToolResult(output=f"写入文件失败：{e}", is_error=True)  # 返回当前函数的处理结果。

        return ToolResult(output=f"已成功编辑 {path}")  # 返回当前函数的处理结果。
