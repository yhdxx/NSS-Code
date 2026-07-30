from __future__ import annotations  # 启用未来版本语法特性。

import asyncio
from pathlib import Path  # 导入当前模块需要的依赖。
from typing import TYPE_CHECKING  # 导入当前模块需要的依赖。

from pydantic import BaseModel, Field  # 导入当前模块需要的依赖。

from mycodingagent.tool_runtime.base import Tool, ToolResult, resolve_sandbox_path  # 导入当前模块需要的依赖。

if TYPE_CHECKING:  # 根据条件决定是否执行后续分支。
    from mycodingagent.workspace.file_cache import FileCache  # 导入当前模块需要的依赖。
    from mycodingagent.tool_runtime.file_state_cache import FileStateCache  # 导入当前模块需要的依赖。


class Params(BaseModel):  # 定义用于封装相关状态和行为的类。
    file_path: str = Field(description="Absolute or relative path to the file to read")  # 保存配置值或中间计算结果。
    offset: int = Field(default=0, description="Line offset to start reading from (0-based)")  # 保存配置值或中间计算结果。
    limit: int = Field(default=2000, description="Maximum number of lines to read")  # 保存配置值或中间计算结果。


class ReadFile(Tool):  # 定义用于封装相关状态和行为的类。
    name = "ReadFile"  # 保存配置值或中间计算结果。
    description = "Read a file inside the sandbox and return its contents with line numbers."  # 保存配置值或中间计算结果。
    params_model = Params   #传入该工具的参数
    category = "read"       #表明该工具属于读操作
    is_concurrency_safe = True  #并发安全


    def __init__(  # 定义函数，封装可复用逻辑。
        self,  # 执行当前步骤的业务逻辑。
        file_cache: FileCache | None = None,  # 保存配置值或中间计算结果。
        file_state_cache: FileStateCache | None = None,  # 保存配置值或中间计算结果。
        sandbox_root: Path | None = None,  # 保存配置值或中间计算结果。
    ) -> None:  # 开启一个新的代码块。
        self._cache = file_cache  # 保存配置值或中间计算结果。
        self._state_cache = file_state_cache  # 保存配置值或中间计算结果。
        self._sandbox_root = sandbox_root  # 保存配置值或中间计算结果。


    async def execute(self, params: Params) -> ToolResult:  # 定义异步函数，供事件循环调用。
        return await asyncio.to_thread(self._read, params)

    def _read(self, params: Params) -> ToolResult:
        path, error = resolve_sandbox_path(params.file_path, self._sandbox_root)  # 保存配置值或中间计算结果。
        if error:  # 根据条件决定是否执行后续分支。
            return ToolResult(output=error, is_error=True)  # 返回当前函数的处理结果。
        if not path.exists():  # 根据条件决定是否执行后续分支。
            return ToolResult(output=f"Error: file not found: {params.file_path}", is_error=True)  # 返回当前函数的处理结果。
        if not path.is_file():  # 根据条件决定是否执行后续分支。
            return ToolResult(output=f"Error: not a file: {params.file_path}", is_error=True)  # 返回当前函数的处理结果。

        try:  # 开始可能抛出异常的保护代码块。
            text = self._cache.get(str(path)) if self._cache else None  # 保存配置值或中间计算结果。
            if text is None:  # 根据条件决定是否执行后续分支。
                text = path.read_text(encoding="utf-8")  # 保存配置值或中间计算结果。
                if self._cache:  # 根据条件决定是否执行后续分支。
                    self._cache.put(str(path), text)  # 执行当前步骤的业务逻辑。
        except Exception as e:  # 捕获并处理指定异常。
            return ToolResult(output=f"Error reading file: {e}", is_error=True)  # 返回当前函数的处理结果。

        if self._state_cache:  # 根据条件决定是否执行后续分支。
            try:  # 开始可能抛出异常的保护代码块。
                mtime_ns = path.stat().st_mtime_ns  # 保存配置值或中间计算结果。
                self._state_cache.record(str(path), text, mtime_ns)  # 执行当前步骤的业务逻辑。
            except OSError:  # 捕获并处理指定异常。
                pass  # 保留空实现位置。

        #按行切分
        lines = text.splitlines()  # 保存配置值或中间计算结果。

        #从偏移量开始读取指定大小的数据
        selected = lines[params.offset : params.offset + params.limit]  # 保存配置值或中间计算结果。

        #加上行号
        numbered = [f"{i + params.offset + 1}\t{line}" for i, line in enumerate(selected)]  # 保存配置值或中间计算结果。
        return ToolResult(output="\n".join(numbered))  # 返回当前函数的处理结果。
