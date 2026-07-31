from __future__ import annotations  # 启用未来版本语法特性。

import asyncio
import fnmatch
import os
import re  # 导入当前模块需要的依赖。
from threading import Event
from pathlib import Path  # 导入当前模块需要的依赖。

from pydantic import BaseModel, Field  # 导入当前模块需要的依赖。

from mycodingagent.tool_runtime.base import SKIP_DIRS, Tool, ToolResult, is_path_in_sandbox, resolve_sandbox_path  # 导入当前模块需要的依赖。

MAX_GREP_MATCHES = 200


class Params(BaseModel):  # 定义用于封装相关状态和行为的类。
    pattern: str = Field(description="要搜索的正则表达式")  # 保存配置值或中间计算结果。
    path: str = Field(default=".", description="搜索起始目录")  # 保存配置值或中间计算结果。
    include: str = Field(default="", description="文件名 Glob 过滤条件，例如 '*.py'")  # 保存配置值或中间计算结果。


class Grep(Tool):  # 定义用于封装相关状态和行为的类。
    name = "Grep"  # 保存配置值或中间计算结果。
    description = (
        "使用正则表达式搜索沙箱内的文件内容，返回 file:line:content 格式的匹配结果。"
        "尽量使用 '*.py' 等 include 过滤条件，避免宽泛扫描整个工作区。"
    )  # 保存配置值或中间计算结果。
    params_model = Params  # 保存配置值或中间计算结果。
    category = "read"  # 保存配置值或中间计算结果。
    is_concurrency_safe = True  # 保存配置值或中间计算结果。

    def __init__(self, sandbox_root: Path | None = None) -> None:  # 定义函数，封装可复用逻辑。
        self._sandbox_root = sandbox_root  # 保存配置值或中间计算结果。


    async def execute(self, params: Params) -> ToolResult:  # 定义异步函数，供事件循环调用。
        stop = Event()
        try:
            return await asyncio.to_thread(self._search, params, stop)
        finally:
            stop.set()

    def _search(self, params: Params, stop: Event) -> ToolResult:
        base, error = resolve_sandbox_path(params.path, self._sandbox_root)  # 保存配置值或中间计算结果。
        if error:  # 根据条件决定是否执行后续分支。
            return ToolResult(output=error, is_error=True)  # 返回当前函数的处理结果。
        if not base.exists():  # 根据条件决定是否执行后续分支。
            return ToolResult(output=f"错误：路径不存在：{params.path}", is_error=True)  # 返回当前函数的处理结果。

        try:  # 开始可能抛出异常的保护代码块。
            regex = re.compile(params.pattern)  # 保存配置值或中间计算结果。
        except re.error as e:  # 捕获并处理指定异常。
            return ToolResult(output=f"错误：正则表达式无效：{e}", is_error=True)  # 返回当前函数的处理结果。

        include_pattern = params.include or "*"  # 保存配置值或中间计算结果。

        results: list[str] = []  # 保存配置值或中间计算结果。
        for file_path, rel in _iter_search_files(base, include_pattern, self._sandbox_root or base):  # 遍历集合中的元素。
            if stop.is_set():
                return ToolResult(output="搜索已中断。", is_error=True)
            try:  # 开始可能抛出异常的保护代码块。
                text = file_path.read_text(encoding="utf-8", errors="ignore")  # 保存配置值或中间计算结果。
            except (OSError, UnicodeDecodeError):  # 捕获并处理指定异常。
                continue  # 跳过本轮循环剩余逻辑。
            for line_num, line in enumerate(text.splitlines(), 1):  # 遍历集合中的元素。
                if stop.is_set():
                    return ToolResult(output="搜索已中断。", is_error=True)
                if regex.search(line):  # 根据条件决定是否执行后续分支。
                    results.append(f"{rel}:{line_num}:{line}")  # 执行当前步骤的业务逻辑。
                    if len(results) >= MAX_GREP_MATCHES:
                        output = "\n".join(results)
                        output += f"\n... <匹配数达到 {MAX_GREP_MATCHES} 后已截断；请使用更精确的模式或 include 过滤条件>"
                        return ToolResult(output=output)

        if not results:  # 根据条件决定是否执行后续分支。
            return ToolResult(output="未找到匹配内容。")  # 返回当前函数的处理结果。
        return ToolResult(output="\n".join(results))  # 返回当前函数的处理结果。


def _iter_search_files(base: Path, include_pattern: str, sandbox_root: Path):
    for root, dirnames, filenames in os.walk(base):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        root_path = Path(root)
        for filename in sorted(filenames):
            file_path = root_path / filename
            resolved = file_path.resolve(strict=False)  # 保存配置值或中间计算结果。
            if not is_path_in_sandbox(resolved, sandbox_root):  # 根据条件决定是否执行后续分支。
                continue
            try:  # 开始可能抛出异常的保护代码块。
                rel = file_path.relative_to(base)  # 保存配置值或中间计算结果。
            except ValueError:  # 捕获并处理指定异常。
                continue
            if ".." in rel.parts:  # 根据条件决定是否执行后续分支。
                continue
            if any(part in SKIP_DIRS for part in rel.parts):  # 根据条件决定是否执行后续分支。
                continue
            if not _include_matches(str(rel), include_pattern):
                continue
            yield file_path, rel


def _include_matches(relative_path: str, include_pattern: str) -> bool:
    if fnmatch.fnmatch(relative_path, include_pattern):
        return True
    if "/" not in include_pattern and fnmatch.fnmatch(Path(relative_path).name, include_pattern):
        return True
    if include_pattern.startswith("**/") and fnmatch.fnmatch(relative_path, include_pattern[3:]):
        return True
    return False
