from __future__ import annotations  # 允许在类型注解中使用尚未定义的类型，并启用较新的注解解析行为。

import asyncio  # 提供异步事件循环、异步子进程等待等能力，本文件用它运行 async 主流程。
import hashlib  # 为 PromptDebug 生成稳定短哈希，避免打印原始 prompt 内容。
import json  # 负责解析模型生成的工具参数 JSON，以及把参数格式化成终端可读文本。
from dataclasses import dataclass, replace  # 用轻量数据类保存流式返回过程中尚未拼完整的工具调用。
from uuid import uuid4

from typing import Any  # `Any` 用在 OpenAI 消息、工具 schema 等动态 JSON 结构的类型标注中。

from mycodingagent.configuration import CONFIG  # 统一读取 API、模型和客户端展示相关配置。
from mycodingagent.llm_runtime.model_manager import ModelManager
from mycodingagent.llm_runtime.providers import ChatRequest, PendingToolCall, normalize_stream_result
from mycodingagent.memory import MemoryRuntime, TokenUsageRecord, TokenUsageSummary
from mycodingagent.memory.budget import estimate_tokens
from mycodingagent.memory.message_filters import (
    is_skill_related_tool,
    persistent_assistant_tool_message,
    remove_trailing_incomplete_tool_call,
)
from mycodingagent.tool_contracts import MAX_TOOL_INTENT_CHARS
from mycodingagent.llm_runtime.context import (
    ContextBudgetState,
    PromptRenderer,
    RenderedPrompt,
    RuntimeContextBuilder,
    freeze_model_visible_user_message,
    render_current_turn_for_model,
)
from mycodingagent.llm_runtime.streaming import stream_one_round
from mycodingagent.llm_runtime.system_prompt import PromptFeatures, build_system_prompt
from mycodingagent.terminal_ui.output import (
    processing_status,
    render_assistant_markdown,
    render_assistant_text,
    render_project_graph_bootstrap_tree,
    tool_status_message,
)
from mycodingagent.terminal_ui.message_queue import FollowUpSignal
from mycodingagent.terminal_ui.application import create_assistant_stream, request_plan_selection
from mycodingagent.tool_runtime import ToolRegistry, create_default_registry  # 导入本地工具注册表类型，以及创建默认读写/搜索/Bash 工具的方法。
from mycodingagent.tool_runtime.execution import (
    CodeQueryLedger,
    RepeatedFailureTracker,
    ToolExecution,
    execute_tool,
    parse_tool_arguments_object,
)
from mycodingagent.plan_runtime import InteractionMode, PlanRuntime, TurnToolPolicy

MAX_TOOL_ROUNDS = CONFIG.client.max_tool_rounds  # 单次用户请求最多允许模型连续调用工具的轮数，用于防止无限循环。
MAX_DISPLAY_STRING_CHARS = CONFIG.client.max_display_string_chars  # 终端展示超长字符串参数时的最大字符数，避免 WriteFile 内容刷屏。
MAX_TOOL_OUTPUT_CHARS = CONFIG.client.max_tool_output_chars
API_MAX_RETRIES = CONFIG.client.api_max_retries
MULTILINE_ARGUMENT_FIELDS = CONFIG.client.multiline_argument_fields  # 这些字段通常包含代码、命令或长文本，打印工具调用时优先按多行展示。
DEBUG = CONFIG.client.debug
STEP_TOKEN = CONFIG.client.step_token
ROUND_TOKEN = CONFIG.client.round_token
CONVERSATION_TOKEN = CONFIG.client.conversation_token


class ToolRoundBudget:
    """Bound consecutive model tool rounds, with optional plan-progress renewal."""

    def __init__(self, max_rounds: int, *, renewable: bool) -> None:
        self.max_rounds = max(0, int(max_rounds))
        self.remaining = self.max_rounds
        self.renewable = renewable

    def consume(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True

    def renew_after_plan_progress(self) -> bool:
        if not self.renewable:
            return False
        self.remaining = self.max_rounds
        return True


@dataclass
class PromptDebugSnapshot:
    request_hash: str
    fixed_system_hash: str
    temporary_system_hash: str
    historical_messages_hash: str
    current_turn_hash: str
    runtime_context_hash: str
    rendered_prompt_hash: str
    tools_hash: str
    request_tokens: int
    fixed_system_tokens: int
    temporary_system_tokens: int
    historical_messages_tokens: int
    current_turn_tokens: int
    runtime_context_tokens: int
    rendered_prompt_tokens: int
    stored_user_prompt_tokens: int
    tools_tokens: int
    message_count: int
    tool_count: int
    rendered_prompt_format_version: str
    message_hashes: tuple[str, ...]
    message_tokens: tuple[int, ...]
    message_roles: tuple[str, ...]


_LAST_PROMPT_DEBUG_SNAPSHOT: PromptDebugSnapshot | None = None


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def estimated_json_tokens(value: Any) -> int:
    return estimate_tokens(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def api_usage_to_dict(usage: Any) -> dict[str, int]:
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    cache_hit = int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0)
    cache_miss = int(getattr(usage, "prompt_cache_miss_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
    if prompt_tokens and cache_hit == 0 and cache_miss == 0:
        cache_miss = prompt_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "prompt_cache_hit_tokens": cache_hit,
        "prompt_cache_miss_tokens": cache_miss,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def add_usage_to_summary(summary: TokenUsageSummary, values: dict[str, int]) -> None:
    summary.add(
        TokenUsageRecord(
            usage_id="",
            session_id="",
            request_index=0,
            prompt_tokens=values["prompt_tokens"],
            prompt_cache_hit_tokens=values["prompt_cache_hit_tokens"],
            prompt_cache_miss_tokens=values["prompt_cache_miss_tokens"],
            completion_tokens=values["completion_tokens"],
            total_tokens=values["total_tokens"],
        )
    )


def format_token_summary(label: str, summary: TokenUsageSummary) -> str:
    return (
        f"[Token][{label}] 请求 {summary.request_count} | 输入 {summary.prompt_tokens} "
        f"(缓存命中 {summary.prompt_cache_hit_tokens}, 未命中 {summary.prompt_cache_miss_tokens}) "
        f"| 输出 {summary.completion_tokens} | 总计 {summary.total_tokens}"
    )


def split_prompt_debug_sections(
    model_messages: list[dict[str, Any]],
    temporary_system_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    current_turn_start: int | None = None,
) -> dict[str, Any]:
    fixed_system = model_messages[:1] if model_messages and model_messages[0].get("role") == "system" else []
    temporary_count = len(temporary_system_messages)
    historical_start = len(fixed_system) + temporary_count
    if current_turn_start is None:
        current_turn_start = len(model_messages)
        for index in range(len(model_messages) - 1, historical_start - 1, -1):
            if model_messages[index].get("role") == "user":
                current_turn_start = index
                break
    current_turn_start = max(historical_start, min(current_turn_start, len(model_messages)))
    historical_messages = model_messages[historical_start:current_turn_start]
    current_turn = model_messages[current_turn_start:]
    return {
        "fixed_system": fixed_system,
        "temporary_system": temporary_system_messages,
        "historical_messages": historical_messages,
        "current_turn": current_turn,
        "tools": tools,
    }


def build_prompt_debug_snapshot(
    *,
    model_messages: list[dict[str, Any]],
    temporary_system_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    current_turn_start: int | None = None,
    rendered_prompt: RenderedPrompt | None = None,
) -> PromptDebugSnapshot:
    sections = split_prompt_debug_sections(model_messages, temporary_system_messages, tools, current_turn_start)
    fixed_system_tokens = estimated_json_tokens(sections["fixed_system"])
    temporary_system_tokens = estimated_json_tokens(sections["temporary_system"])
    historical_messages_tokens = estimated_json_tokens(sections["historical_messages"])
    current_turn_tokens = estimated_json_tokens(sections["current_turn"])
    runtime_context_tokens = rendered_prompt.runtime_context_tokens if rendered_prompt is not None else 0
    rendered_prompt_tokens = rendered_prompt.total_tokens if rendered_prompt is not None else 0
    stored_user_prompt_tokens = rendered_prompt.user_prompt_tokens if rendered_prompt is not None else 0
    tools_tokens = estimated_json_tokens(sections["tools"])
    runtime_context_hash = rendered_prompt.runtime_context_hash if rendered_prompt is not None else stable_json_hash(None)
    rendered_prompt_hash = stable_json_hash(rendered_prompt.content if rendered_prompt is not None else "")
    rendered_prompt_format_version = rendered_prompt.format_version if rendered_prompt is not None else ""
    return PromptDebugSnapshot(
        request_hash=stable_json_hash(model_messages),
        fixed_system_hash=stable_json_hash(sections["fixed_system"]),
        temporary_system_hash=stable_json_hash(sections["temporary_system"]),
        historical_messages_hash=stable_json_hash(sections["historical_messages"]),
        current_turn_hash=stable_json_hash(sections["current_turn"]),
        runtime_context_hash=runtime_context_hash,
        rendered_prompt_hash=rendered_prompt_hash,
        tools_hash=stable_json_hash(sections["tools"]),
        request_tokens=(
            fixed_system_tokens
            + temporary_system_tokens
            + historical_messages_tokens
            + current_turn_tokens
            + tools_tokens
        ),
        fixed_system_tokens=fixed_system_tokens,
        temporary_system_tokens=temporary_system_tokens,
        historical_messages_tokens=historical_messages_tokens,
        current_turn_tokens=current_turn_tokens,
        runtime_context_tokens=runtime_context_tokens,
        rendered_prompt_tokens=rendered_prompt_tokens,
        stored_user_prompt_tokens=stored_user_prompt_tokens,
        tools_tokens=tools_tokens,
        message_count=len(model_messages),
        tool_count=len(tools),
        rendered_prompt_format_version=rendered_prompt_format_version,
        message_hashes=tuple(stable_json_hash(message) for message in model_messages),
        message_tokens=tuple(estimated_json_tokens(message) for message in model_messages),
        message_roles=tuple(str(message.get("role") or "") for message in model_messages),
    )


def first_changed_prompt_debug_section(
    previous: PromptDebugSnapshot | None,
    current: PromptDebugSnapshot,
) -> str:
    if previous is None:
        return "none(first_request)"
    checks = [
        ("fixed_system", previous.fixed_system_hash, current.fixed_system_hash),
        ("temporary_system", previous.temporary_system_hash, current.temporary_system_hash),
        ("historical_messages", previous.historical_messages_hash, current.historical_messages_hash),
        ("runtime_context", previous.runtime_context_hash, current.runtime_context_hash),
        ("current_turn", previous.current_turn_hash, current.current_turn_hash),
        ("tools", previous.tools_hash, current.tools_hash),
    ]
    for section, previous_hash, current_hash in checks:
        if previous_hash != current_hash:
            return f"{section}({previous_hash}->{current_hash})"
    return "none"


def print_prompt_debug(
    *,
    snapshot: PromptDebugSnapshot,
    first_changed_section: str,
    common_prefix_messages: int = 0,
    common_prefix_tokens: int = 0,
    first_changed_message: str = "none",
) -> None:
    if not DEBUG:
        return
    print_token_block(
        "[PromptDebug] "
        f"request≈{snapshot.request_tokens} hash={snapshot.request_hash} | "
        f"fixed_system_tokens≈{snapshot.fixed_system_tokens} hash={snapshot.fixed_system_hash} | "
        f"temporary_system_tokens≈{snapshot.temporary_system_tokens} hash={snapshot.temporary_system_hash} | "
        f"historical_messages_tokens≈{snapshot.historical_messages_tokens} hash={snapshot.historical_messages_hash} | "
        f"runtime_context_tokens≈{snapshot.runtime_context_tokens} hash={snapshot.runtime_context_hash} | "
        f"rendered_prompt_tokens≈{snapshot.rendered_prompt_tokens} hash={snapshot.rendered_prompt_hash} "
        f"format={snapshot.rendered_prompt_format_version or 'none'} | "
        f"stored_user_prompt_tokens≈{snapshot.stored_user_prompt_tokens} | "
        f"current_turn_tokens≈{snapshot.current_turn_tokens} hash={snapshot.current_turn_hash} | "
        f"tools_tokens≈{snapshot.tools_tokens} tools={snapshot.tool_count} hash={snapshot.tools_hash} | "
        f"messages={snapshot.message_count} first_changed_section={first_changed_section} | "
        f"common_prefix_messages={common_prefix_messages} common_prefix_tokens≈{common_prefix_tokens} "
        f"first_changed_message={first_changed_message}",
    )


def print_prompt_debug_with_previous(snapshot: PromptDebugSnapshot) -> None:
    global _LAST_PROMPT_DEBUG_SNAPSHOT
    first_changed_section = first_changed_prompt_debug_section(_LAST_PROMPT_DEBUG_SNAPSHOT, snapshot)
    common_prefix_messages, common_prefix_tokens, first_changed_message = prompt_message_prefix_debug(
        _LAST_PROMPT_DEBUG_SNAPSHOT,
        snapshot,
    )
    print_prompt_debug(
        snapshot=snapshot,
        first_changed_section=first_changed_section,
        common_prefix_messages=common_prefix_messages,
        common_prefix_tokens=common_prefix_tokens,
        first_changed_message=first_changed_message,
    )
    _LAST_PROMPT_DEBUG_SNAPSHOT = snapshot


def prompt_message_prefix_debug(
    previous: PromptDebugSnapshot | None,
    current: PromptDebugSnapshot,
) -> tuple[int, int, str]:
    if previous is None:
        role = current.message_roles[0] if current.message_roles else "none"
        return 0, 0, f"0:{role}(first_request)"
    common = 0
    for previous_hash, current_hash in zip(previous.message_hashes, current.message_hashes):
        if previous_hash != current_hash:
            break
        common += 1
    common_tokens = sum(current.message_tokens[:common])
    if common < len(current.message_roles):
        changed = f"{common}:{current.message_roles[common]}"
    elif len(previous.message_roles) != len(current.message_roles):
        changed = f"{common}:removed"
    else:
        changed = "none"
    return common, common_tokens, changed


def print_token_block(*lines: str) -> None:
    print("=================", flush=True)
    for line in lines:
        print(line, flush=True)
    print("=================", flush=True)


def bash_display_classifier_from_registry(registry: Any):
    """Use the registered Bash tool's execution policy for terminal previews."""
    registry_get = getattr(registry, "get", None)
    bash_tool = registry_get("Bash") if callable(registry_get) else None
    classifier = getattr(bash_tool, "display_policy_level", None)
    return classifier if callable(classifier) else None


def context_budget_state_from_hot_snapshot(snapshot: Any) -> ContextBudgetState:
    ratio = float(getattr(snapshot, "usage_ratio", 0.0) or 0.0)
    if ratio >= CONFIG.memory.budget_emergency_ratio:
        stage = "emergency"
    elif ratio >= CONFIG.memory.budget_working_ratio:
        stage = "working"
    elif ratio >= CONFIG.memory.budget_soft_ratio:
        stage = "soft"
    else:
        stage = "normal"
    return ContextBudgetState(
        usage_ratio=ratio,
        stage=stage,
        budget_is_tight=ratio >= CONFIG.memory.budget_working_ratio,
        emergency=ratio >= CONFIG.memory.budget_emergency_ratio,
    )


def format_openai_tools(raw_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:  # 把本地工具 schema 转成 OpenAI Chat Completions 需要的 tools 格式。
    # 输入 `raw_tools` 的常见结构：  # 说明本函数接收的工具 schema 长什么样。
    # [{"name": "ReadFile", "description": "...", "parameters": {"type": "object", "properties": {...}}}]  # 本地注册表可能返回的扁平 schema。
    # 输出 `tools` 的目标结构：  # 说明 OpenAI 兼容接口期望的结构。
    # [{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}]  # Chat Completions 的 function tool schema。
    tools = []  # 保存转换后的工具 schema 列表，最终会传给 `client.chat.completions.create(tools=...)`。
    for tool in raw_tools:  # 逐个处理注册表返回的原始工具定义。
        # 如果已经是标准格式则不处理，如果不是则进行包装  # 兼容不同注册表实现返回的 schema 形态。
        if "function" in tool:  # 已经包含 `function` 键时，说明该工具大概率已经是 OpenAI 标准格式。
            tools.append(tool)  # 原样加入输出列表，避免重复包装导致 schema 错误。
        else:  # 否则认为它是本地简化格式，需要包装成 OpenAI function tool。
            tools.append({  # 构造单个 OpenAI function tool 描述对象。
                "type": "function",  # OpenAI tools 数组中每个函数工具的固定类型值。
                "function": {  # 函数工具的详细描述体。
                    "name": tool["name"],  # 工具名必须和注册表中的工具名一致，后续模型会用它发起调用。
                    "description": tool.get("description", ""),  # 工具描述用于指导模型何时调用该工具；缺失时给空字符串。
                    "parameters": tool.get("parameters", {"type": "object", "properties": {}}),  # JSON Schema 参数定义；缺失时给一个空对象 schema。
                },  # 结束 `function` 描述体。
            })  # 把包装后的工具 schema 加入 `tools`。
    return tools  # 返回可直接传入 OpenAI 兼容接口的工具 schema 列表。


def pretty_arguments(raw_args: str) -> str:  # 将工具参数 JSON 字符串格式化成适合终端阅读的文本。
    text = raw_args.strip()  # 去掉流式拼接参数两端可能出现的空白字符。
    if not text:  # 如果模型没有给参数，按空 JSON 对象展示。
        return "{}"  # 返回空对象文本，便于终端打印。
    try:  # 尝试按 JSON 解析参数，因为 OpenAI function call 的 arguments 标准上是 JSON 字符串。
        parsed = json.loads(text)  # 把 JSON 字符串转成 Python 对象，通常是 dict。
    except json.JSONDecodeError:  # 如果模型输出了不完整或非法 JSON，就不要在展示层继续处理。
        return text  # 原样返回，保留调试信息，方便判断模型参数生成哪里出错。
    if isinstance(parsed, dict):  # 工具参数正常情况下是对象，例如 `{"file_path": "x", "content": "..."}`。
        return format_argument_mapping(parsed)  # 对 dict 做字段级格式化，让长文本字段多行展示。
    return json.dumps(parsed, ensure_ascii=False, indent=2)  # 非 dict 参数退回通用 JSON 缩进格式，保留中文不转义。


def format_argument_mapping(arguments: dict[str, Any]) -> str:  # 把 dict 形式的工具参数格式化为多行 key/value 文本。
    # 输入示例：{"file_path": "test.py", "content": "print('hi')\n"}  # 说明 WriteFile 参数的真实 Python 结构。
    # 输出示例：'  file_path: "test.py"\\n  content:\\n    print(...)'  # 说明终端中更易读的展示形态。
    if not arguments:  # 如果参数字典为空，直接展示空对象。
        return "{}"  # 保持和 `pretty_arguments` 中空参数的展示一致。

    lines: list[str] = []  # 收集每一行展示文本，最后用换行符拼接。
    for key, value in arguments.items():  # 按模型生成的字段顺序遍历参数；Python 3.7+ dict 会保留插入顺序。
        if should_render_multiline(key, value):  # 判断该字段是否应该按多行文本展示。
            lines.append(f"  {key}:")  # 多行字段先单独打印字段名，下一行开始缩进正文。
            lines.append(indent_multiline_text(truncate_display_string(value)))  # 对长文本先截断，再给每一行加缩进。
        else:  # 短字段或非字符串字段适合单行展示。
            lines.append(f"  {key}: {json.dumps(value, ensure_ascii=False)}")  # 用 JSON 表示字段值，保留字符串引号和布尔/数字等类型信息。
    return "\n".join(lines)  # 把字段展示行合并成一个可打印字符串。


def should_render_multiline(key: str, value: Any) -> bool:  # 判断工具参数字段是否需要以多行块形式展示。
    return (  # 返回一个布尔表达式，三个条件共同决定是否多行显示。
        isinstance(value, str)  # 只有字符串才需要考虑多行缩进；数字、布尔、对象保持 JSON 单行展示。
        and (  # 字段必须是字符串，并且满足下面任一“长文本”条件。
            key in MULTILINE_ARGUMENT_FIELDS  # 命令、文件内容、替换前后文本这类字段即使较短也按多行逻辑处理。
            or "\n" in value  # 字符串内部包含真实换行时，按多行展示可以避免终端显示 `\n` 转义。
            or len(value) > 120  # 很长的单行字符串也拆到独立字段下展示，避免工具调用行过宽。
        )  # 结束“长文本”条件组。
    )  # 返回最终判断结果。


def truncate_display_string(value: str) -> str:  # 限制终端展示的字符串长度，不影响实际传给工具执行的参数。
    if len(value) <= MAX_DISPLAY_STRING_CHARS:  # 如果字符串没有超过配置上限，就完整展示。
        return value  # 返回原字符串；注意这里不修改真正的工具参数。
    remaining = len(value) - MAX_DISPLAY_STRING_CHARS  # 计算被省略的字符数，用于在终端提示用户。
    return value[:MAX_DISPLAY_STRING_CHARS] + f"\n... <truncated {remaining} chars>"  # 展示前缀内容，并追加截断提示。


def indent_multiline_text(value: str, prefix: str = "    ") -> str:  # 给多行字符串的每一行加统一缩进，形成 YAML 风格展示。
    lines = value.splitlines()  # 按真实换行切成多行；默认不会保留末尾空行。
    if value.endswith("\n"):  # 如果原字符串以换行结尾，需要额外补一个空行来表达这个事实。
        lines.append("")  # 加入空字符串，让最终展示保留末尾换行的视觉效果。
    if not lines:  # 如果字符串为空或 split 后没有内容，仍返回一个缩进占位。
        return prefix  # 返回缩进本身，避免字段名后完全没有可见内容。
    return "\n".join(f"{prefix}{line}" for line in lines)  # 给每一行前面加缩进，并重新拼成多行文本。


def parse_tool_arguments(raw_args: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def compact_tool_metadata_value(value: Any, limit: int = MAX_TOOL_INTENT_CHARS) -> str:
    text = " ".join(str(value).split()) if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[:limit]


def tool_call_metadata(tool_name: str, raw_args: str, output: str) -> dict[str, Any]:
    args = parse_tool_arguments(raw_args)
    metadata: dict[str, Any] = {"tool_name": tool_name}
    if args.get("intent"):
        metadata["intent"] = compact_tool_metadata_value(args["intent"])
    for source_key, metadata_key in (
        ("server", "mcp_server"),
        ("tool", "mcp_tool"),
        ("uri", "mcp_resource"),
        ("prompt", "mcp_prompt"),
    ):
        if args.get(source_key):
            metadata.setdefault(metadata_key, compact_tool_metadata_value(args[source_key]))
    try:
        payload = json.loads(output) if output and output.lstrip().startswith("{") else {}
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict):
        for key in (
            "intent",
            "risk",
            "approval",
            "mcp_server",
            "mcp_tool",
            "mcp_resource",
            "mcp_prompt",
            "operation",
            "name",
            "content_type",
            "provider",
            "model",
            "image_count",
            "strategy",
        ):
            if payload.get(key) is not None:
                metadata[key] = compact_tool_metadata_value(payload[key])
    return metadata


async def execute_local_tool(
    registry: ToolRegistry,
    tool_name: str,
    raw_args: str,
    cancel_event: asyncio.Event | None = None,
    execution_recorder: Any | None = None,
    session_id: str = "",
) -> ToolExecution:
    args, error = parse_tool_arguments_object(raw_args)
    if error:
        return ToolExecution(error, is_error=True)
    tool = registry.get(tool_name)
    if tool is None:
        return ToolExecution(f"错误：未知工具 {tool_name}", is_error=True)
    bind_cancel_event = getattr(tool, "bind_cancel_event", None)
    if callable(bind_cancel_event):
        bind_cancel_event(cancel_event)
    try:
        return await execute_tool(
            tool,
            args,
            cancel_event=cancel_event,
            execution_recorder=execution_recorder,
            session_id=session_id,
        )
    finally:
        if callable(bind_cancel_event):
            bind_cancel_event(None)


async def append_project_graph_bootstrap_if_needed(
    messages: list[dict[str, Any]],
    project_graph: Any | None,
    *,
    work_mode: str,
) -> bool:
    if project_graph is None or str(work_mode) != "code":
        return False
    prepare_bootstrap = getattr(project_graph, "prepare_bootstrap", None)
    if not callable(prepare_bootstrap):
        return False
    try:
        update = await prepare_bootstrap(messages)
    except Exception as exc:
        print(f"[项目图谱] Bootstrap 生成失败：{type(exc).__name__}: {exc}", flush=True)
        return False
    if update is None:
        return False
    messages.extend(update.messages)
    render_project_graph_bootstrap_tree(update.payload)
    return True


def _latest_project_graph_bootstrap_hash(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        value = _project_graph_bootstrap_hash(message)
        if value:
            return value
    return ""


def _project_graph_bootstrap_hash(message: dict[str, Any]) -> str:
    metadata = message.get("metadata")
    if isinstance(metadata, dict) and metadata.get("project_graph_bootstrap"):
        return str(metadata.get("navigation_hash") or "")
    payload = _project_graph_payload_from_message(message)
    if payload and payload.get("bootstrap"):
        return str(payload.get("navigation_hash") or "")
    return ""


def _project_graph_payload_from_message(message: dict[str, Any]) -> dict[str, Any]:
    if message.get("role") != "tool":
        return {}
    content = str(message.get("content") or "")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def create_initial_messages(
    registry: ToolRegistry,
    *,
    skill_runtime: Any | None = None,
    capability_router: Any | None = None,
    memory_runtime: MemoryRuntime | None = None,
) -> list[dict[str, Any]]:
    if skill_runtime is None:
        skill_hint = ""
    else:
        fixed_hint = getattr(skill_runtime, "fixed_skill_hint", lambda: "")()
        skill_hint = "\n\n".join(
            part
            for part in (skill_runtime.system_hint(), fixed_hint)
            if part.strip()
        )
    return [
        {
            "role": "system",
            "content": build_system_prompt(
                PromptFeatures(
                    skills_enabled=skill_runtime is not None,
                    mcp_enabled=capability_router is not None,
                    memory_enabled=memory_runtime is not None,
                    project_graph_enabled=registry.get("ProjectArchitecture") is not None,
                ),
                skill_hint=skill_hint,
            ),
        }
    ]


async def ask_model(  # 执行一次用户请求的完整 agent 循环：问模型、执行工具、再问模型，直到停止。
    model_manager: ModelManager,  # 统一推理模型管理器，负责当前 profile 和 provider。
    prompt: str,  # 当前用户输入的自然语言需求。
    registry: ToolRegistry,  # 本地工具注册表，用于根据模型 tool_call 名称找到实际工具对象。
    tools: list[dict[str, Any]],  # 已格式化好的 OpenAI tools schema，每轮请求都要传给模型。
    messages: list[dict[str, Any]],  # 显式初始化的系统消息和历史消息。
    skill_runtime: Any | None = None,  # 可选 SKILL 运行时；存在时每轮动态生成 tools schema。
    core_tool_schemas: list[dict[str, Any]] | None = None,  # 六大核心工具的原始 schema，避免大量 SKILL 全量进入上下文。
    workspace_tracker: Any | None = None,
    memory_runtime: MemoryRuntime | None = None,
    capability_router: Any | None = None,
    project_graph: Any | None = None,
    work_mode: str = "general",
    long_term_memory_runtime: Any | None = None,
    cancel_event: asyncio.Event | None = None,
    follow_up_event: FollowUpSignal | None = None,
    plan_runtime: PlanRuntime | None = None,
    network_access: Any | None = None,
) -> tuple[str, list[dict[str, Any]]]:  # 返回 `(最终模型文本, 更新后的消息历史)`，供 CLI 继续保持上下文。
    # `messages` 在工具调用后的完整结构示例：  # 展示本函数维护的对话历史长什么样。
    # [  # 消息历史是一个有序数组，顺序就是模型看到的上下文顺序。
    #   {"role": "system", "content": "..."},  # 系统消息定义 agent 身份和工具约束。
    #   {"role": "user", "content": "创建 test.py"},  # 用户本轮输入。
    #   {"role": "assistant", "tool_calls": [{"id": "...", "type": "function", "function": {"name": "WriteFile", "arguments": "{...}"}}]},  # 模型请求调用工具。
    #   {"role": "tool", "tool_call_id": "...", "content": "Successfully wrote ..."},  # 本地工具执行结果。
    #   {"role": "assistant", "content": "已完成"}  # 模型最终回答。
    # ]  # 这些消息会被下一轮用户输入继续复用，实现跨轮记忆。
    # A cancelled previous turn may have persisted an assistant tool request
    # without all matching tool results. Remove it before the next API call.
    if remove_trailing_incomplete_tool_call(messages):
        print("已移除上一轮未完成的工具调用，当前会话可以继续。", flush=True)

    session_id = ""
    active_model = model_manager.active_model
    if memory_runtime is not None and CONFIG.memory.enabled:
        session_id = memory_runtime.start_session(active_model)

    def current_context_mode() -> str:
        if memory_runtime is None or not session_id:
            return "raw"
        mode = memory_runtime.context_mode(session_id)
        return str(getattr(mode, "value", mode))

    def save_session_state(*, sync: bool = False) -> None:
        if memory_runtime is None or not session_id:
            return
        if sync:
            memory_runtime.save_messages_now(session_id, messages)
        else:
            memory_runtime.save_messages(session_id, messages)
        memory_runtime.save_lrfu_snapshot(session_id, skill_runtime)
        memory_runtime.save_file_state_snapshot(
            session_id,
            getattr(workspace_tracker, "file_state_cache", None),
        )

    turn_token_usage = TokenUsageSummary()
    session_token_usage: TokenUsageSummary | None = None

    def print_turn_token_summary() -> None:
        nonlocal session_token_usage
        if turn_token_usage.request_count == 0:
            return
        lines: list[str] = []
        if ROUND_TOKEN:
            lines.append(format_token_summary("本轮", turn_token_usage))
        if CONVERSATION_TOKEN and session_token_usage is None and memory_runtime is not None and session_id:
            session_token_usage = memory_runtime.load_token_usage_summary(session_id)
        if CONVERSATION_TOKEN and session_token_usage is not None:
            lines.append(format_token_summary("会话", session_token_usage))
        if lines:
            print_token_block(*lines)

    async def record_long_term_turn_usage(success: bool) -> None:
        if long_term_memory_runtime is None or not session_id:
            return
        await long_term_memory_runtime.record_turn_usage_and_maybe_prompt_skill_promotion(
            session_id=session_id,
            messages=messages,
            turn_start_index=turn_start,
            success=success,
        )

    if await append_project_graph_bootstrap_if_needed(messages, project_graph, work_mode=work_mode):
        save_session_state(sync=True)

    turn_start = len(messages)
    if memory_runtime is not None and CONFIG.memory.enabled:
        memory_runtime.begin_workspace_checkpoint(prompt=prompt, message_index=turn_start)

    # 追加当前用户问题  # 每次调用 `ask_model` 都代表用户发来一条新消息。
    messages.append({"role": "user", "content": prompt})  # 把用户输入追加进历史，让模型能看到本轮需求。
    try:
        if plan_runtime is not None and plan_runtime.should_load_plan_skill():
            await _append_plan_skill_for_current_query(
                messages,
                prompt=prompt,
                registry=registry,
                plan_runtime=plan_runtime,
            )
    except Exception:
        del messages[turn_start:]
        raise
    save_session_state()
    temporary_system_messages: list[dict[str, Any]] = []
    if capability_router is not None:
        print("[Runtime] 正在解析动态能力...", flush=True)
        capability_result = await capability_router.route(prompt)
        print("[Runtime] 动态能力解析完成。", flush=True)
    else:
        capability_result = None
    long_term_context = None
    if long_term_memory_runtime is not None and session_id:
        print("[Runtime] 正在查询长期记忆...", flush=True)
        long_term_context = await long_term_memory_runtime.retrieve_for_turn(
            current_query=prompt,
            recent_messages=messages[:turn_start],
        )
        print("[Runtime] 长期记忆查询完成。", flush=True)
    initial_budget_state = None
    if memory_runtime is not None and session_id:
        initial_hot_snapshot = memory_runtime.hot_context_budget_snapshot(
            session_id=session_id,
            messages=messages,
            current_turn_start=turn_start,
        )
        if initial_hot_snapshot.warning:
            initial_budget_state = context_budget_state_from_hot_snapshot(initial_hot_snapshot)
    tool_policy = TurnToolPolicy(
        interaction_mode=plan_runtime.mode if plan_runtime is not None else InteractionMode.NORMAL,
        has_active_plan=plan_runtime.active_plan() is not None if plan_runtime is not None else False,
    )
    base_runtime_context = RuntimeContextBuilder(
        workspace_tracker=workspace_tracker,
        context_mode=current_context_mode(),
        work_mode=work_mode,
        capabilities=capability_result,
        project_graph=project_graph,
        long_term_memory=long_term_context.to_runtime_payload() if long_term_context is not None else None,
        context_budget=initial_budget_state,
        interaction_mode=plan_runtime.mode.value if plan_runtime is not None else InteractionMode.NORMAL.value,
        tool_policy=tool_policy.runtime_payload() if plan_runtime is not None else None,
        plan=_plan_runtime_context(plan_runtime),
        network_routing={
            "policy": network_access.runtime_payload() if network_access is not None else None,
            "ResearchWeb": "由隔离子智能体完成文本网页研究，返回带来源 URL 的总结",
            "FetchUrl": "读取已知 URL 的静态文本网页；动态页面和图片使用 browser_* 工具",
            "Playwright browser_* tools": "处理 JavaScript、页面交互、截图和本地 UI 验证",
            "Workspace UI": "Bash 与 browser_* 共享会话级工作区网络。项目服务必须监听 0.0.0.0；browser_navigate 可以使用 http://localhost:<port>，Runtime 会映射到本会话工作区容器。",
        },
    ).build()
    round_messages = list(messages)
    current_tools = await build_round_tools(tools, core_tool_schemas)  # 本轮工具列表在整轮内保持稳定，利于 prompt 缓存命中。
    failure_tracker = RepeatedFailureTracker()
    code_query_ledger = CodeQueryLedger()
    frozen_rendered_prompt: RenderedPrompt | None = None
    round_budget = ToolRoundBudget(
        MAX_TOOL_ROUNDS,
        renewable=tool_policy.has_active_plan,
    )

    while round_budget.consume():  # 无计划时是固定上限；活动计划提交真实进度后可恢复完整预算。
        prepared_messages = round_messages
        summary_text = ""
        if memory_runtime is not None and session_id:
            if should_generate_summary(memory_runtime, round_messages, current_tools, prompt):
                summary_text = await summarize_engineering_state(
                    model_manager.active_provider(),
                    round_messages,
                )
            prepared_messages = memory_runtime.prepare_messages_for_model(
                session_id=session_id,
                messages=round_messages,
                tools=current_tools,
                current_prompt=prompt,
                summary_text=summary_text,
                persist_snapshot=True,
                current_turn_start=turn_start,
                project_graph=project_graph if str(work_mode) == "code" else None,
            )
        if frozen_rendered_prompt is None:
            runtime_context = replace(
                base_runtime_context,
                context_render_mode=current_context_mode(),
                task_snapshot=summary_text or None,
            )
            rendered_prompt = PromptRenderer.render_current_user_message(runtime_context, prompt)
        else:
            rendered_prompt = frozen_rendered_prompt
        model_messages = render_current_turn_for_model(
            prepared_messages,
            current_turn_start=turn_start,
            rendered_prompt=rendered_prompt,
        )
        if frozen_rendered_prompt is None:
            frozen_rendered_prompt = rendered_prompt
            if freeze_model_visible_user_message(
                round_messages,
                current_turn_start=turn_start,
                content=rendered_prompt.content,
            ):
                save_session_state()
        prompt_debug_snapshot = build_prompt_debug_snapshot(
            model_messages=model_messages,
            temporary_system_messages=temporary_system_messages,
            tools=current_tools,
            rendered_prompt=rendered_prompt,
        )
        print_prompt_debug_with_previous(prompt_debug_snapshot)
        stream_kwargs = {"cancel_event": cancel_event} if cancel_event is not None else {}
        bash_classifier = bash_display_classifier_from_registry(registry)
        if bash_classifier is not None:
            stream_kwargs["bash_classifier"] = bash_classifier
        provider = model_manager.active_provider()
        active_model = provider.model
        stream_sink = create_assistant_stream("模型")
        stream_result = normalize_stream_result(
            await provider.stream_chat(
                ChatRequest(
                    messages=model_messages,
                    tools=current_tools,
                    stream_sink=stream_sink,
                    **stream_kwargs,
                )
            )
        )
        assistant_text = stream_result.text
        tool_calls = stream_result.tool_calls
        usage = stream_result.usage
        if usage:
            usage_values = api_usage_to_dict(usage)
            add_usage_to_summary(turn_token_usage, usage_values)
            if memory_runtime is not None and session_id:
                session_token_usage = memory_runtime.record_token_usage(
                    session_id=session_id,
                    model=active_model,
                    prompt_hash=prompt_debug_snapshot.request_hash,
                    tools_hash=prompt_debug_snapshot.tools_hash,
                    metadata={
                        "message_count": prompt_debug_snapshot.message_count,
                        "tool_count": prompt_debug_snapshot.tool_count,
                        "estimated_request_tokens": prompt_debug_snapshot.request_tokens,
                        "fixed_system_tokens": prompt_debug_snapshot.fixed_system_tokens,
                        "temporary_system_tokens": prompt_debug_snapshot.temporary_system_tokens,
                        "historical_messages_tokens": prompt_debug_snapshot.historical_messages_tokens,
                        "current_turn_tokens": prompt_debug_snapshot.current_turn_tokens,
                        "runtime_context_tokens": prompt_debug_snapshot.runtime_context_tokens,
                        "rendered_prompt_tokens": prompt_debug_snapshot.rendered_prompt_tokens,
                        "stored_user_prompt_tokens": prompt_debug_snapshot.stored_user_prompt_tokens,
                        "runtime_context_hash": prompt_debug_snapshot.runtime_context_hash,
                        "rendered_prompt_hash": prompt_debug_snapshot.rendered_prompt_hash,
                        "rendered_prompt_format_version": prompt_debug_snapshot.rendered_prompt_format_version,
                        "tools_tokens": prompt_debug_snapshot.tools_tokens,
                    },
                    **usage_values,
                )
            parts = [f"输入 {usage_values['prompt_tokens']}"]
            if usage_values["prompt_cache_hit_tokens"] or usage_values["prompt_cache_miss_tokens"]:
                parts.append(
                    f"(缓存命中 {usage_values['prompt_cache_hit_tokens']}, "
                    f"未命中 {usage_values['prompt_cache_miss_tokens']})"
                )
            parts.append(f"| 输出 {usage_values['completion_tokens']} | 总计 {usage_values['total_tokens']}")
            if STEP_TOKEN:
                print_token_block(f"[Token] {' '.join(parts)}")
        if stream_result.interrupted:
            interruption_text = "本轮已被用户中断。已完成的工具结果已保留，可以继续对话。"
            if assistant_text:
                interruption_text = f"{assistant_text}\n\n{interruption_text}"
            interrupted_message = {
                "role": "assistant",
                "content": interruption_text,
                "metadata": {"interrupted": True},
            }
            messages.append(interrupted_message)
            round_messages.append(interrupted_message)
            save_session_state(sync=True)
            print_turn_token_summary()
            await record_long_term_turn_usage(False)
            render_assistant_text(
                "本轮已被用户中断。已完成的工具结果已保留，可以继续对话。"
            )
            return interruption_text, messages
        if assistant_text.startswith("Error: API ") and not tool_calls:
            # `turn_start` 指向用户消息追加之前的位置。本轮如果已经执行过工具，
            # 这些工具结果是真实的工作进展，不能因为一次 API 失败被整体丢弃。
            has_progress = len(messages) > turn_start + 1
            if has_progress:
                messages.append(
                    {
                        "role": "assistant",
                        "content": (
                            f"{assistant_text}\n\n"
                            "本轮已完成的工具调用结果已保留在上下文中。可以直接说“继续”接着未完成的部分，"
                            "不需要从头重来。"
                        ),
                    }
                )
            else:
                del messages[turn_start:]  # 本轮除用户消息外没有任何进展，回滚到干净状态。
            save_session_state(sync=True)
            print_turn_token_summary()
            await record_long_term_turn_usage(False)
            return assistant_text, messages

        mixed_plan_call = any(call.tool_name == "create_plan" for call in tool_calls) and len(tool_calls) != 1
        assistant_message: dict[str, Any] = {"role": "assistant"}  # 准备写入历史的 assistant 消息骨架。
        if assistant_text or not tool_calls:  # 有文本时保存文本；没有工具调用时即使文本为空也需要 content 字段表示最终回答。
            assistant_message["content"] = assistant_text  # 写入模型本轮普通文本输出。
        if tool_calls:  # 如果模型请求调用工具，需要把 tool_calls 原样写回历史，满足 OpenAI 消息协议。
            assistant_message["tool_calls"] = [  # tool_calls 是 assistant 消息里的数组字段。
                {  # 单个工具调用对象。
                    "id": tool_call.tool_id or f"tool_call_{index}",  # 使用模型返回的 ID；缺失时生成稳定兜底 ID。
                    "type": "function",  # OpenAI function call 的固定类型。
                    "function": {  # 函数调用详情。
                        "name": tool_call.tool_name,  # 被调用的本地工具名。
                        "arguments": tool_call.arguments,  # 原始 JSON 参数字符串，必须保持字符串形态写入消息历史。
                    },  # 结束 function 调用详情。
                }  # 结束单个工具调用对象。
                for index, tool_call in enumerate(tool_calls)  # 按已排序的工具调用列表生成 OpenAI 协议结构。
            ]  # 结束 assistant_message["tool_calls"] 数组。
        persistent_assistant_message = None
        if tool_calls:
            persistent_assistant_message = persistent_assistant_tool_message(assistant_message)
        else:
            persistent_assistant_message = assistant_message
        if persistent_assistant_message is not None:
            messages.append(persistent_assistant_message)  # 把可长期保存的模型输出加入历史。
        round_messages.append(assistant_message)
        if persistent_assistant_message is not None:
            save_session_state(sync=not tool_calls)

        if not tool_calls:  # 如果模型没有请求工具，说明本轮任务已经完成。
            print_turn_token_summary()
            await record_long_term_turn_usage(True)
            return assistant_text, messages  # 返回最终文本和完整消息历史给调用方。

        follow_up_after_tool = False
        created_plan_id = ""
        plan_progress_submitted = False
        for index, tool_call in enumerate(tool_calls):  # 逐个执行模型请求的本地工具调用。
            tool_call_id = tool_call.tool_id or f"tool_call_{index}"  # 计算工具调用 ID，必须和上面的 assistant tool_calls 对象一致。
            registry_get = getattr(registry, "get", None)
            selected_tool = registry_get(tool_call.tool_name) if callable(registry_get) else None
            is_mutation = selected_tool is not None and selected_tool.category == "write"
            blocked = failure_tracker.preflight(
                tool_call.tool_name,
                tool_call.arguments,
                is_mutation=is_mutation,
            )
            if blocked is None:
                blocked = code_query_ledger.preflight(tool_call.tool_name, tool_call.arguments)
            if follow_up_after_tool:
                execution = ToolExecution("收到新的排队消息，本工具调用未执行。", is_error=True)
            elif mixed_plan_call:
                execution = ToolExecution("create_plan 必须是本轮唯一的工具调用，请单独提交计划。", is_error=True)
            elif plan_runtime is not None and (selected_tool is None or not tool_policy.allows(selected_tool)):
                execution = ToolExecution(
                    f"当前交互模式不允许调用工具 {tool_call.tool_name}。",
                    is_error=True,
                )
            elif blocked is not None:
                execution = blocked
            elif cancel_event is not None and cancel_event.is_set():
                execution = ToolExecution("因用户中断，本工具调用未执行。", is_error=True)
            else:
                execution_kwargs = (
                    {"cancel_event": cancel_event} if cancel_event is not None else {}
                )
                if memory_runtime is not None and hasattr(memory_runtime, "start_execution_record"):
                    execution_kwargs.update(
                        {"execution_recorder": memory_runtime, "session_id": session_id}
                    )
                skill_related_tool = is_skill_related_tool(tool_call.tool_name)
                status_enabled = (
                    selected_tool is not None
                    and selected_tool.is_read_only
                    and not skill_related_tool
                )
                async with processing_status(
                    tool_status_message(tool_call.tool_name),
                    enabled=status_enabled,
                ):
                    execution = await execute_local_tool(
                        registry,
                        tool_call.tool_name,
                        tool_call.arguments,
                        **execution_kwargs,
                    )
            code_query_ledger.record(tool_call.tool_name, tool_call.arguments, execution)
            execution = failure_tracker.annotate(
                tool_call.tool_name,
                tool_call.arguments,
                execution,
                is_mutation=is_mutation,
            )
            tool_output, tool_failed = execution.output, execution.is_error
            raw_tool_output = tool_output
            output_id = ""
            skill_related_tool = is_skill_related_tool(tool_call.tool_name)
            metadata = tool_call_metadata(tool_call.tool_name, tool_call.arguments, tool_output)
            metadata["is_error"] = tool_failed  # 冷历史只保留 metadata，失败状态必须随之保留，否则模型无法判断历史调用成败。
            if memory_runtime is not None and session_id and not skill_related_tool:
                output_id = memory_runtime.save_tool_output(
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_call.tool_name,
                    arguments=tool_call.arguments,
                    output=tool_output,
                    metadata=metadata,
                )
            if tool_call.tool_name in {"create_plan", "update_plan_step"}:
                tool_output = truncate_tool_output(tool_output)
            elif skill_related_tool or tool_call.tool_name == "BatchRecoverContext":
                tool_output = truncate_tool_output(tool_output)
            elif memory_runtime is not None and output_id:
                tool_output = memory_runtime.tool_output_prompt_content(
                    output_id=output_id,
                    output=tool_output,
                    messages=round_messages,
                    tools=current_tools,
                    current_prompt=prompt,
                )
            else:
                tool_output = truncate_tool_output(tool_output)
            tool_message = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": tool_output,
            }
            if output_id:
                tool_message["metadata"] = {"output_id": output_id, **metadata}
            if skill_related_tool:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": "[Skill output omitted after current turn]",
                        "metadata": {**metadata, "skill_omitted": True},
                    }
                )
            else:
                messages.append(tool_message)  # 把工具执行结果追加为 role=tool 消息，供模型下一轮读取。
            round_messages.append(tool_message)
            save_session_state()
            if tool_call.tool_name == "create_plan" and not tool_failed:
                try:
                    created_plan_id = str(json.loads(raw_tool_output).get("plan_id") or "")
                except (json.JSONDecodeError, AttributeError):
                    created_plan_id = ""
            if tool_call.tool_name == "update_plan_step" and not tool_failed:
                plan_progress_submitted = True
            if follow_up_event is not None and follow_up_event.is_set():
                follow_up_after_tool = True
        if plan_progress_submitted:
            round_budget.renew_after_plan_progress()
        if created_plan_id and plan_runtime is not None:
            if follow_up_event is not None and follow_up_event.is_set():
                plan_runtime.reject_proposal(created_plan_id, superseded=True)
                _set_plan_tool_decision(messages, created_plan_id, "superseded")
                _set_plan_tool_decision(round_messages, created_plan_id, "superseded")
                follow_up_after_tool = True
            else:
                selection = await _request_plan_decision(plan_runtime, created_plan_id)
                decision = ("implement", "clear_and_implement", "rejected")[selection]
                _set_plan_tool_decision(messages, created_plan_id, decision)
                _set_plan_tool_decision(round_messages, created_plan_id, decision)
                usage_recorded = False
                if selection in {0, 1}:
                    plan_runtime.activate_proposal(created_plan_id)
                    if selection == 1:
                        await record_long_term_turn_usage(True)
                        usage_recorded = True
                        await _rewrite_context_for_plan_execution(
                            messages,
                            turn_start=turn_start,
                            project_graph=project_graph,
                            work_mode=work_mode,
                        )
                    plan_runtime.queue_implementation_prompt()
                else:
                    plan_runtime.reject_proposal(created_plan_id)
                save_session_state(sync=True)
                print_turn_token_summary()
                if not usage_recorded:
                    await record_long_term_turn_usage(True)
                return "计划已提交，等待后续处理。", messages
        if follow_up_after_tool and not (cancel_event is not None and cancel_event.is_set()):
            interruption_text = "当前任务已在工具调用结束后暂停，接下来处理排队消息。"
            interrupted_message = {
                "role": "assistant",
                "content": interruption_text,
                "metadata": {"interrupted": True, "queued_follow_up": True},
            }
            messages.append(interrupted_message)
            round_messages.append(interrupted_message)
            save_session_state(sync=True)
            print_turn_token_summary()
            await record_long_term_turn_usage(False)
            render_assistant_text(interruption_text)
            return interruption_text, messages
        if cancel_event is not None and cancel_event.is_set():
            interruption_text = "本轮已被用户中断。已完成的工具结果已保留，可以继续对话。"
            interrupted_message = {
                "role": "assistant",
                "content": interruption_text,
                "metadata": {"interrupted": True},
            }
            messages.append(interrupted_message)
            round_messages.append(interrupted_message)
            save_session_state(sync=True)
            print_turn_token_summary()
            await record_long_term_turn_usage(False)
            render_assistant_text(interruption_text)
            return interruption_text, messages

    print_turn_token_summary()
    await record_long_term_turn_usage(False)
    return f"Error: exceeded max tool rounds ({MAX_TOOL_ROUNDS})", messages  # 超过工具循环上限时返回错误，避免无限运行。


async def _request_plan_decision(plan_runtime: PlanRuntime, plan_id: str) -> int:
    plan = plan_runtime.proposed_plan()
    if plan is None or plan.id != plan_id:
        raise ValueError("待审批计划不存在")
    preview = "\n".join(
        [
            "Plan",
            f"目标：{plan.objective}",
            "",
            *(f"{index}. {step.text}" for index, step in enumerate(plan.steps, start=1)),
        ]
    )
    markdown = "\n".join(
        [
            "## 实施计划",
            "",
            f"**目标：** {plan.objective}",
            "",
            *(f"{index}. {step.text}" for index, step in enumerate(plan.steps, start=1)),
        ]
    )
    selected = await request_plan_selection(
        preview,
        ["按照计划实施", "清空上下文并按照计划实施", "不实施并补充信息"],
    )
    render_assistant_markdown(markdown, label="Plan")
    return selected if selected in {0, 1, 2} else 2


async def resume_pending_plan_decision(
    messages: list[dict[str, Any]],
    *,
    plan_runtime: PlanRuntime,
    project_graph: Any | None,
    work_mode: str,
) -> list[dict[str, Any]]:
    plan = plan_runtime.proposed_plan()
    if plan is None:
        return messages
    selection = await _request_plan_decision(plan_runtime, plan.id)
    decision = ("implement", "clear_and_implement", "rejected")[selection]
    _set_plan_tool_decision(messages, plan.id, decision)
    if selection in {0, 1}:
        plan_runtime.activate_proposal(plan.id)
        if selection == 1:
            await _rewrite_context_for_plan_execution(
                messages,
                turn_start=_plan_turn_start(messages, plan.id),
                project_graph=project_graph,
                work_mode=work_mode,
            )
        plan_runtime.queue_implementation_prompt()
    else:
        plan_runtime.reject_proposal(plan.id)
    return messages


def _plan_turn_start(messages: list[dict[str, Any]], plan_id: str) -> int:
    tool_index = -1
    for index, message in enumerate(messages):
        if message.get("role") != "tool":
            continue
        try:
            payload = json.loads(str(message.get("content") or ""))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("plan_id") == plan_id:
            tool_index = index
            break
    if tool_index < 0:
        raise ValueError("会话中缺少待审批计划的工具结果")
    for index in range(tool_index, -1, -1):
        if messages[index].get("role") == "user":
            return index
    raise ValueError("会话中缺少待审批计划对应的用户请求")


def _plan_runtime_context(plan_runtime: PlanRuntime | None) -> dict[str, Any] | None:
    if plan_runtime is None:
        return None
    if plan_runtime.is_planning:
        proposal = plan_runtime.proposed_plan()
        return {
            "status": "planning",
            "proposal": (
                {
                    "id": proposal.id,
                    "objective": proposal.objective,
                    "status": proposal.status.value,
                    "steps": [{"id": step.id, "text": step.text} for step in proposal.steps],
                }
                if proposal is not None
                else None
            ),
        }
    payload = plan_runtime.context_payload()
    if payload is None:
        return None
    return {
        "status": "active",
        "active": payload,
    }


async def _append_plan_skill_for_current_query(
    messages: list[dict[str, Any]],
    *,
    prompt: str,
    registry: ToolRegistry,
    plan_runtime: PlanRuntime,
) -> None:
    invoke_skill = registry.get("invoke_skill")
    if invoke_skill is None:
        raise RuntimeError("Plan 模式需要 invoke_skill 工具")
    arguments = {
        "skill_name": "skill_code_plan",
        "instruction": prompt,
        "context": "用户已进入 Plan 模式；对当前请求进行只读调查并形成待审批实施计划。",
    }
    result = await invoke_skill.execute(invoke_skill.params_model(**arguments))
    if result.is_error:
        raise RuntimeError(f"加载 Plan Skill 失败：{result.output}")
    call_id = f"plan_skill_{uuid4().hex}"
    intent = "用户已进入 Plan 模式；加载 code-plan 工作流以规划当前请求。"
    metadata = {
        "tool_name": "invoke_skill",
        "intent": intent,
        "plan_skill_bootstrap": True,
        "skill_name": "skill_code_plan",
    }
    messages.extend(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "invoke_skill",
                            "arguments": json.dumps(
                                {**arguments, "intent": intent},
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        },
                    }
                ],
                "metadata": metadata,
            },
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": result.output,
                "metadata": metadata,
            },
        ]
    )
    plan_runtime.mark_plan_skill_loaded()


def _set_plan_tool_decision(
    messages: list[dict[str, Any]],
    plan_id: str,
    decision: str,
) -> None:
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        try:
            payload = json.loads(str(message.get("content") or ""))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or payload.get("plan_id") != plan_id:
            continue
        payload["status"] = "activated" if decision in {"implement", "clear_and_implement"} else decision
        payload["decision"] = decision
        message["content"] = json.dumps(payload, ensure_ascii=False)
        metadata = message.setdefault("metadata", {})
        metadata["plan_decision"] = decision
        return


async def _rewrite_context_for_plan_execution(
    messages: list[dict[str, Any]],
    *,
    turn_start: int,
    project_graph: Any | None,
    work_mode: str,
) -> None:
    system = next((message for message in messages if message.get("role") == "system"), None)
    turn_messages = messages[turn_start:]
    user = next((message for message in turn_messages if message.get("role") == "user"), None)
    assistant = None
    create_plan_call_id = ""
    for message in turn_messages:
        if message.get("role") != "assistant":
            continue
        for tool_call in message.get("tool_calls", []):
            function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            if function.get("name") == "create_plan":
                assistant = message
                create_plan_call_id = str(tool_call.get("id") or "")
                break
        if assistant is not None:
            break
    tool = next(
        (
            message
            for message in turn_messages
            if message.get("role") == "tool"
            and str(message.get("tool_call_id") or "") == create_plan_call_id
        ),
        None,
    )
    if system is None or user is None or assistant is None or tool is None:
        raise ValueError("无法构造计划执行所需的完整消息链")
    rebuilt = [system, user]
    if project_graph is not None and str(work_mode) == "code":
        update = await project_graph.prepare_bootstrap(rebuilt, force=True)
        if update is not None:
            rebuilt.extend(update.messages)
    rebuilt.extend([assistant, tool])
    messages[:] = rebuilt


def should_generate_summary(
    memory_runtime: MemoryRuntime,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    prompt: str,
) -> bool:
    if CONFIG.memory.prompt_path is None:
        return False
    snapshot = memory_runtime.prompt_budget_snapshot(
        messages,
        tools=tools,
        current_prompt=prompt,
    )
    return snapshot.usage_ratio >= CONFIG.memory.budget_emergency_ratio


async def summarize_engineering_state(
    provider: Any,
    messages: list[dict[str, Any]],
) -> str:
    prompt_path = CONFIG.memory.prompt_path
    if prompt_path is None:
        summary_prompt = "Summarize the current engineering state in a concise structured form."
    else:
        try:
            summary_prompt = prompt_path.read_text(encoding="utf-8")
        except OSError:
            summary_prompt = "Summarize the current engineering state in a concise structured form."
    summary_messages = [
        {
            "role": "system",
            "content": summary_prompt,
        },
        {
            "role": "user",
            "content": json.dumps(messages, ensure_ascii=False, default=str),
        },
    ]
    try:
        result = await provider.stream_chat(
            ChatRequest(messages=summary_messages, display=False, output_label="summary")
        )
    except Exception as exc:
        return f"UNKNOWN\nSUMMARY_ERROR: {exc}"
    return result.text or "UNKNOWN"


def truncate_tool_output(output: str) -> str:
    if len(output) <= MAX_TOOL_OUTPUT_CHARS:
        return output
    remaining = len(output) - MAX_TOOL_OUTPUT_CHARS
    return output[:MAX_TOOL_OUTPUT_CHARS] + f"\n... <tool output truncated {remaining} chars>"


async def build_round_tools(
    default_tools: list[dict[str, Any]],
    core_tool_schemas: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:  # 本轮 tool schema 固定为核心工具；Skill 通过 invoke_skill 单入口调用，不再逐个动态注册。
    if core_tool_schemas is None:
        return default_tools
    return format_openai_tools(core_tool_schemas)


async def main() -> None:  # 提供一个直接运行 `client.py` 时使用的测试入口。
    prompt = (  # 准备一条固定测试 prompt，用于验证 agent 能读取目录并写 README。
        "读取目录下全部文件内容，并用中文总结这个项目，最后写入README.md文件中。"  # 测试需求文本。
    )  # 结束 prompt 字符串。

    from mycodingagent.tool_runtime.command_policy import BashPolicyEvaluator, BashPolicyStore

    registry = create_default_registry(
        bash_policy_evaluator=BashPolicyEvaluator(BashPolicyStore(CONFIG.memory.db_path))
    )  # 创建默认工具注册表，包含文件读写、搜索和 Docker Bash。
    raw_tools = registry.get_all_schemas("openai")  # 从注册表拿到 OpenAI 协议方向的原始工具 schema。
    tools = format_openai_tools(raw_tools)  # 确保工具 schema 满足 Chat Completions 的 tools 参数格式。

    model_manager = ModelManager()

    print(f"提问：{prompt}", flush=True)  # 在终端显示测试 prompt。
    messages = create_initial_messages(registry)
    result, messages = await ask_model(model_manager, prompt, registry, tools, messages)  # 执行完整 agent 循环，得到最终回答和历史消息。
    print(f"结果：{result}", flush=True)  # 打印模型最终回答。

    await model_manager.close()  # 关闭异步 HTTP 客户端连接，释放网络资源。


if __name__ == "__main__":  # 只有直接运行本文件时才执行测试入口，被其他模块 import 时不会运行。
    asyncio.run(main())  # 启动事件循环并运行异步 main。
