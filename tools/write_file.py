from __future__ import annotations  # 启用未来版本语法特性。

from pathlib import Path  # 导入当前模块需要的依赖。
from typing import TYPE_CHECKING, Any  # 导入当前模块需要的依赖。

from pydantic import BaseModel, Field  # 导入当前模块需要的依赖。

from tools.base import Tool, ToolResult, resolve_sandbox_path  # 导入当前模块需要的依赖。

if TYPE_CHECKING:  # 根据条件决定是否执行后续分支。
    from cache import FileCache  # 导入当前模块需要的依赖。
    from tools.file_state_cache import FileStateCache  # 导入当前模块需要的依赖。


class Params(BaseModel):  # 定义用于封装相关状态和行为的类。
    file_path: str = Field(description="Path to the file to write")  # 保存配置值或中间计算结果。
    content: str = Field(description="Content to write to the file")  # 保存配置值或中间计算结果。


class WriteFile(Tool):  # 定义用于封装相关状态和行为的类。
    name = "WriteFile"  # 保存配置值或中间计算结果。
    description = (  # 保存配置值或中间计算结果。
        "Write content to a file inside the sandbox, creating parent directories if needed. "  # 提供上方表达式需要的文本内容。
        "Overwrites existing files.\n"  # 提供上方表达式需要的文本内容。
        "You MUST read existing files with ReadFile before overwriting them. This tool will fail otherwise."  # 提供上方表达式需要的文本内容。
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
    ) -> None:  # 开启一个新的代码块。
        self._cache = file_cache  # 保存配置值或中间计算结果。
        self.file_history = file_history  # 保存配置值或中间计算结果。
        self._state_cache = file_state_cache  # 保存配置值或中间计算结果。
        self._workspace_tracker = workspace_tracker
        self._sandbox_root = sandbox_root  # 保存配置值或中间计算结果。


    async def execute(self, params: Params) -> ToolResult:  # 定义异步函数，供事件循环调用。
        path, error = resolve_sandbox_path(params.file_path, self._sandbox_root)  # 保存配置值或中间计算结果。
        if error:  # 根据条件决定是否执行后续分支。
            return ToolResult(output=error, is_error=True)  # 返回当前函数的处理结果。

        if self._state_cache and path.exists():  # 根据条件决定是否执行后续分支。
            ok, err_msg = self._state_cache.check(str(path))  # 保存配置值或中间计算结果。
            if not ok:  # 根据条件决定是否执行后续分支。
                return ToolResult(output=err_msg, is_error=True)  # 返回当前函数的处理结果。

        if self.file_history is not None:  # 根据条件决定是否执行后续分支。
            self.file_history.track_edit(str(path))  # 执行当前步骤的业务逻辑。

        try:  # 开始可能抛出异常的保护代码块。
            path.parent.mkdir(parents=True, exist_ok=True)  # 保存配置值或中间计算结果。
            path.write_text(params.content, encoding="utf-8")  # 保存配置值或中间计算结果。
            if self._cache:  # 根据条件决定是否执行后续分支。
                self._cache.invalidate(str(path))  # 执行当前步骤的业务逻辑。
            if self._state_cache:  # 根据条件决定是否执行后续分支。
                self._state_cache.update(str(path))  # 执行当前步骤的业务逻辑。
            if self._workspace_tracker is not None:
                self._workspace_tracker.mark_agent_write(str(path))
        except Exception as e:  # 捕获并处理指定异常。
            return ToolResult(output=f"Error writing file: {e}", is_error=True)  # 返回当前函数的处理结果。
        return ToolResult(output=f"Successfully wrote to {path}")  # 返回当前函数的处理结果。
