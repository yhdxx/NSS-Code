from __future__ import annotations  # 启用未来版本语法特性。

import fnmatch
import os
from pathlib import Path  # 导入当前模块需要的依赖。

from pydantic import BaseModel, Field  # 导入当前模块需要的依赖。

from mycodingagent.tool_runtime.base import SKIP_DIRS, Tool, ToolResult, is_path_in_sandbox, resolve_sandbox_path  # 导入当前模块需要的依赖。

MAX_GLOB_MATCHES = 200


class Params(BaseModel):  # 定义用于封装相关状态和行为的类。
    pattern: str = Field(description="Glob pattern to match (e.g. '**/*.py')")  # 保存配置值或中间计算结果。
    path: str = Field(default=".", description="Base directory to search from")  # 保存配置值或中间计算结果。


class Glob(Tool):  # 定义用于封装相关状态和行为的类。
    name = "Glob"  # 保存配置值或中间计算结果。
    description = (
        "Find sandbox files matching a glob pattern, returning relative paths. Prefer targeted patterns "
        "like '*.py' or 'backend/*.py'. Avoid broad workspace scans like '**/*' unless explicitly needed."
    )  # 保存配置值或中间计算结果。
    params_model = Params  # 保存配置值或中间计算结果。
    category = "read"  # 保存配置值或中间计算结果。
    is_concurrency_safe = True  # 保存配置值或中间计算结果。

    def __init__(self, sandbox_root: Path | None = None) -> None:  # 定义函数，封装可复用逻辑。
        self._sandbox_root = sandbox_root  # 保存配置值或中间计算结果。


    async def execute(self, params: Params) -> ToolResult:  # 定义异步函数，供事件循环调用。
        base, error = resolve_sandbox_path(params.path, self._sandbox_root)  # 保存配置值或中间计算结果。
        if error:  # 根据条件决定是否执行后续分支。
            return ToolResult(output=error, is_error=True)  # 返回当前函数的处理结果。
        if not base.exists():  # 根据条件决定是否执行后续分支。
            return ToolResult(output=f"Error: path not found: {params.path}", is_error=True)  # 返回当前函数的处理结果。

        try:  # 开始可能抛出异常的保护代码块。
            matches: list[str] = []  # 保存配置值或中间计算结果。
            for file_path in _iter_matching_files(base, params.pattern, self._sandbox_root or base):
                matches.append(str(file_path.relative_to(base)))  # 执行当前步骤的业务逻辑。
                if len(matches) >= MAX_GLOB_MATCHES:
                    break
            matches.sort()  # 执行当前步骤的业务逻辑。
        except Exception as e:  # 捕获并处理指定异常。
            return ToolResult(output=f"Error: {e}", is_error=True)  # 返回当前函数的处理结果。

        if not matches:  # 根据条件决定是否执行后续分支。
            return ToolResult(output="No files matched the pattern.")  # 返回当前函数的处理结果。
        output = "\n".join(matches)
        if len(matches) >= MAX_GLOB_MATCHES:
            output += f"\n... <truncated after {MAX_GLOB_MATCHES} matches; use a narrower pattern>"
        return ToolResult(output=output)  # 返回当前函数的处理结果。


def _iter_matching_files(base: Path, pattern: str, sandbox_root: Path):
    recursive = "**" in Path(pattern).parts
    if recursive:
        for root, dirnames, filenames in os.walk(base):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            root_path = Path(root)
            for filename in filenames:
                file_path = root_path / filename
                if _matches(file_path, base, pattern, sandbox_root):
                    yield file_path
        return

    for file_path in base.glob(pattern):
        if _matches(file_path, base, pattern, sandbox_root):
            yield file_path


def _matches(file_path: Path, base: Path, pattern: str, sandbox_root: Path) -> bool:
    if not file_path.is_file():  # 根据条件决定是否执行后续分支。
        return False
    resolved = file_path.resolve(strict=False)  # 保存配置值或中间计算结果。
    if not is_path_in_sandbox(resolved, sandbox_root):  # 根据条件决定是否执行后续分支。
        return False
    try:  # 开始可能抛出异常的保护代码块。
        relative = file_path.relative_to(base)  # 保存配置值或中间计算结果。
    except ValueError:  # 捕获并处理指定异常。
        return False
    if ".." in relative.parts:  # 根据条件决定是否执行后续分支。
        return False
    if any(part in SKIP_DIRS for part in relative.parts):  # 根据条件决定是否执行后续分支。
        return False
    relative_text = str(relative)
    if fnmatch.fnmatch(relative_text, pattern):
        return True
    if pattern.startswith("**/") and fnmatch.fnmatch(relative_text, pattern[3:]):
        return True
    return False
