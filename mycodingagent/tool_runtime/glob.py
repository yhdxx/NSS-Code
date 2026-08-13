from __future__ import annotations  # 启用未来版本语法特性。

import os
from pathlib import Path  # 导入当前模块需要的依赖。

from pydantic import BaseModel, Field  # 导入当前模块需要的依赖。

from mycodingagent.tool_runtime.base import (
    DOCKER_WORKSPACE_ALIAS,
    SKIP_DIRS,
    Tool,
    ToolResult,
    expand_brace_patterns,
    get_sandbox_root,
    glob_pattern_matches,
    is_path_denied,
    is_path_readable,
    resolve_read_path,
)

MAX_GLOB_MATCHES = 200


class Params(BaseModel):  # 定义用于封装相关状态和行为的类。
    pattern: str = Field(min_length=1, description="要匹配的 Glob 模式，例如 '**/*.{py,pyi}'")  # 保存配置值或中间计算结果。
    path: str = Field(default=".", min_length=1, description="搜索起始目录")  # 保存配置值或中间计算结果。


class Glob(Tool):  # 定义用于封装相关状态和行为的类。
    name = "Glob"  # 保存配置值或中间计算结果。
    description = (
        "查找沙箱内匹配 Glob 模式的文件并返回相对路径。优先使用 '*.py' 或 'backend/*.py' 等定向模式；"
        "除非确有必要，避免使用 '**/*' 宽泛扫描整个工作区。"
    )  # 保存配置值或中间计算结果。
    params_model = Params  # 保存配置值或中间计算结果。
    category = "read"  # 保存配置值或中间计算结果。
    is_concurrency_safe = True  # 保存配置值或中间计算结果。

    def __init__(self, sandbox_root: Path | None = None) -> None:  # 定义函数，封装可复用逻辑。
        self._sandbox_root = sandbox_root  # 保存配置值或中间计算结果。


    async def execute(self, params: Params) -> ToolResult:  # 定义异步函数，供事件循环调用。
        base, error = resolve_read_path(params.path, self._sandbox_root)  # 保存配置值或中间计算结果。
        if error:  # 根据条件决定是否执行后续分支。
            return ToolResult(output=error, is_error=True)  # 返回当前函数的处理结果。
        if not base.exists():  # 根据条件决定是否执行后续分支。
            return ToolResult(output=f"错误：路径不存在：{params.path}", is_error=True)  # 返回当前函数的处理结果。
        if not base.is_dir():
            return ToolResult(output=f"错误：Glob 的 path 必须是目录：{params.path}", is_error=True)

        try:  # 开始可能抛出异常的保护代码块。
            sandbox_root = (self._sandbox_root or get_sandbox_root()).resolve(strict=False)
            search_base, normalized_pattern = _normalize_glob_target(
                base,
                params.pattern,
                sandbox_root,
            )
            patterns = expand_brace_patterns(normalized_pattern)
            matches: list[str] = []  # 保存配置值或中间计算结果。
            for file_path in _iter_matching_files(search_base, patterns, sandbox_root):
                matches.append(file_path.relative_to(search_base).as_posix())  # 执行当前步骤的业务逻辑。
                if len(matches) > MAX_GLOB_MATCHES:
                    break
        except (OSError, ValueError) as e:  # 捕获并处理指定异常。
            return ToolResult(output=f"错误：{e}", is_error=True)  # 返回当前函数的处理结果。

        if not matches:  # 根据条件决定是否执行后续分支。
            return ToolResult(output="没有文件匹配该模式。")  # 返回当前函数的处理结果。
        truncated = len(matches) > MAX_GLOB_MATCHES
        output = "\n".join(matches[:MAX_GLOB_MATCHES])
        if truncated:
            output += f"\n... <匹配数达到 {MAX_GLOB_MATCHES} 后已截断；请使用更精确的模式>"
        return ToolResult(output=output)  # 返回当前函数的处理结果。


def _static_glob_root(pattern_path: Path) -> Path | None:
    static_parts: list[str] = []
    for part in pattern_path.parts:
        if any(ch in part for ch in "*?[]{}"):
            break
        static_parts.append(part)
    if not static_parts:
        return None
    root = Path(*static_parts)
    if root == Path("/"):
        return root
    return root if root.is_dir() else root.parent


def _normalize_glob_target(base: Path, pattern: str, sandbox_root: Path) -> tuple[Path, str]:
    pattern_path = Path(pattern)
    if not pattern_path.is_absolute():
        if ".." in pattern_path.parts:
            raise ValueError("Glob pattern 不能包含 '..'")
        return base, pattern

    if pattern_path == DOCKER_WORKSPACE_ALIAS or DOCKER_WORKSPACE_ALIAS in pattern_path.parents:
        relative = pattern_path.relative_to(DOCKER_WORKSPACE_ALIAS)
    else:
        try:
            relative = pattern_path.relative_to(sandbox_root)
        except ValueError:
            static_root = _static_glob_root(pattern_path)
            if static_root is None or not is_path_readable(static_root, sandbox_root):
                raise ValueError("绝对 Glob pattern 必须位于 /workspace、沙箱根目录或可读目录内")
            return static_root, pattern_path.relative_to(static_root).as_posix()
    if ".." in relative.parts:
        raise ValueError("Glob pattern 不能包含 '..'")
    return sandbox_root, relative.as_posix()


def _iter_matching_files(base: Path, patterns: tuple[str, ...], sandbox_root: Path):
    recursive = any("**" in Path(pattern).parts for pattern in patterns)
    seen: set[Path] = set()
    if recursive:
        for root, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in SKIP_DIRS and not is_path_denied(Path(root) / name, sandbox_root)
            )
            root_path = Path(root)
            for filename in sorted(filenames):
                file_path = root_path / filename
                if file_path not in seen and _matches(file_path, base, patterns, sandbox_root):
                    seen.add(file_path)
                    yield file_path
        return

    candidates = {
        file_path
        for pattern in patterns
        for file_path in base.glob(pattern)
    }
    for file_path in sorted(candidates, key=lambda item: item.as_posix()):
        if _matches(file_path, base, patterns, sandbox_root):
            yield file_path


def _matches(file_path: Path, base: Path, patterns: tuple[str, ...], sandbox_root: Path) -> bool:
    if not file_path.is_file():  # 根据条件决定是否执行后续分支。
        return False
    resolved = file_path.resolve(strict=False)  # 保存配置值或中间计算结果。
    if not is_path_readable(resolved, sandbox_root):  # 根据条件决定是否执行后续分支。
        return False
    try:  # 开始可能抛出异常的保护代码块。
        relative = file_path.relative_to(base)  # 保存配置值或中间计算结果。
    except ValueError:  # 捕获并处理指定异常。
        return False
    if ".." in relative.parts:  # 根据条件决定是否执行后续分支。
        return False
    if any(part in SKIP_DIRS for part in relative.parts):  # 根据条件决定是否执行后续分支。
        return False
    relative_text = relative.as_posix()
    return any(_pattern_matches(relative_text, pattern) for pattern in patterns)


def _pattern_matches(relative_path: str, pattern: str) -> bool:
    if "/" not in pattern and "/" in relative_path:
        return False
    return glob_pattern_matches(relative_path, pattern)
