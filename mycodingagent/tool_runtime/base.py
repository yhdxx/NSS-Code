from __future__ import annotations  # 启用未来版本语法特性。

from abc import ABC, abstractmethod  # 导入当前模块需要的依赖。
from dataclasses import dataclass  # 导入当前模块需要的依赖。
from pathlib import Path  # 导入当前模块需要的依赖。
from typing import Any, Literal  # 导入当前模块需要的依赖。

from pydantic import BaseModel  # 导入当前模块需要的依赖。

from mycodingagent.configuration import CONFIG  # 统一读取沙箱路径、输出长度等项目配置。

SKIP_DIRS = set(CONFIG.sandbox.skip_dirs)  # 保存配置值或中间计算结果。

MAX_OUTPUT_CHARS = CONFIG.sandbox.max_output_chars  # 保存配置值或中间计算结果。
SANDBOX_ROOT_ENV = CONFIG.sandbox.root_env  # 保存配置值或中间计算结果。

ToolCategory = Literal["read", "write", "command"]  # 保存配置值或中间计算结果。
DOCKER_WORKSPACE_ALIAS = CONFIG.sandbox.docker_workspace_alias  # 兼容 Docker 容器内常见的工作区根路径别名。


def get_sandbox_root() -> Path:  # 定义函数，封装可复用逻辑。
    return CONFIG.sandbox.root.expanduser().resolve(strict=False)  # 返回当前函数的处理结果。


def is_path_in_sandbox(path: Path, sandbox_root: Path) -> bool:  # 定义函数，封装可复用逻辑。
    try:  # 开始可能抛出异常的保护代码块。
        path.relative_to(sandbox_root)  # 执行当前步骤的业务逻辑。
    except ValueError:  # 捕获并处理指定异常。
        return False  # 返回当前函数的处理结果。
    return True  # 返回当前函数的处理结果。


def resolve_sandbox_path(raw_path: str, sandbox_root: Path | None = None) -> tuple[Path | None, str]:  # 定义函数，封装可复用逻辑。
    root = (sandbox_root or get_sandbox_root()).resolve(strict=False)  # 保存配置值或中间计算结果。
    raw_path = raw_path.strip()  # 统一去掉首尾空白，避免空格影响路径判断。
    if not raw_path:  # 根据条件决定是否执行后续分支。
        return None, "错误：路径为空"  # 返回当前函数的处理结果。

    path = Path(raw_path).expanduser()  # 保存配置值或中间计算结果。
    if not path.is_absolute():  # 根据条件决定是否执行后续分支。
        path = root / path  # 保存配置值或中间计算结果。
    elif path == DOCKER_WORKSPACE_ALIAS or DOCKER_WORKSPACE_ALIAS in path.parents:  # 根据条件决定是否执行后续分支。
        path = root / path.relative_to(DOCKER_WORKSPACE_ALIAS)  # 将 Docker 容器内的 /workspace 路径别名映射到本机沙箱根目录。

    try:  # 开始可能抛出异常的保护代码块。
        resolved = path.resolve(strict=False)  # 保存配置值或中间计算结果。
    except RuntimeError as exc:  # 捕获并处理指定异常。
        return None, f"解析路径失败：{exc}"  # 返回当前函数的处理结果。

    if not is_path_in_sandbox(resolved, root):  # 根据条件决定是否执行后续分支。
        return None, f"错误：路径位于沙箱之外：{raw_path}\n沙箱根目录：{root}"  # 返回当前函数的处理结果。

    return resolved, ""  # 返回当前函数的处理结果。


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
        properties = schema.setdefault("properties", {})
        if isinstance(properties, dict) and "intent" not in properties:
            properties["intent"] = {
                "type": "string",
                "description": "本次工具调用的简短目的；上下文虚拟化时用作紧凑元数据。",
                "maxLength": 160,
            }
        required = schema.setdefault("required", [])
        if isinstance(required, list) and "intent" not in required:
            required.append("intent")
        return {  # 返回当前函数的处理结果。
            "name": self.name,  # 提供上方表达式需要的文本内容。
            "description": self.description,  # 提供上方表达式需要的文本内容。
            "input_schema": schema,  # 提供上方表达式需要的文本内容。
        }  # 结束上方的多行结构。

    @abstractmethod  # 声明装饰器，调整下一行定义的行为。
    async def execute(self, params: BaseModel) -> ToolResult: ...  # 定义异步函数，供事件循环调用。
