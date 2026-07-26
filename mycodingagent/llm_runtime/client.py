from __future__ import annotations  # 允许在类型注解中使用尚未定义的类型，并启用较新的注解解析行为。

import asyncio  # 提供异步事件循环、异步子进程等待等能力，本文件用它运行 async 主流程。
import hashlib  # 为 PromptDebug 生成稳定短哈希，避免打印原始 prompt 内容。
import json  # 负责解析模型生成的工具参数 JSON，以及把参数格式化成终端可读文本。
import os  # 读取环境变量、清理代理环境变量，保证 API 客户端和本地工具按预期运行。
from dataclasses import dataclass, replace  # 用轻量数据类保存流式返回过程中尚未拼完整的工具调用。

for env_key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:  # 遍历常见代理变量名，避免外部代理影响 DeepSeek/OpenAI 兼容接口连接。
    os.environ.pop(env_key, None)  # 从当前进程环境中删除代理变量；不存在时返回 None，不抛异常。

from typing import Any  # `Any` 用在 OpenAI 消息、工具 schema 等动态 JSON 结构的类型标注中。

from openai import AsyncOpenAI  # OpenAI Python SDK 的异步客户端；这里连接 DeepSeek 的 OpenAI 兼容接口。
from openai import APIConnectionError, APIError, APITimeoutError

from mycodingagent.configuration import CONFIG  # 统一读取 API、模型和客户端展示相关配置。
from mycodingagent.memory import MemoryRuntime, TokenUsageRecord, TokenUsageSummary
from mycodingagent.memory.budget import estimate_tokens
from mycodingagent.memory.message_filters import is_skill_related_tool, persistent_assistant_tool_message
from mycodingagent.llm_runtime.context import (
    ContextBudgetState,
    PromptRenderer,
    RenderedPrompt,
    RuntimeContextBuilder,
    render_current_turn_for_model,
)
from mycodingagent.tool_runtime import ToolRegistry, create_default_registry  # 导入本地工具注册表类型，以及创建默认读写/搜索/Bash 工具的方法。

DEEPSEEK_API_KEY = CONFIG.api.deepseek_api_key  # DeepSeek API Key；优先从 DEEPSEEK_API_KEY 环境变量读取。
BASE_URL = CONFIG.api.base_url  # API 基础地址；未配置时使用 DeepSeek 官方兼容地址。
MODEL = CONFIG.api.model  # 模型名称；允许通过环境变量切换模型而不用改代码。
MAX_TOOL_ROUNDS = CONFIG.client.max_tool_rounds  # 单次用户请求最多允许模型连续调用工具的轮数，用于防止无限循环。
MAX_DISPLAY_STRING_CHARS = CONFIG.client.max_display_string_chars  # 终端展示超长字符串参数时的最大字符数，避免 WriteFile 内容刷屏。
MAX_TOOL_OUTPUT_CHARS = CONFIG.client.max_tool_output_chars
MULTILINE_ARGUMENT_FIELDS = CONFIG.client.multiline_argument_fields  # 这些字段通常包含代码、命令或长文本，打印工具调用时优先按多行展示。
DEBUG = CONFIG.client.debug
STEP_TOKEN = CONFIG.client.step_token
ROUND_TOKEN = CONFIG.client.round_token
CONVERSATION_TOKEN = CONFIG.client.conversation_token


@dataclass  # 自动生成 `__init__` 等方法，让该类只承担“保存状态”的职责。
class PendingToolCall:  # 保存一个流式工具调用在拼接完成前的中间状态。
    tool_id: str = ""  # OpenAI 返回的工具调用 ID；后续 tool 消息必须用它和 assistant tool_call 对齐。
    tool_name: str = ""  # 工具函数名，例如 `ReadFile`、`WriteFile`、`Bash`。
    arguments: str = ""  # 工具参数的 JSON 字符串；流式返回时会被分片追加到这里。


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
        f"messages={snapshot.message_count} first_changed_section={first_changed_section}",
    )


def print_prompt_debug_with_previous(snapshot: PromptDebugSnapshot) -> None:
    global _LAST_PROMPT_DEBUG_SNAPSHOT
    first_changed_section = first_changed_prompt_debug_section(_LAST_PROMPT_DEBUG_SNAPSHOT, snapshot)
    print_prompt_debug(snapshot=snapshot, first_changed_section=first_changed_section)
    _LAST_PROMPT_DEBUG_SNAPSHOT = snapshot


def print_token_block(*lines: str) -> None:
    print("=================", flush=True)
    for line in lines:
        print(line, flush=True)
    print("=================", flush=True)


def context_budget_state_from_snapshot(snapshot: Any) -> ContextBudgetState:
    return ContextBudgetState(
        usage_ratio=float(getattr(snapshot, "usage_ratio", 0.0) or 0.0),
        stage=str(getattr(getattr(snapshot, "stage", ""), "value", getattr(snapshot, "stage", ""))),
        budget_is_tight=float(getattr(snapshot, "usage_ratio", 0.0) or 0.0) >= CONFIG.memory.budget_working_ratio,
        emergency=float(getattr(snapshot, "usage_ratio", 0.0) or 0.0) >= CONFIG.memory.budget_emergency_ratio,
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


def skill_tool_notice(tool_name: str, args: dict[str, Any], skill_runtime: Any | None = None) -> str:  # 为 SKILL 相关工具调用生成终端可见的简短提示。
    notice_tool_name = str(args.get("skill_name") or "") if tool_name == "invoke_skill" else tool_name
    record = get_skill_record_for_notice(skill_runtime, notice_tool_name)
    if record is not None:
        lines = [f"[SKILL] 调用：{record.tool_name} ({record.name})"]
        description = compact_notice_value(record.description, limit=160)
        if description:
            lines.append(f"  描述：{description}")
        instruction = compact_notice_value(args.get("instruction"), limit=160)
        if instruction:
            lines.append(f"  instruction：{instruction}")
        return "\n".join(lines)

    if tool_name == "search_tool":  # search_tool 是按能力检索 SKILL 的管理工具。
        query = compact_notice_value(args.get("query"))
        return f"[SKILL] 检索: {query}" if query else "[SKILL] 检索"
    if tool_name == "Get_all_tool":  # Get_all_tool 会列出当前可用的全部 SKILL。
        return "[SKILL] 列出全部可用 skill"
    if tool_name == "Get_tool_by_name":  # Get_tool_by_name 会按名称激活并返回某个 SKILL schema。
        requested_name = compact_notice_value(args.get("tool_name"))
        return f"[SKILL] 获取工具定义: {requested_name}" if requested_name else "[SKILL] 获取工具定义"
    if tool_name == "invoke_skill":
        requested_name = compact_notice_value(args.get("skill_name"))
        instruction = compact_notice_value(args.get("instruction"))
        if requested_name and instruction:
            return f"[SKILL] 调用: {requested_name} instruction={instruction}"
        return f"[SKILL] 调用: {requested_name}" if requested_name else "[SKILL] 调用"
    if tool_name == "search_skill_references":
        query = compact_notice_value(args.get("query"))
        skill_name = compact_notice_value(args.get("skill_name"))
        target = f" skill={skill_name}" if skill_name else ""
        return f"[SKILL] 检索 references: {query}{target}" if query else f"[SKILL] 检索 references{target}"
    if tool_name == "Get_skill_reference":
        skill_name = compact_notice_value(args.get("skill_name"))
        reference_path = compact_notice_value(args.get("reference_path"))
        if skill_name and reference_path:
            return f"[SKILL] 读取 reference: {skill_name} {reference_path}"
        return "[SKILL] 读取 reference"
    if tool_name.startswith("skill_"):  # 真正的 SKILL 工具名统一以 skill_ 开头。
        instruction = compact_notice_value(args.get("instruction"))
        return f"[SKILL] 调用: {tool_name} instruction={instruction}" if instruction else f"[SKILL] 调用: {tool_name}"
    return ""


def get_skill_record_for_notice(skill_runtime: Any | None, tool_name: str) -> Any | None:
    if skill_runtime is None:
        return None
    get_record = getattr(skill_runtime, "get_record", None)
    if not callable(get_record):
        return None
    try:
        return get_record(tool_name)
    except Exception:
        return None


def compact_notice_value(value: Any, limit: int = 120) -> str:  # 把参数压缩成单行摘要，避免终端刷出大段上下文。
    if value is None:
        return ""
    if isinstance(value, str):
        text = " ".join(value.split())
    else:
        text = json.dumps(value, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + f"... <truncated {len(text) - limit} chars>"


def parse_tool_arguments(raw_args: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def compact_tool_metadata_value(value: Any, limit: int = 160) -> str:
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
        ):
            if payload.get(key) is not None:
                metadata[key] = compact_tool_metadata_value(payload[key])
    return metadata


async def execute_local_tool(
    registry: ToolRegistry,
    tool_name: str,
    raw_args: str,
    skill_runtime: Any | None = None,
) -> str:  # 根据模型请求的工具名和参数，在本地执行对应工具。
    # `raw_args` 的来源是 assistant_message["tool_calls"][i]["function"]["arguments"]。  # 说明工具执行参数从消息历史中的哪里来。
    # 标准结构示例：{"file_path": "a.py", "content": "..."}。  # 说明执行前会把 JSON 字符串还原成 dict。
    try:  # 解析工具参数 JSON；模型生成非法 JSON 时工具不能执行。
        args = json.loads(raw_args) if raw_args else {}  # 有参数时解析成 dict，无参数时使用空 dict。
    except json.JSONDecodeError as exc:  # 捕获 JSON 解析失败，避免整个 agent 崩溃。
        return f"Tool execution error: invalid JSON arguments: {exc}"  # 把错误作为 tool 输出返回给模型，让模型有机会修正参数。

    tool = registry.get(tool_name)  # 从工具注册表按名称查找本地工具对象。
    if tool is None:  # 如果模型调用了不存在的工具名，不能执行。
        return f"Error: unknown tool {tool_name}"  # 返回明确错误，帮助模型或开发者定位工具名问题。

    try:  # 参数校验和工具执行都可能失败，因此统一捕获异常转成字符串输出。
        params = tool.params_model.model_validate(args)  # 使用工具自己的 Pydantic 参数模型校验和转换参数。
        notice = skill_tool_notice(tool_name, args if isinstance(args, dict) else {}, skill_runtime)  # SKILL 调用结果默认只给模型，这里补一条终端提示。
        if notice:
            print(notice, flush=True)
        result = await tool.execute(params)  # 调用工具的异步执行方法，得到 ToolResult。
    except Exception as exc:  # 捕获参数校验、文件 IO、Docker/Bash 等执行阶段异常。
        return f"Tool execution error: {exc}"  # 将异常信息作为工具输出返回给模型。

    return result.output  # 只把工具输出文本返回给模型；`is_error` 当前没有写入消息结构。


async def stream_one_round(  # 向模型发起一轮流式请求，并收集正文和工具调用。
    client: AsyncOpenAI,  # 已创建好的异步 OpenAI 兼容客户端，负责实际 HTTP 请求。
    model: str,  # 本轮请求使用的模型名，例如 `deepseek-v4-flash`。
    messages: list[dict[str, Any]],  # 当前完整对话历史；包含 system/user/assistant/tool 消息。
    tools: list[dict[str, Any]],  # OpenAI function tools schema；用于告诉模型可调用哪些本地工具。
    *,
    display: bool = True,
    output_label: str = "模型",
) -> tuple[str, list[PendingToolCall], Any]:  # 返回 `(assistant_text, tool_calls, usage)`，usage 是流末 chunk 的 token 统计对象。
    # `messages` 典型结构：  # 说明传给模型的上下文消息数组。
    # [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]  # 初始请求只包含系统提示和用户问题。
    # 工具调用后会追加 assistant tool_calls 消息和 role=tool 的工具结果消息。  # 后续循环依赖这些消息继续推理。
    try:
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            request["tools"] = tools
        stream = await client.chat.completions.create(**request)  # 发起流式 Chat Completions 请求。
    except (APIConnectionError, APITimeoutError) as exc:
        error = f"Error: API connection failed: {exc}"
        if display:
            print(f"{output_label}：{error}", flush=True)
        return error, [], None
    except APIError as exc:
        error = f"Error: API request failed: {exc}"
        if display:
            print(f"{output_label}：{error}", flush=True)
        return error, [], None

    content_parts: list[str] = []  # 收集模型普通文本 delta，最终拼成完整 assistant 文本。
    pending_tool_calls: dict[int, PendingToolCall] = {}  # 按 tool_call.index 聚合流式工具调用分片。
    last_usage = None  # 流式最后一个 chunk 携带 usage 统计（prompt_tokens / completion_tokens / cache 命中/未命中）。

    if display:
        print(f"{output_label}：", end="", flush=True)  # 在终端打印模型输出前缀，`end=""` 让后续流式文本接在同一行。
    async for chunk in stream:  # 异步迭代服务端不断返回的增量 chunk。
        if not chunk.choices:  # 某些兼容接口可能返回无 choices 的心跳/空 chunk。
            continue  # 跳过空 chunk，继续等待下一段有效内容。

        delta = chunk.choices[0].delta  # 取第一个候选的增量内容；本项目没有请求多候选输出。
        text = getattr(delta, "content", None)  # 普通文本增量在 `delta.content` 中；不存在时为 None。
        if text:  # 只有本 chunk 含有文本时才打印和收集。
            if display:
                print(text, end="", flush=True)  # 立即把文本打印到终端，实现边生成边显示。
            content_parts.append(text)  # 同时保存文本片段，函数结束时拼成完整 assistant_text。

        tool_deltas = getattr(delta, "tool_calls", None) or []  # 工具调用增量在 `delta.tool_calls` 中；缺失时按空列表处理。
        for tool_delta in tool_deltas:  # 一个 chunk 里可能同时携带多个工具调用的增量。
            state = pending_tool_calls.setdefault(tool_delta.index, PendingToolCall())  # 用 index 找到或创建对应工具调用的聚合状态。
            if tool_delta.id:  # 工具调用 ID 通常只在某个早期 chunk 中出现。
                state.tool_id = tool_delta.id  # 保存 ID，后续 `role=tool` 消息需要引用它。

            function_delta = getattr(tool_delta, "function", None)  # 函数工具调用的增量信息在 `tool_delta.function` 中。
            if function_delta is None:  # 如果当前增量没有 function 字段，就没有可拼接内容。
                continue  # 跳过该工具调用增量。
            if function_delta.name:  # 函数名也可能分片返回，但多数情况下只出现一次。
                state.tool_name = function_delta.name  # 保存工具名，例如 `WriteFile`。
            if function_delta.arguments:  # 参数 JSON 会经常被拆成多个字符串片段流式返回。
                state.arguments += function_delta.arguments  # 追加参数片段，直到最终形成完整 JSON 字符串。

        if hasattr(chunk, "usage") and chunk.usage:  # 流式最后一个 chunk 通常携带 usage 统计信息。
            last_usage = chunk.usage  # 保留最后一帧的 usage，函数结束时返回。

    if display and content_parts:  # 如果本轮模型输出过普通文本，需要补一个换行结束终端显示。
        print()  # 打印换行，避免后面的“工具调用”标题接在模型正文后。

    if display and pending_tool_calls:  # 如果模型本轮请求了工具调用，就把工具调用内容打印出来。
        print("工具调用：", flush=True)  # 打印工具调用分区标题。
        for index in sorted(pending_tool_calls):  # 按 OpenAI 返回的 index 排序，保证多工具调用展示顺序稳定。
            call = pending_tool_calls[index]  # 取出某个已经聚合完成的工具调用。
            formatted_args = pretty_arguments(call.arguments)  # 把工具 JSON 参数转成终端友好的展示文本。
            if "\n" in formatted_args:  # 多行参数需要换行打印，避免工具名和大段内容挤在一行。
                print(f"- {call.tool_name}\n{formatted_args}", flush=True)  # 打印工具名，并在下一行打印缩进后的参数。
            else:  # 单行参数可以和工具名放在同一行。
                print(f"- {call.tool_name} {formatted_args}", flush=True)  # 打印紧凑形式的工具调用。

    return "".join(content_parts), [pending_tool_calls[index] for index in sorted(pending_tool_calls)], last_usage  # 返回完整文本、按 index 排序的工具调用列表、以及流末 usage 统计。


async def ask_deepseek(  # 执行一次用户请求的完整 agent 循环：问模型、执行工具、再问模型，直到停止。
    client: AsyncOpenAI,  # 已打开连接的异步 API 客户端，由调用方负责创建和关闭。
    prompt: str,  # 当前用户输入的自然语言需求。
    registry: ToolRegistry,  # 本地工具注册表，用于根据模型 tool_call 名称找到实际工具对象。
    tools: list[dict[str, Any]],  # 已格式化好的 OpenAI tools schema，每轮请求都要传给模型。
    messages: list[dict[str, Any]] | None = None,  # 可选历史消息；为 None 时说明这是本轮会话的第一次请求。
    skill_runtime: Any | None = None,  # 可选 SKILL 运行时；存在时每轮动态生成 tools schema。
    core_tool_schemas: list[dict[str, Any]] | None = None,  # 六大核心工具的原始 schema，避免大量 SKILL 全量进入上下文。
    workspace_tracker: Any | None = None,
    memory_runtime: MemoryRuntime | None = None,
    capability_router: Any | None = None,
) -> tuple[str, list[dict[str, Any]]]:  # 返回 `(最终模型文本, 更新后的消息历史)`，供 CLI 继续保持上下文。
    # `messages` 在工具调用后的完整结构示例：  # 展示本函数维护的对话历史长什么样。
    # [  # 消息历史是一个有序数组，顺序就是模型看到的上下文顺序。
    #   {"role": "system", "content": "..."},  # 系统消息定义 agent 身份和工具约束。
    #   {"role": "user", "content": "创建 test.py"},  # 用户本轮输入。
    #   {"role": "assistant", "tool_calls": [{"id": "...", "type": "function", "function": {"name": "WriteFile", "arguments": "{...}"}}]},  # 模型请求调用工具。
    #   {"role": "tool", "tool_call_id": "...", "content": "Successfully wrote ..."},  # 本地工具执行结果。
    #   {"role": "assistant", "content": "已完成"}  # 模型最终回答。
    # ]  # 这些消息会被下一轮用户输入继续复用，实现跨轮记忆。
    if messages is None:  # 首次调用时没有历史消息，需要初始化系统提示。
        skill_hint = skill_runtime.system_hint() if skill_runtime is not None else ""  # 大量 SKILL 时追加 search_tool 使用说明。
        messages = [  # 创建新的消息列表；后续会原地 append 用户、assistant 和 tool 消息。
            {  # 单条 system 消息对象。
                "role": "system",  # system role 用于定义模型行为规则。
                "content": (  # system 内容描述 agent 身份、文件读取原则和沙箱约束。
                    """
                    ***角色定义***
                    你是一个名为 H-Agent 的智能体助手，你的基础功能是帮助用户编写、修改、审查和测试代码。
                    当需要本地文件信息时，请使用工具，请勿猜测文件内容。
                    除非用户需要，否则不要私自创建文件。
                    文件工具仅限在沙盒工作区内使用。
                    Shell 命令在 Docker 容器内运行，工作区挂载在 /workspace 目录下。
                    文件工具也接受 /workspace 作为沙盒工作区根目录的别名；例如 /workspace/a.py 等价于沙盒根目录下的 a.py。
                    由于沙箱的存在，你无法安全任何工具，当你需要某个工具时，可以告知用户下载该工具的方式，并由用户自由决定是否安装。
                    你运行在隔离的 Linux Docker 沙箱中，沙箱已经预装了常见的软件开发环境和命令行工具，如果不确定某个命令是否存在，应先判断该工具是否存在，若存在，才可以调用。
                    
                    不要因为不知道工具是否存在，就直接放弃任务。
                    重要：你绝对不能为用户生成或猜测 URL，除非你确信这些 URL是为了帮助用户完成编程任务。你可以使用用户在消息或本地文件中提供的 URL。
                    重要：允许协助已授权的安全测试、防御性安全研究、CTF 挑战赛和教育场景。拒绝涉及破坏性技术、DoS 攻击、大规模目标扫描、供应链攻击或用于恶意目的的检测规避请求。

                    ***行为准则***
                    1. 一般来说，不要对你没有阅读过的代码提出修改建议。如果用户要求你查看或修改某个文件，先读一遍它。在提出修改建议之前，先理解现有代码。
                    2. 不要在用户要求之外添加功能、重构代码或进行"改进"。修一个 bug不需要顺手清理周围的代码。一个简单功能不需要额外的可配置性。
                    3. 不要为一次性操作创建辅助函数、工具类或抽象层。
                    4. 三行相似的代码比一个过早的抽象更好。
                    5. 如果某个方案失败了，先诊断原因再决定是否换方案——读报错信息、检查你的假设、尝试有针对性的修复。不要盲目重试完全相同的操作，但也不要因为一次失败就放弃一个可行的方案。
                    6. 不要基于名称和结构做推断，而是逐行跟踪实际执行逻辑。
                    7.你必须为你编写的代码设计单元测试，并在代码修改结束后进行测试。

                    ***操作安全***
                    仔细考虑操作的可逆性（reversibility）和影响范围（blast radius）。
                    一般来说，你可以自由执行本地的、可逆的操作，比如编辑文件或运行测试。但对于难以撤销、影响共享系统或有风险的操作，请先和用户确认后再执行。
                    需要用户确认的高风险操作示例：
                    -破坏性操作：删除文件/分支、删表、rm -rf
                    -难以逆转的操作：force-push、git reset --hard、修改已发布的 commit
                    -对他人可见的操作：推送代码、创建/关闭 PR、发送消息
                    -上传到第三方工具：内容可能被缓存或索引，即使删除也无法撤回

                    ***工具使用指南***
                    能力选择策略：
                    -Model 自身能力只用于常识问答、推理、总结、翻译、文本生成。
                    -Business Skill 是开发者定义的专家工作流，负责领域流程、约束、标准和最佳实践。
                    -Core Tool 只负责执行读写文件、搜索、运行命令等基础操作，不负责替代专家工作流。
                    -如果当前工具列表中已经存在与用户请求高度匹配的 Business Skill，必须优先调用该 Skill；不得因为你自己知道如何完成而跳过。
                    -如果当前工具列表没有匹配 Skill，但任务可能有相关 Skill，先调用 search_tool 查询；search_tool 的 query 必须使用中文能力描述。
                    -最多调用 search_tool 三次，但三次检索必须逐步放宽：具体任务 → 同义词/能力类别 → 上位领域；不要越搜越窄。
                    -你可以连续调用skill解决用户需求。
                    -只有当 SKILL 兜底能力摘要明确覆盖你需要的能力，即你认为有 80% 可能存在你需要的skill，且三次中文 search_tool 都未命中时，才允许调用 Get_all_tool；若不确定摘要是否覆盖，禁止调用 Get_all_tool。
                    -Get_all_tool 主要用于用户询问“有哪些 skill/能力”或上述严格兜底场景；不要为了普通任务随意列出全部 skill。
                    -只有不存在相关 Business Skill、Skill 明显无法完成任务，或 Skill 指令明确要求执行时，才直接调用 Core Tool。
                    -多智能体路由采用二分类：只有当任务局部、明确、低风险，且不需要 plan/review/test 分离时，才由主智能体直接处理。
                    -所有非局部工程任务必须在代码修改前调用 DelegateToMultiAgent，由 plan、plan_review、execute、test、execute_review 子智能体闭环处理。
                    -如果任务需要先规划再执行、涉及多个相关部分、改变或重组项目结构、要求保持行为兼容、需要测试/审查循环、影响范围不清楚，必须调用 DelegateToMultiAgent。
                    -不确定任务影响是否局部时，必须调用 DelegateToMultiAgent。不得因为你已经知道方案而跳过委派；不得先部分执行可委派任务再委派。
                    -调用 DelegateToMultiAgent 时，reason 必须用一句话说明触发委派的工程条件，作为审计记录。
                    -前端页面/组件/Web App/UI/UX 需求优先调用 invoke_skill 且 skill_name=skill_frontend_design；
                     代码 Review 优先调用 invoke_skill 且 skill_name=skill_review；
                     后端面试优先调用 invoke_skill 且 skill_name=skill_backend_interview。

                    当有专用工具可用时，不要用 Bash 来执行命令。使用专用工具可以
                    让用户更好地理解和审查你的工作。这一点至关重要：
                    -读取文件用 Read 工具，而不是 cat、head、tail 或 sed
                    -编辑文件用 Edit 工具，而不是 sed 或 awk
                    -创建文件用 Write 工具，而不是 echo 重定向
                    -搜索文件用 Glob 工具，而不是 find 或 ls
                    -了解项目功能、架构或入口时，先使用窄范围 Glob（如 "*.py"、"backend/*.py"）和 ReadFile 读取 README、入口文件、配置文件；
                     不要一开始对 /workspace 使用 "**/*" 这类全仓库递归扫描。
                    -搜索内容用 Grep 工具，而不是 grep 或 rg
                    -查询、列举或确认当前可用 SKILL/技能/能力时，必须使用 Get_all_tool、search_tool 或 Get_tool_by_name；
                     不要用 Bash、Glob、ReadFile 直接查看 skills 目录、SQLite 数据库或 .skill_runtime
                    -每一次工具调用都必须提供简短 intent 字段，用一句话说明本次调用意图；intent 应短小稳定，用于历史工具输出虚拟化后的 metadata，而不是长篇推理。
                    -当缺少用户账号、用户名、仓库名、组织名、权限范围等无法从工具可靠确定的信息时，必须调用 ask_user 询问；可以用 choice 给出可选项；禁止从本地路径、Linux 用户名、项目名或历史猜测推断用户身份。
                    -MCP discovery 工具统一使用 offset/limit 分页；MCP call_tool 的 read 风险工具默认放行，write/dangerous/unknown 风险工具经 hook 请求用户确认，若用户拒绝则按工具结果继续处理。

                    ***Work Context Sufficiency Protocol***
                    Before producing the final answer, evaluate whether the current Working Context is sufficient to answer correctly.
                    Only recover additional context when unavailable historical information may influence correctness. Do not perform recovery as a formality for simple questions, general reasoning, translation, summarization, or answers that are already fully supported by the visible context.
                    If a user asks for a tool result or fact that is already visible in the current conversation, answer from the visible context directly; do not call BatchRecoverContext, SearchRecoverableContext, SearchSessionHistory, or GetRecentConversationTurns.
                    Never invent context_id values from tool names, arguments, offsets, or memory. Use recovery by id only when an exact id is visible in a recoverable reference or search result.
                    Evidence First Rule: never infer facts that could be verified by available historical context. If historical tool outputs, previously read file contents, command outputs, test results, prior decisions, constraints, or virtualized context may affect the answer, recover the relevant evidence before answering.
                    Historical tool outputs may have been virtualized. Recover additional context only if required for correctness.
                    Use the most appropriate recovery tool according to the current task:
                    -Use BatchRecoverContext with items when one or more relevant context_id values are already visible or known.
                    -Use SearchRecoverableContext when you need to locate historical tool outputs or virtualized context by topic, file, command, error, keyword, or decision.
                    -Use SearchSessionHistory when you need to search historical conversation turns.
                    -Use GetRecentConversationTurns when you need to understand the recent conversation structure before deciding what evidence matters.
                    Do not follow a fixed recovery sequence. Choose only the recovery tool that best matches the missing evidence.
                    After each recovery, re-evaluate whether the current Working Context is now sufficient. If it is still insufficient and more relevant evidence is available, continue recovering. Only produce the final answer when sufficient evidence has been collected, or when the needed evidence is unavailable and that limitation is explicitly stated.

                    ***Working Context Epoch Protocol***
                    Related user requests may share a multi-turn hot working context whose file contents and tool results remain visible.
                    Do not call CommitWorkingContext while the user is likely to continue the same implementation, debugging, review, or analysis task.
                    You are responsible for semantic working-context switches. Call CommitWorkingContext when the current task is complete, the user explicitly closes/switches work, or several recent requests have clearly formed a new task that no longer needs the prior hot context.
                    Runtime only forces CommitWorkingContext when the hot working context exceeds its budget; do not expect runtime to infer topic drift.
                    The commit is deferred until the current assistant turn is fully complete, so continue using the visible context normally after calling it.
                    CommitWorkingContext is a hot-to-cold epoch rotation control, not a checkpoint or rollover summary generator. Provide a concise reason, optional commit_note, important active_files, and any context_id values worth retaining; do not generate a dense task-history summary just for this tool.

                    ***Runtime Context Input Protocol***
                    A current user message may contain a structured wrapper with <RUNTIME_CONTEXT> and <USER_REQUEST>.
                    Treat <RUNTIME_CONTEXT> as current-turn environment state only. It is not a user request; do not answer, summarize, or repeat it directly.
                    Use <RUNTIME_CONTEXT> only when it affects the correctness of the <USER_REQUEST>.
                    Treat <USER_REQUEST> as the user's actual request.
                    Runtime Context is temporary for the current inference turn. When the turn becomes historical, rely on the original user request and recover historical evidence with tools when needed.

                    ***Git安全协议***
                    Git 安全协议：
                    -绝不修改 git config
                    -绝不执行破坏性 git 命令（push --force、reset --hard、checkout .、clean -f），除非用户明确要求
                    -绝不跳过 hooks（--no-verify），除非用户明确要求
                    -绝不 force push 到 main/master 分支，如果用户要求则发出警告

                    关键：始终创建新的 commit（NEW commit），而不是用 --amend 修改。
                    当 pre-commit hook 失败时，commit 实际上并没有发生——所以
                    --amend 会修改上一个（不相关的）commit，可能导致代码丢失。
                    正确做法是：修复问题后创建一个新的 commit。

                    ***输出风格***
                    对于简单问题，你可以直奔重点，但是对于稍显复杂的问题，你必须先列一个计划，然后按照计划执行，并根据计划的执行结果选择优化计划继续执行或直接回答。
                    工具调用之间的文字不超过 25 个词。默认最终回复不超过 100 个词。
                    当用户明确要求查看文件内容、代码、日志或命令输出时，可以完整展示必要内容，不受 100 个词限制。
                    先给出答案或行动，而不是推理过程。跳过填充词、开场白和不必要的过渡句。不要复述用户说过的话——直接做就行。
                    """
                    + ("\n***SKILL 工具检索***\n" + skill_hint if skill_hint else "")
                ),  # 结束 system content 字符串拼接。
            },  # 结束 system 消息对象。
        ]  # 完成初始消息列表。

    turn_start = len(messages)
    session_id = ""
    if memory_runtime is not None and CONFIG.memory.enabled:
        session_id = memory_runtime.start_session(MODEL)

    def current_context_mode() -> str:
        if memory_runtime is None or not session_id:
            return "raw"
        mode = memory_runtime.context_mode(session_id)
        return str(getattr(mode, "value", mode))

    begin_turn = getattr(skill_runtime, "begin_turn", None)
    if callable(begin_turn):
        begin_turn()

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

    def end_skill_turn() -> None:
        end_turn = getattr(skill_runtime, "end_turn", None)
        if callable(end_turn):
            end_turn()

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

    # 追加当前用户问题  # 每次调用 `ask_deepseek` 都代表用户发来一条新消息。
    messages.append({"role": "user", "content": prompt})  # 把用户输入追加进历史，让模型能看到本轮需求。
    save_session_state()
    temporary_system_messages: list[dict[str, Any]] = []
    capability_result = await capability_router.route(prompt) if capability_router is not None else None
    base_runtime_context = RuntimeContextBuilder(
        workspace_tracker=workspace_tracker,
        context_mode=current_context_mode(),
        capabilities=capability_result,
    ).build()
    rendered_prompt = PromptRenderer.render_current_user_message(base_runtime_context, prompt)
    round_messages = list(messages)
    if capability_router is None:
        current_tools = await build_round_tools(prompt, tools, skill_runtime, core_tool_schemas)
    else:
        current_tools = await build_round_tools(
            prompt,
            tools,
            skill_runtime,
            core_tool_schemas,
            capability_router=capability_router,
        )
    seen_tool_failures: set[tuple[str, str]] = set()

    for _ in range(MAX_TOOL_ROUNDS):  # 最多循环 MAX_TOOL_ROUNDS 次，防止模型不断调用工具无法结束。
        model_messages = render_current_turn_for_model(
            round_messages,
            current_turn_start=turn_start,
            rendered_prompt=rendered_prompt,
        )
        if memory_runtime is not None and session_id:
            summary_text = ""
            if should_generate_summary(memory_runtime, model_messages, current_tools, prompt):
                summary_text = await summarize_engineering_state(client, MODEL, model_messages)
            prepared_messages = memory_runtime.prepare_messages_for_model(
                session_id=session_id,
                messages=round_messages,
                tools=current_tools,
                current_prompt=prompt,
                summary_text=summary_text,
                persist_snapshot=True,
                current_turn_start=turn_start,
            )
            runtime_context = replace(
                base_runtime_context,
                context_mode=current_context_mode(),
                task_snapshot=summary_text or None,
            )
            rendered_prompt = PromptRenderer.render_current_user_message(runtime_context, prompt)
            model_messages = render_current_turn_for_model(
                prepared_messages,
                current_turn_start=turn_start,
                rendered_prompt=rendered_prompt,
            )
            budget_snapshot = memory_runtime.prompt_budget_snapshot(
                model_messages,
                tools=current_tools,
                current_prompt=prompt,
            )
            if budget_snapshot.usage_ratio >= CONFIG.memory.budget_soft_ratio:
                runtime_context = replace(
                    runtime_context,
                    context_budget=context_budget_state_from_snapshot(budget_snapshot),
                )
                rendered_prompt = PromptRenderer.render_current_user_message(runtime_context, prompt)
                model_messages = render_current_turn_for_model(
                    prepared_messages,
                    current_turn_start=turn_start,
                    rendered_prompt=rendered_prompt,
                )
        prompt_debug_snapshot = build_prompt_debug_snapshot(
            model_messages=model_messages,
            temporary_system_messages=temporary_system_messages,
            tools=current_tools,
            rendered_prompt=rendered_prompt,
        )
        print_prompt_debug_with_previous(prompt_debug_snapshot)
        assistant_text, tool_calls, usage = await stream_one_round(client, MODEL, model_messages, current_tools)  # 让模型基于当前历史输出文本或工具调用。
        if usage:
            usage_values = api_usage_to_dict(usage)
            add_usage_to_summary(turn_token_usage, usage_values)
            if memory_runtime is not None and session_id:
                session_token_usage = memory_runtime.record_token_usage(
                    session_id=session_id,
                    model=MODEL,
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
        if assistant_text.startswith("Error: API ") and not tool_calls:
            del messages[turn_start:]
            save_session_state(sync=True)
            print_turn_token_summary()
            end_skill_turn()
            return assistant_text, messages

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
            end_skill_turn()
            return assistant_text, messages  # 返回最终文本和完整消息历史给调用方。

        for index, tool_call in enumerate(tool_calls):  # 逐个执行模型请求的本地工具调用。
            tool_call_id = tool_call.tool_id or f"tool_call_{index}"  # 计算工具调用 ID，必须和上面的 assistant tool_calls 对象一致。
            tool_output = await execute_local_tool(registry, tool_call.tool_name, tool_call.arguments, skill_runtime)  # 执行本地工具并得到输出文本。
            failure_key = (tool_call.tool_name, tool_call.arguments.strip())
            if (
                tool_output.startswith("Tool execution error:")
                or tool_output.startswith("Error:")
                or '"error"' in tool_output[:300]
            ):
                if failure_key in seen_tool_failures:
                    tool_output += (
                        "\nRepeated tool failure with the same tool and arguments in this user turn. "
                        "Do not retry the same call. Correct the missing/invalid arguments, use a listed reference_path, "
                        "or answer with the information already available."
                    )
                else:
                    seen_tool_failures.add(failure_key)
            output_id = ""
            skill_related_tool = is_skill_related_tool(tool_call.tool_name)
            metadata = tool_call_metadata(tool_call.tool_name, tool_call.arguments, tool_output)
            if memory_runtime is not None and session_id and not skill_related_tool:
                output_id = memory_runtime.save_tool_output(
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_call.tool_name,
                    arguments=tool_call.arguments,
                    output=tool_output,
                    metadata=metadata,
                )
            if skill_related_tool:
                tool_output = tool_output
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

    print_turn_token_summary()
    end_skill_turn()
    return f"Error: exceeded max tool rounds ({MAX_TOOL_ROUNDS})", messages  # 超过工具循环上限时返回错误，避免无限运行。


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
    client: AsyncOpenAI,
    model: str,
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
        response = await client.chat.completions.create(
            model=model,
            messages=summary_messages,
            stream=False,
        )
    except (APIConnectionError, APITimeoutError, APIError) as exc:
        return f"UNKNOWN\nSUMMARY_ERROR: {exc}"
    if not response.choices:
        return "UNKNOWN"
    return response.choices[0].message.content or "UNKNOWN"


def truncate_tool_output(output: str) -> str:
    if len(output) <= MAX_TOOL_OUTPUT_CHARS:
        return output
    remaining = len(output) - MAX_TOOL_OUTPUT_CHARS
    return output[:MAX_TOOL_OUTPUT_CHARS] + f"\n... <tool output truncated {remaining} chars>"


def build_turn_temporary_system_messages(workspace_tracker: Any | None) -> list[dict[str, Any]]:
    return []


def with_workspace_change_notice(messages: list[dict[str, Any]], workspace_tracker: Any | None) -> list[dict[str, Any]]:
    return list(messages)


def with_turn_temporary_system_messages(
    messages: list[dict[str, Any]],
    temporary_system_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not temporary_system_messages:
        return list(messages)
    insert_at = 1 if messages and messages[0].get("role") == "system" else 0
    return [*messages[:insert_at], *temporary_system_messages, *messages[insert_at:]]


def workspace_change_notice_content(workspace_tracker: Any | None) -> str:
    return ""


async def build_round_tools(
    prompt: str,
    default_tools: list[dict[str, Any]],
    skill_runtime: Any | None,
    core_tool_schemas: list[dict[str, Any]] | None,
    capability_router: Any | None = None,
) -> list[dict[str, Any]]:
    if core_tool_schemas is None:
        return default_tools
    return format_openai_tools(core_tool_schemas)


async def main() -> None:  # 提供一个直接运行 `client.py` 时使用的测试入口。
    prompt = (  # 准备一条固定测试 prompt，用于验证 agent 能读取目录并写 README。
        "读取目录下全部文件内容，并用中文总结这个项目，最后写入README.md文件中。"  # 测试需求文本。
    )  # 结束 prompt 字符串。

    registry = create_default_registry()  # 创建默认工具注册表，包含文件读写、搜索和 Docker Bash。
    raw_tools = registry.get_all_schemas("openai")  # 从注册表拿到 OpenAI 协议方向的原始工具 schema。
    tools = format_openai_tools(raw_tools)  # 确保工具 schema 满足 Chat Completions 的 tools 参数格式。

    client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)  # 创建异步 API 客户端；连接地址可由 BASE_URL 控制。

    print(f"提问：{prompt}", flush=True)  # 在终端显示测试 prompt。
    result, messages = await ask_deepseek(client, prompt, registry, tools)  # 执行完整 agent 循环，得到最终回答和历史消息。
    print(f"结果：{result}", flush=True)  # 打印模型最终回答。

    await client.close()  # 关闭异步 HTTP 客户端连接，释放网络资源。


if __name__ == "__main__":  # 只有直接运行本文件时才执行测试入口，被其他模块 import 时不会运行。
    asyncio.run(main())  # 启动事件循环并运行异步 main。
