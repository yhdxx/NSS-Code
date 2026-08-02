from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


# ── 统一用户 JSON 配置 ──
_USER_CONFIG_PATH = Path.home() / ".mycodingagent" / "config.json"
_MISSING = object()


def _load_user_json_config() -> dict:
    """加载 ~/.mycodingagent/config.json。

    文件不存在或解析失败时静默返回 {}，格式诊断由 app/main.py 处理。
    """
    try:
        raw_text = _USER_CONFIG_PATH.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, OSError):
        return {}
    if not raw_text.strip():
        return {}
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


_USER_JSON_CONFIG = _load_user_json_config()


# ── 统一配置查找函数 ──

def _user_raw(json_path: str, env_names: tuple[str, ...]) -> object:
    """统一配置查找：JSON 路径 > 环境变量列表（逐项尝试）。

    json_path 示例："api.model"
    env_names 示例：("DEEPSEEK_MODEL",)
    """
    # 第一优先级：~/.mycodingagent/config.json
    current: object = _USER_JSON_CONFIG
    for part in json_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            current = _MISSING
            break
    if current is not _MISSING and current is not None:
        if isinstance(current, str) and not current.strip():
            pass  # 空字符串视为未设置，回退到 env
        else:
            return current
    # 第二优先级：环境变量（按顺序尝试）
    for name in env_names:
        value = os.getenv(name)
        if value is not None:
            return value
    return _MISSING


def _user_str(json_path: str, env_names: tuple[str, ...], default: str) -> str:
    raw = _user_raw(json_path, env_names)
    if raw is _MISSING or raw is None:
        return default
    return str(raw)


def _user_int(json_path: str, env_names: tuple[str, ...], default: int) -> int:
    raw = _user_raw(json_path, env_names)
    if raw is _MISSING or raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _user_float(json_path: str, env_names: tuple[str, ...], default: float) -> float:
    raw = _user_raw(json_path, env_names)
    if raw is _MISSING or raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _user_bool(json_path: str, env_names: tuple[str, ...], default: bool) -> bool:
    raw = _user_raw(json_path, env_names)
    if raw is _MISSING or raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _user_list(json_path: str, env_names: tuple[str, ...], default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = _user_raw(json_path, env_names)
    if raw is _MISSING or raw is None:
        return default
    if isinstance(raw, (list, tuple)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return tuple(item.strip() for item in str(raw).split(",") if item.strip())


def _user_dict(json_path: str, env_names: tuple[str, ...], default: dict) -> dict:
    raw = _user_raw(json_path, env_names)
    if raw is _MISSING or raw is None or raw == "":
        return default
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return default
    return value if isinstance(value, dict) else default


def _user_path(
    json_path: str, env_names: tuple[str, ...], default: Path | None = None
) -> Path | None:
    raw = _user_raw(json_path, env_names)
    if raw is _MISSING or raw is None or raw == "":
        return default
    return Path(str(raw)).expanduser()


def _user_paths(
    json_path: str, env_names: tuple[str, ...], default: tuple[Path, ...] = ()
) -> tuple[Path, ...]:
    raw = _user_raw(json_path, env_names)
    if raw is _MISSING or raw is None:
        return default
    if isinstance(raw, (list, tuple)):
        return tuple(
            Path(str(item)).expanduser()
            for item in raw
            if str(item).strip()
        )
    return tuple(
        Path(item.strip()).expanduser()
        for item in str(raw).split(os.pathsep)
        if item.strip()
    )


# ── 辅助函数（非配置查找，保留原逻辑） ──

def _dedupe_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for p in paths:
        key = str(p.expanduser().resolve(strict=False))
        if key not in seen:
            seen.add(key)
            result.append(p)
    return tuple(result)


def _default_user_id() -> str:
    return (
        _user_str("skills.user_id", ("MYCODINGAGENT_USER_ID",), "")
        or os.getenv("USER")
        or os.getenv("USERNAME")
        or "default_user"
    )


def _default_embedding_api_format() -> str:
    provider = _user_str("embedding.provider", ("MYCODINGAGENT_EMBEDDING_PROVIDER",), "bge_http").strip().lower()
    if provider in {"openai", "openai_compatible", "openai-compatible"}:
        return "openai"
    if provider == "dashscope":
        return "dashscope"
    return "ollama"


def _default_builtin_skills_root() -> Path:
    return Path(__file__).resolve().parents[2] / "skills"


def _default_workspace_skills_root() -> Path:
    raw_root = (
        _user_str("skills.workspace_root", ("MYCODINGAGENT_WORKSPACE_SKILLS_ROOT", "MYCODINGAGENT_SKILLS_ROOT"), "")
    )
    if raw_root:
        return Path(raw_root).expanduser()
    sandbox_root = _user_str("sandbox.root", ("MYCODINGAGENT_SANDBOX_ROOT",), os.getcwd())
    return Path(sandbox_root).expanduser() / "skills"


def _default_memory_db_path() -> Path:
    state_dir = _user_str("memory.state_dir", ("MYCODINGAGENT_STATE_DIR",), "")
    if state_dir:
        return Path(state_dir).expanduser() / "sessions.sqlite3"
    xdg_state_home = os.getenv("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "myCodingAgent" / "sessions.sqlite3"
    return Path.home() / ".local" / "state" / "myCodingAgent" / "sessions.sqlite3"


def _default_mcp_project_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".mycodingagent" / "mcp.json"


def _default_mcp_user_config_path() -> Path:
    return Path.home() / ".config" / "myCodingAgent" / "mcp.json"


# ── 配置类定义 ──

@dataclass(frozen=True)
class ApiConfig:
    """主模型 API 配置。模型名称影响对话质量和长期记忆模型选择。"""
    deepseek_api_key: str = field(
        default_factory=lambda: _user_str("api.deepseek_api_key", ("DEEPSEEK_API_KEY",), "")
    )
    base_url: str = field(
        default_factory=lambda: _user_str("api.base_url", ("DEEPSEEK_BASE_URL",), "https://api.deepseek.com")
    )
    model: str = field(
        default_factory=lambda: _user_str("api.model", ("DEEPSEEK_MODEL",), "deepseek-v4-pro")
    )


@dataclass(frozen=True)
class ClientConfig:
    """LLM 客户端运行时行为配置：重试、展示、调试和系统提示词。"""
    max_tool_rounds: int = field(
        default_factory=lambda: _user_int("client.max_tool_rounds", ("MYCODINGAGENT_MAX_TOOL_ROUNDS",), 50)
    )
    max_display_string_chars: int = field(
        default_factory=lambda: _user_int("client.max_display_string_chars", ("MYCODINGAGENT_MAX_DISPLAY_STRING_CHARS",), 12000)
    )
    max_tool_output_chars: int = field(
        default_factory=lambda: _user_int("client.max_tool_output_chars", ("MYCODINGAGENT_MAX_TOOL_OUTPUT_CHARS",), 20000)
    )
    api_max_retries: int = field(
        default_factory=lambda: _user_int("client.api_max_retries", ("MYCODINGAGENT_API_MAX_RETRIES",), 3)
    )
    api_retry_base_delay: float = field(
        default_factory=lambda: _user_float("client.api_retry_base_delay", ("MYCODINGAGENT_API_RETRY_BASE_DELAY",), 1.0)
    )
    multiline_argument_fields: frozenset[str] = frozenset({"command", "content", "old_string", "new_string"})
    debug: bool = field(
        default_factory=lambda: _user_bool("client.debug", ("DEBUG", "MYCODINGAGENT_DEBUG"), False)
    )
    step_token: bool = field(
        default_factory=lambda: _user_bool("client.step_token", ("STEP_TOKEN",), True)
    )
    round_token: bool = field(
        default_factory=lambda: _user_bool("client.round_token", ("ROUND_TOKEN",), True)
    )
    conversation_token: bool = field(
        default_factory=lambda: _user_bool("client.conversation_token", ("CONVERSATION_TOKEN",), True)
    )
    legacy_system_prompt: bool = field(
        default_factory=lambda: _user_bool("client.legacy_system_prompt", ("MYCODINGAGENT_LEGACY_SYSTEM_PROMPT",), False)
    )


@dataclass(frozen=True)
class MultiAgentConfig:
    """多智能体并发和轮次限制。"""
    max_agent_rounds: int = field(
        default_factory=lambda: max(1, _user_int("multi_agent.max_agent_rounds", ("MYCODINGAGENT_MULTI_AGENT_MAX_AGENT_ROUNDS",), 50))
    )
    max_parallel_tasks: int = field(
        default_factory=lambda: max(1, _user_int("multi_agent.max_parallel_tasks", ("MYCODINGAGENT_MULTI_AGENT_MAX_PARALLEL_TASKS",), 5))
    )


@dataclass(frozen=True)
class LongTermMemoryConfig:
    """长期记忆存储和查询配置。

    storage_model / query_model 为空时自动跟随 api.model / deepseek-v4-flash。
    """
    enabled: bool = field(
        default_factory=lambda: _user_bool("long_term_memory.enabled", ("MYCODINGAGENT_LONG_TERM_MEMORY_ENABLED",), True)
    )
    storage_model: str = field(
        default_factory=lambda: _user_str("long_term_memory.storage_model", ("MYCODINGAGENT_LONG_TERM_MEMORY_STORAGE_MODEL",), "")
    )
    query_model: str = field(
        default_factory=lambda: _user_str("long_term_memory.query_model", ("MYCODINGAGENT_LONG_TERM_MEMORY_QUERY_MODEL",), "")
    )
    query_recent_turns: int = field(
        default_factory=lambda: max(1, _user_int("long_term_memory.query_recent_turns", ("MYCODINGAGENT_LONG_TERM_MEMORY_QUERY_RECENT_TURNS",), 10))
    )
    max_memories: int = field(
        default_factory=lambda: max(1, _user_int("long_term_memory.max_memories", ("MYCODINGAGENT_LONG_TERM_MEMORY_MAX_MEMORIES",), 50))
    )
    max_workflow_candidates: int = field(
        default_factory=lambda: max(0, _user_int("long_term_memory.max_workflow_candidates", ("MYCODINGAGENT_LONG_TERM_MEMORY_MAX_WORKFLOW_CANDIDATES",), 5))
    )
    max_skill_candidates: int = field(
        default_factory=lambda: max(0, _user_int("long_term_memory.max_skill_candidates", ("MYCODINGAGENT_LONG_TERM_MEMORY_MAX_SKILL_CANDIDATES",), 3))
    )
    skill_candidate_success_threshold: int = field(
        default_factory=lambda: max(0, _user_int("long_term_memory.skill_candidate_success_threshold", ("MYCODINGAGENT_LONG_TERM_MEMORY_SKILL_SUCCESS_THRESHOLD",), 3))
    )
    skill_candidate_prompt_cooldown_days: int = field(
        default_factory=lambda: max(0, _user_int("long_term_memory.skill_candidate_prompt_cooldown_days", ("MYCODINGAGENT_LONG_TERM_MEMORY_SKILL_PROMPT_COOLDOWN_DAYS",), 7))
    )
    extraction_claim_timeout_seconds: int = field(
        default_factory=lambda: max(1, _user_int("long_term_memory.extraction_claim_timeout_seconds", ("MYCODINGAGENT_LONG_TERM_MEMORY_EXTRACTION_CLAIM_TIMEOUT_SECONDS",), 600))
    )
    graceful_exit_extract_timeout_seconds: int = field(
        default_factory=lambda: max(1, _user_int("long_term_memory.graceful_exit_extract_timeout_seconds", ("MYCODINGAGENT_LONG_TERM_MEMORY_GRACEFUL_EXIT_TIMEOUT_SECONDS",), 30))
    )
    startup_backfill_enabled: bool = field(
        default_factory=lambda: _user_bool("long_term_memory.startup_backfill_enabled", ("MYCODINGAGENT_LONG_TERM_MEMORY_STARTUP_BACKFILL_ENABLED",), True)
    )


@dataclass(frozen=True)
class MemoryConfig:
    """会话持久化、上下文虚拟化和检查点配置。"""
    enabled: bool = field(
        default_factory=lambda: _user_bool("memory.enabled", ("MYCODINGAGENT_MEMORY_ENABLED",), True)
    )
    output_context_compression: bool = field(
        default_factory=lambda: _user_bool("memory.output_context_compression", ("OUTPUT_CONTEXT_COMPRESSION",), True)
    )
    db_path: Path = field(
        default_factory=lambda: _user_path("memory.db_path", ("MYCODINGAGENT_MEMORY_DB_PATH",)) or _default_memory_db_path()
    )
    prompt_path: Path | None = field(
        default_factory=lambda: _user_path("memory.prompt_path", ("MYCODINGAGENT_MEMORY_SUMMARY_PROMPT",))
    )
    default_context_window: int = field(
        default_factory=lambda: _user_int("memory.default_context_window", ("MYCODINGAGENT_MODEL_CONTEXT_WINDOW",), 128_000)
    )
    session_ttl_days: int = field(
        default_factory=lambda: _user_int("memory.session_ttl_days", ("MYCODINGAGENT_MEMORY_SESSION_TTL_DAYS",), 90)
    )
    default_work_mode: str = field(
        default_factory=lambda: (
            wm if (wm := _user_str("memory.default_work_mode", ("MYCODINGAGENT_DEFAULT_WORK_MODE",), "general").strip().lower()) in {"general", "code"}
            else "general"
        )
    )
    workspace_snapshot_ttl_days: int = field(
        default_factory=lambda: _user_int("memory.workspace_snapshot_ttl_days", ("MYCODINGAGENT_MEMORY_WORKSPACE_SNAPSHOT_TTL_DAYS",), 30)
    )
    tool_preview_chars: int = field(
        default_factory=lambda: _user_int("memory.tool_preview_chars", ("MYCODINGAGENT_MEMORY_TOOL_PREVIEW_CHARS",), 2000)
    )
    context_preview_threshold_tokens: int = field(
        default_factory=lambda: _user_int("memory.context_preview_threshold_tokens", ("MYCODINGAGENT_CONTEXT_PREVIEW_THRESHOLD_TOKENS",), 12000)
    )
    context_preview_tokens: int = field(
        default_factory=lambda: _user_int("memory.context_preview_tokens", ("MYCODINGAGENT_CONTEXT_PREVIEW_TOKENS",), 2000)
    )
    raw_tool_output_preview_chars: int = field(
        default_factory=lambda: _user_int("memory.raw_tool_output_preview_chars", ("MYCODINGAGENT_RAW_TOOL_OUTPUT_PREVIEW_CHARS",), 1000)
    )
    raw_to_virtualized_ratio: float = field(
        default_factory=lambda: _user_float("memory.raw_to_virtualized_ratio", ("MYCODINGAGENT_RAW_TO_VIRTUALIZED_RATIO",), 0.60)
    )
    budget_soft_ratio: float = field(
        default_factory=lambda: _user_float("memory.budget_soft_ratio", ("MYCODINGAGENT_BUDGET_SOFT_RATIO",), 0.60)
    )
    budget_working_ratio: float = field(
        default_factory=lambda: _user_float("memory.budget_working_ratio", ("MYCODINGAGENT_BUDGET_WORKING_RATIO",), 0.80)
    )
    budget_emergency_ratio: float = field(
        default_factory=lambda: _user_float("memory.budget_emergency_ratio", ("MYCODINGAGENT_BUDGET_EMERGENCY_RATIO",), 0.90)
    )
    hot_context_warning_ratio: float = field(
        default_factory=lambda: _user_float("memory.hot_context_warning_ratio", ("MYCODINGAGENT_HOT_CONTEXT_WARNING_RATIO",), 0.30)
    )
    hot_context_force_ratio: float = field(
        default_factory=lambda: _user_float("memory.hot_context_force_ratio", ("MYCODINGAGENT_HOT_CONTEXT_FORCE_RATIO",), 0.40)
    )
    hot_context_retained_turns: int = field(
        default_factory=lambda: _user_int("memory.hot_context_retained_turns", ("MYCODINGAGENT_HOT_CONTEXT_RETAINED_TURNS",), 3)
    )
    hot_context_topic_drift_turns: int = field(
        default_factory=lambda: _user_int("memory.hot_context_topic_drift_turns", ("MYCODINGAGENT_HOT_CONTEXT_TOPIC_DRIFT_TURNS",), 3)
    )
    hot_context_topic_similarity_threshold: float = field(
        default_factory=lambda: _user_float("memory.hot_context_topic_similarity_threshold", ("MYCODINGAGENT_HOT_CONTEXT_TOPIC_SIMILARITY_THRESHOLD",), 0.12)
    )
    archive_cold_context_ratio: float = field(
        default_factory=lambda: _user_float("memory.archive_cold_context_ratio", ("MYCODINGAGENT_ARCHIVE_COLD_CONTEXT_RATIO",), 0.50)
    )
    current_turn_summary_max_per_message: int = field(
        default_factory=lambda: _user_int("memory.current_turn_summary_max_per_message", ("MYCODINGAGENT_CURRENT_TURN_SUMMARY_MAX_PER_MESSAGE",), 2)
    )
    current_turn_summary_max_per_turn: int = field(
        default_factory=lambda: _user_int("memory.current_turn_summary_max_per_turn", ("MYCODINGAGENT_CURRENT_TURN_SUMMARY_MAX_PER_TURN",), 5)
    )
    checkpoint_enabled: bool = field(
        default_factory=lambda: _user_bool("memory.checkpoint_enabled", ("MYCODINGAGENT_CHECKPOINT_ENABLED",), True)
    )
    checkpoint_soft_ratio: float = field(
        default_factory=lambda: _user_float("memory.checkpoint_soft_ratio", ("MYCODINGAGENT_CHECKPOINT_SOFT_RATIO",), 0.65)
    )
    checkpoint_hard_ratio: float = field(
        default_factory=lambda: _user_float("memory.checkpoint_hard_ratio", ("MYCODINGAGENT_CHECKPOINT_HARD_RATIO",), 0.85)
    )
    snapshot_version: str = field(
        default_factory=lambda: _user_str("memory.snapshot_version", ("MYCODINGAGENT_SNAPSHOT_VERSION",), "1.0")
    )
    checkpoint_min_turns_between_rollovers: int = field(
        default_factory=lambda: _user_int("memory.checkpoint_min_turns_between_rollovers", ("MYCODINGAGENT_CHECKPOINT_MIN_TURNS_BETWEEN_ROLLOVERS",), 3)
    )
    checkpoint_recent_delta_turns: int = field(
        default_factory=lambda: _user_int("memory.checkpoint_recent_delta_turns", ("MYCODINGAGENT_CHECKPOINT_RECENT_DELTA_TURNS",), 20)
    )
    reserved_reasoning_tokens: int = field(
        default_factory=lambda: _user_int("memory.reserved_reasoning_tokens", ("MYCODINGAGENT_RESERVED_REASONING_TOKENS",), 8000)
    )
    reserved_output_tokens: int = field(
        default_factory=lambda: _user_int("memory.reserved_output_tokens", ("MYCODINGAGENT_RESERVED_OUTPUT_TOKENS",), 4000)
    )
    reserved_tool_tokens: int = field(
        default_factory=lambda: _user_int("memory.reserved_tool_tokens", ("MYCODINGAGENT_RESERVED_TOOL_TOKENS",), 12000)
    )
    context_store_backend: str = field(
        default_factory=lambda: _user_str("memory.context_store_backend", ("MYCODINGAGENT_CONTEXT_STORE_BACKEND",), "sqlite")
    )
    recent_rounds_for_average: int = field(
        default_factory=lambda: _user_int("memory.recent_rounds_for_average", ("MYCODINGAGENT_MEMORY_RECENT_ROUNDS",), 20)
    )
    recent_messages_after_summary: int = field(
        default_factory=lambda: _user_int("memory.recent_messages_after_summary", ("MYCODINGAGENT_MEMORY_RECENT_MESSAGES_AFTER_SUMMARY",), 12)
    )
    model_context_windows: dict = field(
        default_factory=lambda: _user_dict(
            "memory.model_context_windows",
            ("MYCODINGAGENT_MODEL_CONTEXT_WINDOWS",),
            {"deepseek-v4-flash": 1_000_000},
        )
    )

    def context_window_for(self, model: str) -> int:
        value = self.model_context_windows.get(model)
        if isinstance(value, int) and value > 0:
            return value
        return self.default_context_window


@dataclass(frozen=True)
class SandboxConfig:
    """Docker 沙箱工作区配置。"""
    root_env: str = "MYCODINGAGENT_SANDBOX_ROOT"
    root: Path = field(
        default_factory=lambda: Path(_user_str("sandbox.root", ("MYCODINGAGENT_SANDBOX_ROOT",), os.getcwd()))
    )
    docker_workspace_alias: Path = Path("/workspace")
    max_output_chars: int = field(
        default_factory=lambda: _user_int("sandbox.max_output_chars", ("MYCODINGAGENT_MAX_OUTPUT_CHARS",), 10000)
    )
    workspace_lease_enabled: bool = field(
        default_factory=lambda: _user_bool("sandbox.workspace_lease_enabled", ("MYCODINGAGENT_WORKSPACE_LEASE_ENABLED",), True)
    )
    skip_dirs: frozenset[str] = frozenset({
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".skill_runtime",
        "build",
        "dist",
    })


@dataclass(frozen=True)
class DockerConfig:
    """Docker 沙箱容器资源限制。"""
    image_env: str = "MYCODINGAGENT_DOCKER_IMAGE"
    network_env: str = "MYCODINGAGENT_DOCKER_NETWORK"
    build_network_env: str = "MYCODINGAGENT_DOCKER_BUILD_NETWORK"
    cpus_env: str = "MYCODINGAGENT_DOCKER_CPUS"
    memory_env: str = "MYCODINGAGENT_DOCKER_MEMORY"
    pids_limit_env: str = "MYCODINGAGENT_DOCKER_PIDS_LIMIT"
    pull_timeout_env: str = "MYCODINGAGENT_DOCKER_PULL_TIMEOUT"
    image: str = field(
        default_factory=lambda: _user_str("docker.image", ("MYCODINGAGENT_DOCKER_IMAGE",), "mycodingagent-sandbox:py312")
    )
    network: str = field(
        default_factory=lambda: _user_str("docker.network", ("MYCODINGAGENT_DOCKER_NETWORK",), "bridge")
    )
    build_network: str = field(
        default_factory=lambda: _user_str("docker.build_network", ("MYCODINGAGENT_DOCKER_BUILD_NETWORK",), "host")
    )
    cpus: str = field(
        default_factory=lambda: _user_str("docker.cpus", ("MYCODINGAGENT_DOCKER_CPUS",), "2")
    )
    memory: str = field(
        default_factory=lambda: _user_str("docker.memory", ("MYCODINGAGENT_DOCKER_MEMORY",), "1g")
    )
    pids_limit: str = field(
        default_factory=lambda: _user_str("docker.pids_limit", ("MYCODINGAGENT_DOCKER_PIDS_LIMIT",), "256")
    )
    default_timeout: int = field(
        default_factory=lambda: _user_int("docker.default_timeout", ("MYCODINGAGENT_DOCKER_DEFAULT_TIMEOUT",), 120)
    )
    max_timeout: int = field(
        default_factory=lambda: _user_int("docker.max_timeout", ("MYCODINGAGENT_DOCKER_MAX_TIMEOUT",), 600)
    )
    check_timeout: int = field(
        default_factory=lambda: _user_int("docker.check_timeout", ("MYCODINGAGENT_DOCKER_CHECK_TIMEOUT",), 30)
    )
    pull_timeout: int = field(
        default_factory=lambda: _user_int("docker.pull_timeout", ("MYCODINGAGENT_DOCKER_PULL_TIMEOUT",), 300)
    )


@dataclass(frozen=True)
class SkillConfig:
    """Skill 发现、索引、路由和 LRFU 配置。"""
    builtin_root: Path = field(
        default_factory=lambda: (
            _user_path("skills.builtin_root", ("MYCODINGAGENT_BUILTIN_SKILLS_ROOT",))
            or _default_builtin_skills_root()
        )
    )
    workspace_root: Path = field(default_factory=_default_workspace_skills_root)
    extra_roots: tuple[Path, ...] = field(
        default_factory=lambda: _user_paths("skills.extra_roots", ("MYCODINGAGENT_EXTRA_SKILLS_ROOTS",))
    )
    markdown_filename: str = field(
        default_factory=lambda: _user_str("skills.markdown_filename", ("MYCODINGAGENT_SKILL_MARKDOWN_NAME",), "SKILL.md")
    )
    json_suffix: str = field(
        default_factory=lambda: _user_str("skills.json_suffix", ("MYCODINGAGENT_SKILL_JSON_SUFFIX",), ".skill.json")
    )
    skip_dirs: frozenset[str] = frozenset({"__pycache__", ".skill_runtime", ".git", ".venv"})
    small_count: int = field(
        default_factory=lambda: _user_int("skills.small_count", ("MYCODINGAGENT_SKILL_SMALL_COUNT",), 8)
    )
    default_tool_names: tuple[str, ...] = field(
        default_factory=lambda: _user_list("skills.default_tool_names", ("MYCODINGAGENT_DEFAULT_SKILLS",), ("coding-standards",))
    )
    prefetch_top_k: int = field(
        default_factory=lambda: _user_int("skills.prefetch_top_k", ("MYCODINGAGENT_SKILL_PREFETCH_TOP_K",), 3)
    )
    search_top_k: int = field(
        default_factory=lambda: _user_int("skills.search_top_k", ("MYCODINGAGENT_SKILL_SEARCH_TOP_K",), 8)
    )
    min_score: float = field(
        default_factory=lambda: _user_float("skills.min_score", ("MYCODINGAGENT_SKILL_MIN_SCORE",), 0.18)
    )
    index_dir: Path | None = field(
        default_factory=lambda: _user_path("skills.index_dir", ("MYCODINGAGENT_SKILL_INDEX_DIR",))
    )
    watcher_poll_interval: float = field(
        default_factory=lambda: _user_float("skills.watcher_poll_interval", ("MYCODINGAGENT_SKILL_WATCH_POLL_INTERVAL",), 2.0)
    )
    user_id: str = field(default_factory=_default_user_id)
    router_top_n: int = field(
        default_factory=lambda: _user_int("skills.router_top_n", ("MYCODINGAGENT_SKILL_ROUTER_TOP_N",), 10)
    )
    router_retrieval_top_k: int = field(
        default_factory=lambda: _user_int("skills.router_retrieval_top_k", ("MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_TOP_K",), 40)
    )
    router_cache_top_k: int = field(
        default_factory=lambda: _user_int("skills.router_cache_top_k", ("MYCODINGAGENT_SKILL_ROUTER_CACHE_TOP_K",), 40)
    )
    router_retrieval_min_ratio: float = field(
        default_factory=lambda: _user_float("skills.router_retrieval_min_ratio", ("MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_MIN_RATIO",), 0.4)
    )
    router_user_weight: float = field(
        default_factory=lambda: _user_float("skills.router_user_weight", ("MYCODINGAGENT_SKILL_ROUTER_USER_WEIGHT",), 0.15)
    )
    router_session_weight: float = field(
        default_factory=lambda: _user_float("skills.router_session_weight", ("MYCODINGAGENT_SKILL_ROUTER_SESSION_WEIGHT",), 0.45)
    )
    router_retrieval_weight: float = field(
        default_factory=lambda: _user_float("skills.router_retrieval_weight", ("MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_WEIGHT",), 0.40)
    )
    router_pinned_bonus: float = field(
        default_factory=lambda: _user_float("skills.router_pinned_bonus", ("MYCODINGAGENT_SKILL_ROUTER_PINNED_BONUS",), 1.0)
    )
    lrfu_decay: float = field(
        default_factory=lambda: _user_float("skills.lrfu_decay", ("MYCODINGAGENT_SKILL_LRFU_DECAY",), 0.95)
    )
    skill_call_reward: float = field(
        default_factory=lambda: _user_float("skills.skill_call_reward", ("MYCODINGAGENT_SKILL_CALL_REWARD",), 10.0)
    )
    session_activation_reward: float = field(
        default_factory=lambda: _user_float(
            "skills.session_activation_reward",
            ("MYCODINGAGENT_SKILL_SESSION_ACTIVATION_REWARD",),
            0.3,
        )
    )
    user_skill_cache_max_entries: int = field(
        default_factory=lambda: _user_int(
            "skills.user_skill_cache_max_entries",
            ("MYCODINGAGENT_USER_SKILL_CACHE_MAX_ENTRIES",),
            1000,
        )
    )
    session_skill_cache_max_entries: int = field(
        default_factory=lambda: _user_int("skills.session_skill_cache_max_entries", ("MYCODINGAGENT_SESSION_SKILL_CACHE_MAX_ENTRIES",), 200)
    )
    output_recall_skill: bool = field(
        default_factory=lambda: _user_bool("skills.output_recall_skill", ("OUTPUT_RECALL_SKILL",), True)
    )
    vector_sync_batch_size: int = field(
        default_factory=lambda: max(1, _user_int("skills.vector_sync_batch_size", ("MYCODINGAGENT_SKILL_VECTOR_SYNC_BATCH_SIZE",), 2))
    )
    vector_sync_max_retries: int = field(
        default_factory=lambda: max(1, _user_int("skills.vector_sync_max_retries", ("MYCODINGAGENT_SKILL_VECTOR_SYNC_MAX_RETRIES",), 3))
    )

    @property
    def root(self) -> Path:
        return self.builtin_root

    @property
    def roots(self) -> tuple[Path, ...]:
        return _dedupe_paths((self.builtin_root, *self.extra_roots))


@dataclass(frozen=True)
class EmbeddingConfig:
    """Embedding 模型配置：provider/model/endpoint/api_key 等。"""
    provider: str = field(
        default_factory=lambda: _user_str("embedding.provider", ("MYCODINGAGENT_EMBEDDING_PROVIDER",), "bge_http")
    )
    model: str = field(
        default_factory=lambda: _user_str("embedding.model", ("MYCODINGAGENT_EMBEDDING_MODEL", "MYCODINGAGENT_BGE_MODEL"), "bge-m3")
    )
    endpoint: str = field(
        default_factory=lambda: _user_str(
            "embedding.endpoint",
            ("MYCODINGAGENT_EMBEDDING_ENDPOINT", "MYCODINGAGENT_BGE_ENDPOINT"),
            "http://127.0.0.1:11434/api/embed",
        )
    )
    api_format: str = field(
        default_factory=lambda: _user_str(
            "embedding.api_format",
            ("MYCODINGAGENT_EMBEDDING_API_FORMAT", "MYCODINGAGENT_BGE_API_FORMAT"),
            _default_embedding_api_format(),
        )
    )
    api_key: str | None = field(
        default_factory=lambda: _user_str(
            "embedding.api_key",
            ("MYCODINGAGENT_EMBEDDING_API_KEY", "MYCODINGAGENT_BGE_API_KEY"),
            "",
        ) or None
    )
    timeout: float = field(
        default_factory=lambda: max(
            0.1,
            _user_float(
                "embedding.timeout",
                ("MYCODINGAGENT_EMBEDDING_TIMEOUT", "MYCODINGAGENT_BGE_TIMEOUT"),
                30.0,
            ),
        )
    )
    query_instruction: str = field(
        default_factory=lambda: _user_str(
            "embedding.query_instruction",
            ("MYCODINGAGENT_EMBEDDING_QUERY_INSTRUCTION", "MYCODINGAGENT_BGE_QUERY_INSTRUCTION"),
            "为这个句子生成表示以用于检索相关文章：",
        )
    )
    normalize: bool = field(
        default_factory=lambda: _user_bool("embedding.normalize", ("MYCODINGAGENT_EMBEDDING_NORMALIZE",), True)
    )
    device: str | None = field(
        default_factory=lambda: _user_str(
            "embedding.device",
            ("MYCODINGAGENT_EMBEDDING_DEVICE", "MYCODINGAGENT_BGE_DEVICE"),
            "",
        ) or None
    )
    batch_size: int = field(
        default_factory=lambda: max(
            1,
            _user_int(
                "embedding.batch_size",
                ("MYCODINGAGENT_EMBEDDING_BATCH_SIZE", "MYCODINGAGENT_BGE_BATCH_SIZE"),
                16,
            ),
        )
    )
    dimension: int = field(
        default_factory=lambda: max(1, _user_int("embedding.dimension", ("MYCODINGAGENT_EMBEDDING_DIMENSION", "MYCODINGAGENT_BGE_DIM"), 1024))
    )
    fallback_to_hash: bool = field(
        default_factory=lambda: _user_bool(
            "embedding.fallback_to_hash",
            ("MYCODINGAGENT_BGE_FALLBACK_TO_HASH",),
            False,
        )
    )
    hash_dimension: int = field(
        default_factory=lambda: _user_int("embedding.hash_dimension", ("MYCODINGAGENT_HASH_EMBEDDING_DIM",), 256)
    )
    request_extra: dict = field(
        default_factory=lambda: _user_dict("embedding.request_extra", ("MYCODINGAGENT_EMBEDDING_REQUEST_EXTRA",), {})
    )
    headers: dict = field(
        default_factory=lambda: _user_dict("embedding.headers", ("MYCODINGAGENT_EMBEDDING_HEADERS",), {})
    )

    # 兼容旧 bge_ 前缀属性
    @property
    def bge_model(self) -> str:
        return self.model

    @property
    def bge_endpoint(self) -> str:
        return self.endpoint

    @property
    def bge_api_format(self) -> str:
        return self.api_format

    @property
    def bge_api_key(self) -> str | None:
        return self.api_key

    @property
    def bge_timeout(self) -> float:
        return self.timeout

    @property
    def bge_query_instruction(self) -> str:
        return self.query_instruction

    @property
    def bge_device(self) -> str | None:
        return self.device

    @property
    def bge_batch_size(self) -> int:
        return self.batch_size

    @property
    def bge_dimension(self) -> int:
        return self.dimension


@dataclass(frozen=True)
class MilvusConfig:
    """Milvus 向量数据库连接配置。"""
    enabled: bool = field(
        default_factory=lambda: _user_bool("milvus.enabled", ("MYCODINGAGENT_MILVUS_ENABLED",), True)
    )
    host: str = field(
        default_factory=lambda: _user_str("milvus.host", ("MYCODINGAGENT_MILVUS_HOST",), "127.0.0.1")
    )
    port: str = field(
        default_factory=lambda: _user_str("milvus.port", ("MYCODINGAGENT_MILVUS_PORT",), "19530")
    )
    collection: str = field(
        default_factory=lambda: _user_str("milvus.collection", ("MYCODINGAGENT_MILVUS_COLLECTION",), "mycodingagent_skills")
    )
    token: str | None = field(
        default_factory=lambda: _user_str("milvus.token", ("MYCODINGAGENT_MILVUS_TOKEN",), "") or None
    )
    recreate_incompatible: bool = field(
        default_factory=lambda: _user_bool("milvus.recreate_incompatible", ("MYCODINGAGENT_MILVUS_RECREATE_INCOMPATIBLE",), True)
    )
    consistency_level: str = field(
        default_factory=lambda: _user_str("milvus.consistency_level", ("MYCODINGAGENT_MILVUS_CONSISTENCY_LEVEL",), "Strong")
    )
    index_type: str = field(
        default_factory=lambda: _user_str("milvus.index_type", ("MYCODINGAGENT_MILVUS_INDEX_TYPE",), "HNSW")
    )
    metric_type: str = field(
        default_factory=lambda: _user_str("milvus.metric_type", ("MYCODINGAGENT_MILVUS_METRIC_TYPE",), "COSINE")
    )
    sparse_metric_type: str = field(
        default_factory=lambda: _user_str("milvus.sparse_metric_type", ("MYCODINGAGENT_MILVUS_SPARSE_METRIC_TYPE",), "BM25")
    )
    sparse_inverted_index_algo: str = field(
        default_factory=lambda: _user_str("milvus.sparse_inverted_index_algo", ("MYCODINGAGENT_MILVUS_SPARSE_ALGO",), "DAAT_MAXSCORE")
    )
    rrf_k: int = field(
        default_factory=lambda: _user_int("milvus.rrf_k", ("MYCODINGAGENT_MILVUS_RRF_K",), 60)
    )
    text_max_bytes: int = field(
        default_factory=lambda: _user_int("milvus.text_max_bytes", ("MYCODINGAGENT_MILVUS_TEXT_MAX_BYTES",), 65535)
    )
    analyzer_params: dict = field(
        default_factory=lambda: _user_dict("milvus.analyzer_params", ("MYCODINGAGENT_MILVUS_ANALYZER_PARAMS",), {"type": "chinese"})
    )

    @property
    def uri(self) -> str:
        from_env = _user_str("milvus.uri", ("MYCODINGAGENT_MILVUS_URI",), "")
        if from_env:
            return from_env
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class MCPConfig:
    """MCP Server 连接与权限配置。"""
    enabled: bool = field(
        default_factory=lambda: _user_bool("mcp.enabled", ("MYCODINGAGENT_MCP_ENABLED",), True)
    )
    project_config_path: Path = field(
        default_factory=lambda: (
            _user_path("mcp.project_config_path", ("MYCODINGAGENT_MCP_PROJECT_CONFIG",))
            or _default_mcp_project_config_path()
        )
    )
    user_config_path: Path = field(
        default_factory=lambda: (
            _user_path("mcp.user_config_path", ("MYCODINGAGENT_MCP_USER_CONFIG",))
            or _default_mcp_user_config_path()
        )
    )
    reconnect_server_step: int = field(
        default_factory=lambda: max(
            1,
            _user_int("mcp.reconnect_server_step", ("MYCODINGAGENT_RECONNECT_MCP_SERVER_STEP", "RECONNECT_MCP_SERVER_STEP"), 10),
        )
    )


@dataclass(frozen=True)
class AppConfig:
    """应用顶层配置，聚合所有子配置模块。"""
    user_id: str = field(default_factory=_default_user_id)
    api: ApiConfig = field(default_factory=ApiConfig)
    client: ClientConfig = field(default_factory=ClientConfig)
    multi_agent: MultiAgentConfig = field(default_factory=MultiAgentConfig)
    long_term_memory: LongTermMemoryConfig = field(default_factory=LongTermMemoryConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    docker: DockerConfig = field(default_factory=DockerConfig)
    skills: SkillConfig = field(default_factory=SkillConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    milvus: MilvusConfig = field(default_factory=MilvusConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)


CONFIG = AppConfig()
