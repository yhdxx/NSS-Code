from __future__ import annotations  # 启用未来版本语法特性。

from abc import ABC, abstractmethod  # 导入当前模块需要的依赖。
from dataclasses import dataclass  # 导入当前模块需要的依赖。
from enum import Enum
from pathlib import Path, PurePosixPath  # 导入当前模块需要的依赖。
from typing import Any, Literal  # 导入当前模块需要的依赖。

from pydantic import BaseModel  # 导入当前模块需要的依赖。

from mycodingagent.configuration import CONFIG  # 统一读取沙箱路径、输出长度等项目配置。
from mycodingagent.tool_contracts import apply_tool_intent_schema

SKIP_DIRS = set(CONFIG.sandbox.skip_dirs)  # 保存配置值或中间计算结果。

MAX_OUTPUT_CHARS = CONFIG.sandbox.max_output_chars  # 保存配置值或中间计算结果。
SANDBOX_ROOT_ENV = CONFIG.sandbox.root_env  # 保存配置值或中间计算结果。

ToolCategory = Literal["read", "write", "command", "state"]  # 保存配置值或中间计算结果。
DOCKER_WORKSPACE_ALIAS = CONFIG.sandbox.docker_workspace_alias  # 兼容 Docker 容器内常见的工作区根路径别名。


class AccessMode(str, Enum):
    WORKSPACE_ONLY = "workspace_only"
    GLOBAL_READ = "global_read"
    GLOBAL_WRITE = "global_write"


def get_access_mode() -> AccessMode:
    try:
        return AccessMode(CONFIG.sandbox.access_mode)
    except ValueError:
        return AccessMode.GLOBAL_READ


OUT_OF_WORKSPACE_WRITE_MESSAGE = (
    "当前操作位于沙箱工作区域之外，你对工作区域之外只允许只读操作，不允许修改非工作区文件"
)


def expand_brace_patterns(pattern: str, *, max_expansions: int = 32) -> tuple[str, ...]:
    """Expand common `{a,b}` glob groups without invoking a shell."""
    pending = [pattern]
    expanded: list[str] = []
    while pending:
        current = pending.pop()
        open_index = -1
        close_index = -1
        for index, char in enumerate(current):
            if char == "{":
                open_index = index
            elif char == "}" and open_index >= 0:
                body = current[open_index + 1 : index]
                if "," in body and "{" not in body:
                    close_index = index
                    break
                open_index = -1
        if close_index < 0:
            expanded.append(current)
            continue
        choices = current[open_index + 1 : close_index].split(",")
        if not all(choices):
            raise ValueError("Glob 花括号选项不能为空")
        prefix = current[:open_index]
        suffix = current[close_index + 1 :]
        pending.extend(prefix + choice + suffix for choice in reversed(choices))
        if len(pending) + len(expanded) > max_expansions:
            raise ValueError(f"Glob 花括号展开不能超过 {max_expansions} 个模式")
    return tuple(dict.fromkeys(expanded))


def glob_pattern_matches(relative_path: str, pattern: str) -> bool:
    """Match a POSIX relative path and let every `**/` span zero directories."""
    pending = [pattern]
    seen: set[str] = set()
    candidate = PurePosixPath(relative_path)
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if candidate.match(current):
            return True
        marker = current.find("**/")
        while marker >= 0:
            pending.append(current[:marker] + current[marker + 3 :])
            marker = current.find("**/", marker + 3)
    return False


def get_sandbox_root() -> Path:  # 定义函数，封装可复用逻辑。
    return CONFIG.sandbox.root.expanduser().resolve(strict=False)  # 返回当前函数的处理结果。


def is_path_in_sandbox(path: Path, sandbox_root: Path) -> bool:  # 定义函数，封装可复用逻辑。
    try:  # 开始可能抛出异常的保护代码块。
        path.relative_to(sandbox_root)  # 执行当前步骤的业务逻辑。
    except ValueError:  # 捕获并处理指定异常。
        return False  # 返回当前函数的处理结果。
    return True  # 返回当前函数的处理结果。


def _resolve_raw_path(raw_path: str, root: Path) -> tuple[Path | None, str]:
    raw_path = raw_path.strip()
    if not raw_path:
        return None, "错误：路径为空"
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = root / path
    elif path == DOCKER_WORKSPACE_ALIAS or DOCKER_WORKSPACE_ALIAS in path.parents:
        path = root / path.relative_to(DOCKER_WORKSPACE_ALIAS)
    try:
        resolved = path.resolve(strict=False)
    except RuntimeError as exc:
        return None, f"解析路径失败：{exc}"
    return resolved, ""


def is_path_within(path: Path, roots: tuple[Path, ...]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return True
    return False


def _allowlist_paths() -> tuple[Path, ...]:
    return tuple(
        Path(item).expanduser().resolve(strict=False)
        for item in CONFIG.sandbox.read_allowlist
    )


def _denylist_paths() -> tuple[Path, ...]:
    return tuple(
        Path(item).resolve(strict=False)
        for item in CONFIG.sandbox.effective_read_denylist()
    )


def _is_isolated_root(root: Path) -> bool:
    return root != get_sandbox_root()


def resolve_read_path(raw_path: str, sandbox_root: Path | None = None) -> tuple[Path | None, str]:
    root = (sandbox_root or get_sandbox_root()).resolve(strict=False)
    resolved, error = _resolve_raw_path(raw_path, root)
    if error:
        return None, error
    if is_path_in_sandbox(resolved, root):
        return resolved, ""
    if _is_isolated_root(root):
        return None, f"错误：路径位于沙箱之外：{raw_path}\n沙箱根目录：{root}"
    if is_path_within(resolved, _denylist_paths()):
        return None, f"错误：路径位于不可读目录内：{raw_path}"
    if is_path_within(resolved, _allowlist_paths()):
        return resolved, ""
    if get_access_mode() in (AccessMode.GLOBAL_READ, AccessMode.GLOBAL_WRITE):
        return resolved, ""
    return None, f"错误：路径位于沙箱之外：{raw_path}\n沙箱根目录：{root}"


def resolve_write_path(raw_path: str, sandbox_root: Path | None = None) -> tuple[Path | None, str]:
    root = (sandbox_root or get_sandbox_root()).resolve(strict=False)
    resolved, error = _resolve_raw_path(raw_path, root)
    if error:
        return None, error
    if is_path_in_sandbox(resolved, root):
        return resolved, ""
    if _is_isolated_root(root):
        return None, OUT_OF_WORKSPACE_WRITE_MESSAGE
    if is_path_within(resolved, _denylist_paths()):
        return None, OUT_OF_WORKSPACE_WRITE_MESSAGE
    if get_access_mode() == AccessMode.GLOBAL_WRITE:
        return resolved, ""
    return None, OUT_OF_WORKSPACE_WRITE_MESSAGE


def is_path_readable(path: Path, sandbox_root: Path | None = None) -> bool:
    root = (sandbox_root or get_sandbox_root()).resolve(strict=False)
    resolved = path.resolve(strict=False)
    if is_path_in_sandbox(resolved, root):
        return True
    if _is_isolated_root(root):
        return False
    if is_path_within(resolved, _denylist_paths()):
        return False
    if is_path_within(resolved, _allowlist_paths()):
        return True
    return get_access_mode() in (AccessMode.GLOBAL_READ, AccessMode.GLOBAL_WRITE)


def is_path_denied(path: Path, sandbox_root: Path | None = None) -> bool:
    root = (sandbox_root or get_sandbox_root()).resolve(strict=False)
    resolved = path.resolve(strict=False)
    if is_path_in_sandbox(resolved, root):
        return False
    if _is_isolated_root(root):
        return True
    return is_path_within(resolved, _denylist_paths())


def resolve_sandbox_path(raw_path: str, sandbox_root: Path | None = None) -> tuple[Path | None, str]:
    root = (sandbox_root or get_sandbox_root()).resolve(strict=False)
    resolved, error = _resolve_raw_path(raw_path, root)
    if error:
        return None, error
    if not is_path_in_sandbox(resolved, root):
        return None, f"错误：路径位于沙箱之外：{raw_path}\n沙箱根目录：{root}"
    return resolved, ""


@dataclass  # 声明装饰器，调整下一行定义的行为。
class ToolResult:  # 定义用于封装相关状态和行为的类。
    output: str  # 执行当前步骤的业务逻辑。
    is_error: bool = False  # 保存配置值或中间计算结果。


class Tool(ABC):  # 定义用于封装相关状态和行为的类。
    name: str  # 执行当前步骤的业务逻辑。
    description: str  # 执行当前步骤的业务逻辑。
    params_model: type[BaseModel]  # 执行当前步骤的业务逻辑。
    category: ToolCategory = "read"  # 保存配置值或中间计算结果。
    is_concurrency_safe: bool = False  # 保存配置值或中间计算结果。
    is_system_tool: bool = False  # 保存配置值或中间计算结果。

    @property  # 声明装饰器，调整下一行定义的行为。
    def is_read_only(self) -> bool:  # 定义函数，封装可复用逻辑。
        return self.category == "read"  # 返回当前函数的处理结果。


    def get_schema(self) -> dict[str, Any]:  # 定义函数，封装可复用逻辑。
        schema = self.params_model.model_json_schema()  # 保存配置值或中间计算结果。
        schema.pop("title", None)  # 执行当前步骤的业务逻辑。
        apply_tool_intent_schema(schema)
        return {  # 返回当前函数的处理结果。
            "name": self.name,  # 提供上方表达式需要的文本内容。
            "description": self.description,  # 提供上方表达式需要的文本内容。
            "input_schema": schema,  # 提供上方表达式需要的文本内容。
        }  # 结束上方的多行结构。

    @abstractmethod  # 声明装饰器，调整下一行定义的行为。
    async def execute(self, params: BaseModel) -> ToolResult: ...  # 定义异步函数，供事件循环调用。
