from __future__ import annotations  # 启用未来版本语法特性。

import asyncio
from pathlib import Path  # 导入当前模块需要的依赖。
from typing import TYPE_CHECKING  # 导入当前模块需要的依赖。

from pydantic import BaseModel, Field  # 导入当前模块需要的依赖。

from mycodingagent.tool_runtime.base import MAX_OUTPUT_CHARS, Tool, ToolResult, resolve_sandbox_path  # 导入当前模块需要的依赖。
from mycodingagent.tool_runtime.text_files import read_text_preserving_newlines

if TYPE_CHECKING:  # 根据条件决定是否执行后续分支。
    from mycodingagent.workspace.file_cache import FileCache  # 导入当前模块需要的依赖。
    from mycodingagent.tool_runtime.file_state_cache import FileStateCache  # 导入当前模块需要的依赖。


class Params(BaseModel):  # 定义用于封装相关状态和行为的类。
    file_path: str = Field(description="要读取文件的绝对或相对路径")  # 保存配置值或中间计算结果。
    offset: int = Field(default=0, ge=0, description="开始读取的行偏移量，从 0 开始")  # 保存配置值或中间计算结果。
    limit: int = Field(default=2000, ge=1, description="最多读取的行数，必须大于 0")  # 保存配置值或中间计算结果。


class ReadFile(Tool):  # 定义用于封装相关状态和行为的类。
    name = "ReadFile"  # 保存配置值或中间计算结果。
    description = "读取沙箱内的文件，并返回带行号的内容。"  # 保存配置值或中间计算结果。
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
            return ToolResult(output=f"错误：文件不存在：{params.file_path}", is_error=True)  # 返回当前函数的处理结果。
        if not path.is_file():  # 根据条件决定是否执行后续分支。
            return ToolResult(output=f"错误：路径不是文件：{params.file_path}", is_error=True)  # 返回当前函数的处理结果。

        try:  # 开始可能抛出异常的保护代码块。
            text = self._cache.get(str(path)) if self._cache else None
            if text is None:
                text = read_text_preserving_newlines(path)
                if self._cache:  # 根据条件决定是否执行后续分支。
                    self._cache.put(str(path), text)  # 执行当前步骤的业务逻辑。
        except Exception as e:  # 捕获并处理指定异常。
            return ToolResult(output=f"读取文件失败：{e}", is_error=True)  # 返回当前函数的处理结果。

        if self._state_cache:  # 根据条件决定是否执行后续分支。
            try:  # 开始可能抛出异常的保护代码块。
                mtime_ns = path.stat().st_mtime_ns  # 保存配置值或中间计算结果。
                self._state_cache.record(str(path), text, mtime_ns)  # 执行当前步骤的业务逻辑。
            except OSError:  # 捕获并处理指定异常。
                pass  # 保留空实现位置。

        lines = text.splitlines()  # 保存配置值或中间计算结果。
        if not lines:
            return ToolResult(output="（文件为空）")
        if params.offset >= len(lines):
            return ToolResult(
                output=f"错误：offset={params.offset} 超出文件范围；文件共 {len(lines)} 行。",
                is_error=True,
            )

        selected = lines[params.offset : params.offset + params.limit]
        numbered: list[str] = []
        output_chars = 0
        line_was_truncated = False
        for index, line in enumerate(selected, start=params.offset + 1):
            rendered = f"{index}\t{line}"
            separator_chars = 1 if numbered else 0
            remaining = MAX_OUTPUT_CHARS - output_chars - separator_chars
            if len(rendered) > remaining:
                if remaining > 0:
                    numbered.append(rendered[:remaining])
                line_was_truncated = True
                break
            numbered.append(rendered)
            output_chars += separator_chars + len(rendered)

        output = "\n".join(numbered)
        if line_was_truncated:
            output += "\n... <当前行超过输出字符上限，已截断；请使用 Grep 定位或 Bash 分段读取>"
        else:
            next_offset = params.offset + len(numbered)
            if next_offset < len(lines):
                output += (
                    f"\n... <还有 {len(lines) - next_offset} 行；"
                    f"继续读取请使用 offset={next_offset}>"
                )
        return ToolResult(output=output)  # 返回当前函数的处理结果。
