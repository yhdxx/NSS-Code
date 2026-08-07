from __future__ import annotations  # 启用未来版本语法特性。

from typing import TYPE_CHECKING, Any  # 导入当前模块需要的依赖。
from contextlib import contextmanager
from pathlib import Path

from mycodingagent.tool_runtime.base import Tool, get_sandbox_root  # 导入当前模块需要的依赖。

if TYPE_CHECKING:  # 根据条件决定是否执行后续分支。
    from mycodingagent.workspace.file_cache import FileCache  # 导入当前模块需要的依赖。
    from mycodingagent.memory import MemoryRuntime


class ToolRegistry:  # 定义用于封装相关状态和行为的类。
    def __init__(self) -> None:  # 定义函数，封装可复用逻辑。
        self._tools: dict[str, Tool] = {}  # 保存配置值或中间计算结果。
        self._disabled: set[str] = set()  # 保存配置值或中间计算结果。

    def register(self, tool: Tool) -> None:  # 定义函数，封装可复用逻辑。
        self._tools[tool.name] = tool  # 保存配置值或中间计算结果。

    def get(self, name: str) -> Tool | None:  # 定义函数，封装可复用逻辑。
        return self._tools.get(name)  # 返回当前函数的处理结果。


    def is_enabled(self, name: str) -> bool:  # 定义函数，封装可复用逻辑。
        return name in self._tools and name not in self._disabled  # 返回当前函数的处理结果。

    def enable(self, name: str) -> None:  # 定义函数，封装可复用逻辑。
        self._disabled.discard(name)  # 执行当前步骤的业务逻辑。


    def disable(self, name: str) -> None:  # 定义函数，封装可复用逻辑。
        if name in self._tools:  # 根据条件决定是否执行后续分支。
            self._disabled.add(name)  # 执行当前步骤的业务逻辑。

    def enable_all(self) -> None:  # 定义函数，封装可复用逻辑。
        self._disabled.clear()  # 执行当前步骤的业务逻辑。


    def list_tools(self) -> list[Tool]:  # 定义函数，封装可复用逻辑。
        return list(self._tools.values())  # 返回当前函数的处理结果。


    def get_all_schemas(self, protocol: str = "anthropic") -> list[dict[str, Any]]:  # 定义函数，封装可复用逻辑。
        schemas: list[dict[str, Any]] = []  # 保存配置值或中间计算结果。
        for name, tool in self._tools.items():  # 遍历集合中的元素。
            if name in self._disabled:  # 根据条件决定是否执行后续分支。
                continue  # 跳过本轮循环剩余逻辑。
            base = tool.get_schema()  # 保存配置值或中间计算结果。
            if protocol in ("openai", "openai-compat"):  # 根据条件决定是否执行后续分支。
                schemas.append({  # 执行当前步骤的业务逻辑。
                    "type": "function",  # 提供上方表达式需要的文本内容。
                    "name": base["name"],  # 提供上方表达式需要的文本内容。
                    "description": base["description"],  # 提供上方表达式需要的文本内容。
                    "parameters": base["input_schema"],  # 提供上方表达式需要的文本内容。
                })  # 执行当前步骤的业务逻辑。
            else:  # 处理前面条件都不满足的默认分支。
                schemas.append(base)  # 执行当前步骤的业务逻辑。
        return schemas  # 返回当前函数的处理结果。

    @contextmanager
    def retarget_sandbox(self, root: Path):
        """Temporarily point filesystem tools at an isolated worktree."""
        saved: list[tuple[Any, str, Any]] = []
        disabled_before = set(self._disabled)
        for tool in self._tools.values():
            if hasattr(tool, "_sandbox_root"):
                saved.append((tool, "_sandbox_root", getattr(tool, "_sandbox_root")))
                setattr(tool, "_sandbox_root", root)
            if hasattr(tool, "_checkpoint_hook"):
                saved.append((tool, "_checkpoint_hook", getattr(tool, "_checkpoint_hook")))
                setattr(tool, "_checkpoint_hook", None)
        self.disable("ProjectArchitecture")
        self.disable("UnitDependencyGraph")
        self.disable("UpdateProjectDescription")
        try:
            yield
        finally:
            for target, attribute, value in reversed(saved):
                setattr(target, attribute, value)
            self._disabled = disabled_before


def create_default_registry(  # 定义函数，封装可复用逻辑。
    file_cache: FileCache | None = None,
    file_history: Any = None,
    file_state_cache: Any = None,
    workspace_tracker: Any = None,
    memory_runtime: MemoryRuntime | None = None,
    command_approval_hook: Any = None,
    terminal_input: Any = None,
    project_graph_service: Any = None,
    bash_policy_evaluator: Any = None,
    media_runtime: Any = None,
    web_fetch_runtime: Any = None,
    workspace_runtime: Any = None,
) -> ToolRegistry:
    from mycodingagent.tool_runtime.ask_user import AskUser
    from mycodingagent.tool_runtime.bash import Bash  # 导入当前模块需要的依赖。
    from mycodingagent.tool_runtime.edit_file import EditFile  # 导入当前模块需要的依赖。
    from mycodingagent.tool_runtime.file_state_cache import FileStateCache  # 导入当前模块需要的依赖。
    from mycodingagent.tool_runtime.glob import Glob  # 导入当前模块需要的依赖。
    from mycodingagent.tool_runtime.grep import Grep  # 导入当前模块需要的依赖。
    from mycodingagent.tool_runtime.memory_lookup import (
        BatchRecoverContext,
        CommitWorkingContext,
        GetRecentConversationTurns,
        RestoreSession,
        SearchRecoverableContext,
        SearchSessionHistory,
        SummarizeCurrentTurnMessage,
    )
    from mycodingagent.tool_runtime.read_file import ReadFile  # 导入当前模块需要的依赖。
    from mycodingagent.tool_runtime.write_file import WriteFile  # 导入当前模块需要的依赖。

    if bash_policy_evaluator is None:
        raise ValueError("bash_policy_evaluator is required")
    file_state_cache = file_state_cache or FileStateCache()  # 保存配置值或中间计算结果。
    sandbox_root = get_sandbox_root()  # 保存配置值或中间计算结果。
    registry = ToolRegistry()  # 保存配置值或中间计算结果。
    registry.register(AskUser(terminal_input))
    registry.register(  # 执行当前步骤的业务逻辑。
        ReadFile(  # 执行当前步骤的业务逻辑。
            file_cache=file_cache,  # 保存配置值或中间计算结果。
            file_state_cache=file_state_cache,  # 保存配置值或中间计算结果。
            sandbox_root=sandbox_root,  # 保存配置值或中间计算结果。
        )  # 结束上方的多行结构。
    )  # 结束上方的多行结构。
    registry.register(  # 执行当前步骤的业务逻辑。
        WriteFile(  # 执行当前步骤的业务逻辑。
            file_cache=file_cache,  # 保存配置值或中间计算结果。
            file_history=file_history,  # 保存配置值或中间计算结果。
            file_state_cache=file_state_cache,  # 保存配置值或中间计算结果。
            workspace_tracker=workspace_tracker,
            sandbox_root=sandbox_root,  # 保存配置值或中间计算结果。
            approval_hook=None,
            checkpoint_hook=memory_runtime,
        )  # 结束上方的多行结构。
    )  # 结束上方的多行结构。
    registry.register(  # 执行当前步骤的业务逻辑。
        EditFile(  # 执行当前步骤的业务逻辑。
            file_cache=file_cache,  # 保存配置值或中间计算结果。
            file_history=file_history,  # 保存配置值或中间计算结果。
            file_state_cache=file_state_cache,  # 保存配置值或中间计算结果。
            workspace_tracker=workspace_tracker,
            sandbox_root=sandbox_root,  # 保存配置值或中间计算结果。
            approval_hook=None,
            checkpoint_hook=memory_runtime,
        )  # 结束上方的多行结构。
    )  # 结束上方的多行结构。
    registry.register(
        Bash(
            sandbox_root=sandbox_root,
            approval_hook=command_approval_hook,
            policy_evaluator=bash_policy_evaluator,
            session_runtime=workspace_runtime,
        )
    )
    registry.register(Glob(sandbox_root=sandbox_root))  # 保存配置值或中间计算结果。
    registry.register(Grep(sandbox_root=sandbox_root))  # 保存配置值或中间计算结果。
    if media_runtime is not None:
        from mycodingagent.tool_runtime.media import AnalyzeImage, TranscribeAudio

        if media_runtime.audio_availability().enabled:
            registry.register(TranscribeAudio(media_runtime))
        if media_runtime.vision_availability().enabled:
            registry.register(AnalyzeImage(media_runtime))
    if web_fetch_runtime is not None:
        from mycodingagent.tool_runtime.fetch_url import FetchUrl

        registry.register(FetchUrl(web_fetch_runtime))
    if project_graph_service is not None:
        from mycodingagent.tool_runtime.project_graph import (
            ProjectArchitectureTool,
            UnitDependencyGraphTool,
            UpdateProjectDescriptionTool,
        )

        registry.register(ProjectArchitectureTool(project_graph_service))
        registry.register(UnitDependencyGraphTool(project_graph_service))
        registry.register(UpdateProjectDescriptionTool(project_graph_service))
    if memory_runtime is not None:
        registry.register(CommitWorkingContext(memory_runtime))
        registry.register(BatchRecoverContext(memory_runtime))
        registry.register(RestoreSession(memory_runtime))
        registry.register(SearchRecoverableContext(memory_runtime))
        registry.register(SearchSessionHistory(memory_runtime))
        registry.register(GetRecentConversationTurns(memory_runtime))
        registry.register(SummarizeCurrentTurnMessage(memory_runtime))
    return registry  # 返回当前函数的处理结果。
