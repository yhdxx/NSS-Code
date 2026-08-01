from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


CONFIG_FILE_ENV = "MYCODINGAGENT_CONFIG"
_MISSING = object()


def _default_user_config_path() -> Path:
    return Path.home() / ".config" / "myCodingAgent" / "config.yaml"


def _default_project_config_path() -> Path:
    return Path(os.getenv("MYCODINGAGENT_SANDBOX_ROOT", os.getcwd())).expanduser() / ".mycodingagent" / "config.yaml"


def _config_file_candidates() -> tuple[Path, ...]:
    paths = [_default_user_config_path(), _default_project_config_path()]
    explicit_paths = os.getenv(CONFIG_FILE_ENV, "")
    if explicit_paths:
        paths.extend(Path(item).expanduser() for item in explicit_paths.split(os.pathsep) if item.strip())
    return tuple(paths)


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_config_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Failed to read configuration file {path}: {exc}") from exc
    if not raw_text.strip():
        return {}

    try:
        if path.suffix.lower() == ".json":
            parsed = json.loads(raw_text)
        else:
            import yaml

            parsed = yaml.safe_load(raw_text)
    except Exception as exc:
        raise RuntimeError(f"Failed to parse configuration file {path}: {exc}") from exc

    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Configuration file {path} must contain a top-level mapping/object.")
    return parsed


def _load_file_config() -> dict:
    config: dict = {}
    for path in _config_file_candidates():
        config = _deep_merge(config, _read_config_file(path))
    return config


_FILE_CONFIG = _load_file_config()


_ENV_CONFIG_PATHS = {
    "DEEPSEEK_API_KEY": "api.deepseek_api_key",
    "DEEPSEEK_BASE_URL": "api.base_url",
    "DEEPSEEK_MODEL": "api.model",
    "DEBUG": "client.debug",
    "MYCODINGAGENT_DEBUG": "client.debug",
    "STEP_TOKEN": "client.step_token",
    "ROUND_TOKEN": "client.round_token",
    "CONVERSATION_TOKEN": "client.conversation_token",
    "MYCODINGAGENT_MAX_TOOL_ROUNDS": "client.max_tool_rounds",
    "MYCODINGAGENT_MAX_DISPLAY_STRING_CHARS": "client.max_display_string_chars",
    "MYCODINGAGENT_MAX_TOOL_OUTPUT_CHARS": "client.max_tool_output_chars",
    "MYCODINGAGENT_API_MAX_RETRIES": "client.api_max_retries",
    "MYCODINGAGENT_API_RETRY_BASE_DELAY": "client.api_retry_base_delay",
    "MYCODINGAGENT_LEGACY_SYSTEM_PROMPT": "client.legacy_system_prompt",
    "MYCODINGAGENT_MULTI_AGENT_MAX_AGENT_ROUNDS": "multi_agent.max_agent_rounds",
    "MYCODINGAGENT_MULTI_AGENT_MAX_PARALLEL_TASKS": "multi_agent.max_parallel_tasks",
    "MYCODINGAGENT_LONG_TERM_MEMORY_ENABLED": "long_term_memory.enabled",
    "MYCODINGAGENT_LONG_TERM_MEMORY_STORAGE_MODEL": "long_term_memory.storage_model",
    "MYCODINGAGENT_LONG_TERM_MEMORY_QUERY_MODEL": "long_term_memory.query_model",
    "MYCODINGAGENT_LONG_TERM_MEMORY_QUERY_RECENT_TURNS": "long_term_memory.query_recent_turns",
    "MYCODINGAGENT_LONG_TERM_MEMORY_MAX_MEMORIES": "long_term_memory.max_memories",
    "MYCODINGAGENT_LONG_TERM_MEMORY_MAX_WORKFLOW_CANDIDATES": "long_term_memory.max_workflow_candidates",
    "MYCODINGAGENT_LONG_TERM_MEMORY_MAX_SKILL_CANDIDATES": "long_term_memory.max_skill_candidates",
    "MYCODINGAGENT_LONG_TERM_MEMORY_SKILL_SUCCESS_THRESHOLD": "long_term_memory.skill_candidate_success_threshold",
    "MYCODINGAGENT_LONG_TERM_MEMORY_SKILL_PROMPT_COOLDOWN_DAYS": "long_term_memory.skill_candidate_prompt_cooldown_days",
    "MYCODINGAGENT_LONG_TERM_MEMORY_LOCK_TTL_SECONDS": "long_term_memory.lock_ttl_seconds",
    "MYCODINGAGENT_LONG_TERM_MEMORY_GRACEFUL_EXIT_TIMEOUT_SECONDS": "long_term_memory.graceful_exit_extract_timeout_seconds",
    "MYCODINGAGENT_LONG_TERM_MEMORY_STARTUP_BACKFILL_ENABLED": "long_term_memory.startup_backfill_enabled",
    "MYCODINGAGENT_MEMORY_ENABLED": "memory.enabled",
    "OUTPUT_CONTEXT_COMPRESSION": "memory.output_context_compression",
    "MYCODINGAGENT_STATE_DIR": "memory.state_dir",
    "MYCODINGAGENT_MEMORY_DB_PATH": "memory.db_path",
    "MYCODINGAGENT_MEMORY_SUMMARY_PROMPT": "memory.prompt_path",
    "MYCODINGAGENT_MODEL_CONTEXT_WINDOW": "memory.default_context_window",
    "MYCODINGAGENT_MEMORY_SESSION_TTL_DAYS": "memory.session_ttl_days",
    "MYCODINGAGENT_DEFAULT_WORK_MODE": "memory.default_work_mode",
    "MYCODINGAGENT_MEMORY_WORKSPACE_SNAPSHOT_TTL_DAYS": "memory.workspace_snapshot_ttl_days",
    "MYCODINGAGENT_MEMORY_TOOL_PREVIEW_CHARS": "memory.tool_preview_chars",
    "MYCODINGAGENT_CONTEXT_PREVIEW_THRESHOLD_TOKENS": "memory.context_preview_threshold_tokens",
    "MYCODINGAGENT_CONTEXT_PREVIEW_TOKENS": "memory.context_preview_tokens",
    "MYCODINGAGENT_RAW_TOOL_OUTPUT_PREVIEW_CHARS": "memory.raw_tool_output_preview_chars",
    "MYCODINGAGENT_RAW_TO_VIRTUALIZED_RATIO": "memory.raw_to_virtualized_ratio",
    "MYCODINGAGENT_BUDGET_SOFT_RATIO": "memory.budget_soft_ratio",
    "MYCODINGAGENT_BUDGET_WORKING_RATIO": "memory.budget_working_ratio",
    "MYCODINGAGENT_BUDGET_EMERGENCY_RATIO": "memory.budget_emergency_ratio",
    "MYCODINGAGENT_HOT_CONTEXT_WARNING_RATIO": "memory.hot_context_warning_ratio",
    "MYCODINGAGENT_HOT_CONTEXT_FORCE_RATIO": "memory.hot_context_force_ratio",
    "MYCODINGAGENT_HOT_CONTEXT_RETAINED_TURNS": "memory.hot_context_retained_turns",
    "MYCODINGAGENT_HOT_CONTEXT_TOPIC_DRIFT_TURNS": "memory.hot_context_topic_drift_turns",
    "MYCODINGAGENT_HOT_CONTEXT_TOPIC_SIMILARITY_THRESHOLD": "memory.hot_context_topic_similarity_threshold",
    "MYCODINGAGENT_ARCHIVE_COLD_CONTEXT_RATIO": "memory.archive_cold_context_ratio",
    "MYCODINGAGENT_CURRENT_TURN_SUMMARY_MAX_PER_MESSAGE": "memory.current_turn_summary_max_per_message",
    "MYCODINGAGENT_CURRENT_TURN_SUMMARY_MAX_PER_TURN": "memory.current_turn_summary_max_per_turn",
    "MYCODINGAGENT_CHECKPOINT_ENABLED": "memory.checkpoint_enabled",
    "MYCODINGAGENT_CHECKPOINT_SOFT_RATIO": "memory.checkpoint_soft_ratio",
    "MYCODINGAGENT_CHECKPOINT_HARD_RATIO": "memory.checkpoint_hard_ratio",
    "MYCODINGAGENT_SNAPSHOT_VERSION": "memory.snapshot_version",
    "MYCODINGAGENT_CHECKPOINT_MIN_TURNS_BETWEEN_ROLLOVERS": "memory.checkpoint_min_turns_between_rollovers",
    "MYCODINGAGENT_CHECKPOINT_RECENT_DELTA_TURNS": "memory.checkpoint_recent_delta_turns",
    "MYCODINGAGENT_RESERVED_REASONING_TOKENS": "memory.reserved_reasoning_tokens",
    "MYCODINGAGENT_RESERVED_OUTPUT_TOKENS": "memory.reserved_output_tokens",
    "MYCODINGAGENT_RESERVED_TOOL_TOKENS": "memory.reserved_tool_tokens",
    "MYCODINGAGENT_CONTEXT_STORE_BACKEND": "memory.context_store_backend",
    "MYCODINGAGENT_MEMORY_RECENT_ROUNDS": "memory.recent_rounds_for_average",
    "MYCODINGAGENT_MEMORY_RECENT_MESSAGES_AFTER_SUMMARY": "memory.recent_messages_after_summary",
    "MYCODINGAGENT_MODEL_CONTEXT_WINDOWS": "memory.model_context_windows",
    "MYCODINGAGENT_SANDBOX_ROOT": "sandbox.root",
    "MYCODINGAGENT_MAX_OUTPUT_CHARS": "sandbox.max_output_chars",
    "MYCODINGAGENT_WORKSPACE_LEASE_ENABLED": "sandbox.workspace_lease_enabled",
    "MYCODINGAGENT_DOCKER_IMAGE": "docker.image",
    "MYCODINGAGENT_DOCKER_NETWORK": "docker.network",
    "MYCODINGAGENT_DOCKER_BUILD_NETWORK": "docker.build_network",
    "MYCODINGAGENT_DOCKER_CPUS": "docker.cpus",
    "MYCODINGAGENT_DOCKER_MEMORY": "docker.memory",
    "MYCODINGAGENT_DOCKER_PIDS_LIMIT": "docker.pids_limit",
    "MYCODINGAGENT_DOCKER_DEFAULT_TIMEOUT": "docker.default_timeout",
    "MYCODINGAGENT_DOCKER_MAX_TIMEOUT": "docker.max_timeout",
    "MYCODINGAGENT_DOCKER_CHECK_TIMEOUT": "docker.check_timeout",
    "MYCODINGAGENT_DOCKER_PULL_TIMEOUT": "docker.pull_timeout",
    "MYCODINGAGENT_BUILTIN_SKILLS_ROOT": "skills.builtin_root",
    "MYCODINGAGENT_WORKSPACE_SKILLS_ROOT": "skills.workspace_root",
    "MYCODINGAGENT_SKILLS_ROOT": "skills.workspace_root",
    "MYCODINGAGENT_EXTRA_SKILLS_ROOTS": "skills.extra_roots",
    "MYCODINGAGENT_SKILL_MARKDOWN_NAME": "skills.markdown_filename",
    "MYCODINGAGENT_SKILL_JSON_SUFFIX": "skills.json_suffix",
    "MYCODINGAGENT_USER_ID": "skills.user_id",
    "MYCODINGAGENT_DEFAULT_SKILLS": "skills.default_tool_names",
    "MYCODINGAGENT_SKILL_SMALL_COUNT": "skills.small_count",
    "MYCODINGAGENT_SKILL_PREFETCH_TOP_K": "skills.prefetch_top_k",
    "MYCODINGAGENT_SKILL_SEARCH_TOP_K": "skills.search_top_k",
    "MYCODINGAGENT_SKILL_MIN_SCORE": "skills.min_score",
    "MYCODINGAGENT_SKILL_INDEX_DIR": "skills.index_dir",
    "MYCODINGAGENT_SKILL_WATCH_POLL_INTERVAL": "skills.watcher_poll_interval",
    "MYCODINGAGENT_SKILL_ROUTER_TOP_N": "skills.router_top_n",
    "MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_TOP_K": "skills.router_retrieval_top_k",
    "MYCODINGAGENT_SKILL_ROUTER_CACHE_TOP_K": "skills.router_cache_top_k",
    "MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_MIN_RATIO": "skills.router_retrieval_min_ratio",
    "MYCODINGAGENT_SKILL_ROUTER_USER_WEIGHT": "skills.router_user_weight",
    "MYCODINGAGENT_SKILL_ROUTER_SESSION_WEIGHT": "skills.router_session_weight",
    "MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_WEIGHT": "skills.router_retrieval_weight",
    "MYCODINGAGENT_SKILL_ROUTER_PINNED_BONUS": "skills.router_pinned_bonus",
    "MYCODINGAGENT_SKILL_LRFU_DECAY": "skills.lrfu_decay",
    "MYCODINGAGENT_SKILL_CALL_REWARD": "skills.skill_call_reward",
    "MYCODINGAGENT_SKILL_SESSION_ACTIVATION_REWARD": "skills.session_activation_reward",
    "MYCODINGAGENT_USER_SKILL_CACHE_MAX_ENTRIES": "skills.user_skill_cache_max_entries",
    "MYCODINGAGENT_SESSION_SKILL_CACHE_MAX_ENTRIES": "skills.session_skill_cache_max_entries",
    "OUTPUT_RECALL_SKILL": "skills.output_recall_skill",
    "MYCODINGAGENT_SKILL_VECTOR_SYNC_BATCH_SIZE": "skills.vector_sync_batch_size",
    "MYCODINGAGENT_SKILL_VECTOR_SYNC_MAX_RETRIES": "skills.vector_sync_max_retries",
    "MYCODINGAGENT_EMBEDDING_PROVIDER": "embedding.provider",
    "MYCODINGAGENT_EMBEDDING_MODEL": "embedding.model",
    "MYCODINGAGENT_EMBEDDING_ENDPOINT": "embedding.endpoint",
    "MYCODINGAGENT_EMBEDDING_API_FORMAT": "embedding.api_format",
    "MYCODINGAGENT_EMBEDDING_API_KEY": "embedding.api_key",
    "MYCODINGAGENT_EMBEDDING_TIMEOUT": "embedding.timeout",
    "MYCODINGAGENT_EMBEDDING_QUERY_INSTRUCTION": "embedding.query_instruction",
    "MYCODINGAGENT_EMBEDDING_DEVICE": "embedding.device",
    "MYCODINGAGENT_EMBEDDING_BATCH_SIZE": "embedding.batch_size",
    "MYCODINGAGENT_EMBEDDING_DIM": "embedding.dimension",
    "MYCODINGAGENT_EMBEDDING_REQUEST_EXTRA": "embedding.request_extra",
    "MYCODINGAGENT_EMBEDDING_HEADERS": "embedding.headers",
    "MYCODINGAGENT_EMBEDDING_FALLBACK_TO_HASH": "embedding.fallback_to_hash",
    "MYCODINGAGENT_BGE_MODEL": "embedding.bge_model",
    "MYCODINGAGENT_BGE_ENDPOINT": "embedding.bge_endpoint",
    "MYCODINGAGENT_BGE_API_FORMAT": "embedding.bge_api_format",
    "MYCODINGAGENT_BGE_API_KEY": "embedding.bge_api_key",
    "MYCODINGAGENT_BGE_TIMEOUT": "embedding.bge_timeout",
    "MYCODINGAGENT_BGE_QUERY_INSTRUCTION": "embedding.bge_query_instruction",
    "MYCODINGAGENT_BGE_DEVICE": "embedding.bge_device",
    "MYCODINGAGENT_BGE_BATCH_SIZE": "embedding.bge_batch_size",
    "MYCODINGAGENT_BGE_DIM": "embedding.bge_dimension",
    "MYCODINGAGENT_BGE_FALLBACK_TO_HASH": "embedding.fallback_to_hash",
    "MYCODINGAGENT_HASH_EMBEDDING_DIM": "embedding.hash_dimension",
    "MYCODINGAGENT_MILVUS_ENABLED": "milvus.enabled",
    "MYCODINGAGENT_MILVUS_HOST": "milvus.host",
    "MYCODINGAGENT_MILVUS_PORT": "milvus.port",
    "MYCODINGAGENT_MILVUS_URI": "milvus.uri",
    "MYCODINGAGENT_MILVUS_COLLECTION": "milvus.collection",
    "MYCODINGAGENT_MILVUS_TOKEN": "milvus.token",
    "MYCODINGAGENT_MILVUS_RECREATE_INCOMPATIBLE": "milvus.recreate_incompatible",
    "MYCODINGAGENT_MILVUS_DENSE_INDEX_TYPE": "milvus.dense_index_type",
    "MYCODINGAGENT_MILVUS_DENSE_METRIC_TYPE": "milvus.dense_metric_type",
    "MYCODINGAGENT_MILVUS_HNSW_M": "milvus.hnsw_m",
    "MYCODINGAGENT_MILVUS_HNSW_EF_CONSTRUCTION": "milvus.hnsw_ef_construction",
    "MYCODINGAGENT_MILVUS_HNSW_EF": "milvus.hnsw_ef",
    "MYCODINGAGENT_MILVUS_SPARSE_INDEX_TYPE": "milvus.sparse_index_type",
    "MYCODINGAGENT_MILVUS_SPARSE_METRIC_TYPE": "milvus.sparse_metric_type",
    "MYCODINGAGENT_MILVUS_SPARSE_ALGO": "milvus.sparse_inverted_index_algo",
    "MYCODINGAGENT_MILVUS_RRF_K": "milvus.rrf_k",
    "MYCODINGAGENT_MILVUS_TEXT_MAX_BYTES": "milvus.text_max_bytes",
    "MYCODINGAGENT_MILVUS_ANALYZER_PARAMS": "milvus.analyzer_params",
    "MYCODINGAGENT_MCP_ENABLED": "mcp.enabled",
    "MYCODINGAGENT_MCP_PROJECT_CONFIG": "mcp.project_config_path",
    "MYCODINGAGENT_MCP_USER_CONFIG": "mcp.user_config_path",
    "MYCODINGAGENT_RECONNECT_MCP_SERVER_STEP": "mcp.reconnect_server_step",
    "RECONNECT_MCP_SERVER_STEP": "mcp.reconnect_server_step",
}


def _config_value(path: str | None) -> object:
    if not path:
        return _MISSING
    current: object = _FILE_CONFIG
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _raw_setting(name: str) -> object:
    raw_value = os.getenv(name)
    if raw_value is not None:
        return raw_value
    return _config_value(_ENV_CONFIG_PATHS.get(name))


def _alias_raw(env_names: tuple[str, ...], config_paths: tuple[str, ...]) -> object:
    for name in env_names:
        raw_value = os.getenv(name)
        if raw_value is not None:
            return raw_value
    for path in config_paths:
        raw_value = _config_value(path)
        if raw_value is not _MISSING:
            return raw_value
    return _MISSING


def _alias_str(env_names: tuple[str, ...], config_paths: tuple[str, ...], default: str) -> str:
    raw_value = _alias_raw(env_names, config_paths)
    if raw_value is _MISSING or raw_value is None:
        return default
    return str(raw_value)


def _alias_int(env_names: tuple[str, ...], config_paths: tuple[str, ...], default: int) -> int:
    raw_value = _alias_raw(env_names, config_paths)
    if raw_value is _MISSING or raw_value is None:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def _alias_float(env_names: tuple[str, ...], config_paths: tuple[str, ...], default: float) -> float:
    raw_value = _alias_raw(env_names, config_paths)
    if raw_value is _MISSING or raw_value is None:
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


def _alias_bool(env_names: tuple[str, ...], config_paths: tuple[str, ...], default: bool) -> bool:
    raw_value = _alias_raw(env_names, config_paths)
    if raw_value is _MISSING or raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _alias_json_dict(env_names: tuple[str, ...], config_paths: tuple[str, ...], default: dict) -> dict:
    raw_value = _alias_raw(env_names, config_paths)
    if raw_value is _MISSING or raw_value is None or raw_value == "":
        return default
    if isinstance(raw_value, dict):
        return raw_value
    try:
        value = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return default
    return value if isinstance(value, dict) else default


def _env_str(name: str, default: str) -> str:
    raw_value = _raw_setting(name)
    if raw_value is _MISSING or raw_value is None:
        return default
    return str(raw_value)


def _env_int(name: str, default: int) -> int:
    raw_value = _raw_setting(name)
    if raw_value is _MISSING or raw_value is None:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw_value = _raw_setting(name)
    if raw_value is _MISSING or raw_value is None:
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw_value = _raw_setting(name)
    if raw_value is _MISSING or raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_path(name: str, default: Path | None = None) -> Path | None:
    raw_value = _raw_setting(name)
    if raw_value is _MISSING or raw_value is None or raw_value == "":
        return default
    return Path(str(raw_value)).expanduser()


def _env_paths(name: str) -> tuple[Path, ...]:
    raw_value = _raw_setting(name)
    if raw_value is _MISSING or raw_value is None or raw_value == "":
        return ()
    if isinstance(raw_value, list):
        return tuple(Path(str(item)).expanduser() for item in raw_value if str(item).strip())
    return tuple(Path(item).expanduser() for item in str(raw_value).split(os.pathsep) if item.strip())


def _env_list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw_value = _raw_setting(name)
    if raw_value is _MISSING or raw_value is None or raw_value == "":
        return default
    if isinstance(raw_value, list):
        return tuple(str(item).strip() for item in raw_value if str(item).strip())
    return tuple(item.strip() for item in str(raw_value).split(",") if item.strip())


def _default_user_id() -> str:
    return (
        _env_str("MYCODINGAGENT_USER_ID", "")
        or os.getenv("USER")
        or os.getenv("USERNAME")
        or "default_user"
    )


def _env_json_dict(name: str, default: dict) -> dict:
    raw_value = _raw_setting(name)
    if raw_value is _MISSING or raw_value is None or raw_value == "":
        return default
    if isinstance(raw_value, dict):
        return raw_value
    try:
        value = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return default
    return value if isinstance(value, dict) else default


def _default_embedding_api_format() -> str:
    provider = _env_str("MYCODINGAGENT_EMBEDDING_PROVIDER", "bge_http").strip().lower()
    if provider in {"openai", "openai_compatible", "openai-compatible"}:
        return "openai"
    if provider == "dashscope":
        return "dashscope"
    return "ollama"


def _default_builtin_skills_root() -> Path:
    return Path(__file__).resolve().parents[2] / "skills"


def _default_workspace_skills_root() -> Path:
    raw_root = (
        _env_str("MYCODINGAGENT_WORKSPACE_SKILLS_ROOT", "")
        or _env_str("MYCODINGAGENT_SKILLS_ROOT", "")
    )
    if raw_root:
        return Path(raw_root).expanduser()
    return Path(_env_str("MYCODINGAGENT_SANDBOX_ROOT", os.getcwd())).expanduser() / "skills"


def _default_memory_db_path() -> Path:
    state_dir = _env_str("MYCODINGAGENT_STATE_DIR", "")
    if state_dir:
        return Path(state_dir).expanduser() / "sessions.sqlite3"
    xdg_state_home = os.getenv("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "myCodingAgent" / "sessions.sqlite3"
    return Path.home() / ".local" / "state" / "myCodingAgent" / "sessions.sqlite3"


def _default_mcp_user_config_path() -> Path:
    return Path.home() / ".config" / "myCodingAgent" / "mcp.json"


def _default_mcp_project_config_path() -> Path:
    return Path(_env_str("MYCODINGAGENT_SANDBOX_ROOT", os.getcwd())).expanduser() / ".mycodingagent" / "mcp.json"


def _dedupe_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path.expanduser().resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return tuple(result)


@dataclass(frozen=True)
class ApiConfig:
    deepseek_api_key: str = field(
        default_factory=lambda: _env_str("DEEPSEEK_API_KEY", "")  # 密钥默认不在仓库中保留；优先使用环境变量覆盖本地配置。
    )
    base_url: str = field(default_factory=lambda: _env_str("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    model: str = field(default_factory=lambda: _env_str("DEEPSEEK_MODEL", "deepseek-v4-pro"))


@dataclass(frozen=True)
class ClientConfig:
    max_tool_rounds: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MAX_TOOL_ROUNDS", 50))
    max_display_string_chars: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_MAX_DISPLAY_STRING_CHARS", 12000)
    )
    max_tool_output_chars: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MAX_TOOL_OUTPUT_CHARS", 12000))
    api_max_retries: int = field(default_factory=lambda: max(0, _env_int("MYCODINGAGENT_API_MAX_RETRIES", 3)))
    api_retry_base_delay: float = field(
        default_factory=lambda: max(0.0, _env_float("MYCODINGAGENT_API_RETRY_BASE_DELAY", 1.0))
    )
    multiline_argument_fields: frozenset[str] = frozenset({"command", "content", "old_string", "new_string"})
    debug: bool = field(default_factory=lambda: _env_bool("DEBUG", _env_bool("MYCODINGAGENT_DEBUG", False)))
    step_token: bool = field(default_factory=lambda: _env_bool("STEP_TOKEN", True))
    round_token: bool = field(default_factory=lambda: _env_bool("ROUND_TOKEN", True))
    conversation_token: bool = field(default_factory=lambda: _env_bool("CONVERSATION_TOKEN", True))
    legacy_system_prompt: bool = field(
        default_factory=lambda: _env_bool("MYCODINGAGENT_LEGACY_SYSTEM_PROMPT", False)
    )


@dataclass(frozen=True)
class MultiAgentConfig:
    max_agent_rounds: int = field(
        default_factory=lambda: max(1, _env_int("MYCODINGAGENT_MULTI_AGENT_MAX_AGENT_ROUNDS", 50))
    )
    max_parallel_tasks: int = field(
        default_factory=lambda: max(1, _env_int("MYCODINGAGENT_MULTI_AGENT_MAX_PARALLEL_TASKS", 5))
    )


@dataclass(frozen=True)
class LongTermMemoryConfig:
    enabled: bool = field(default_factory=lambda: _env_bool("MYCODINGAGENT_LONG_TERM_MEMORY_ENABLED", True))
    storage_model: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_LONG_TERM_MEMORY_STORAGE_MODEL", ""))
    query_model: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_LONG_TERM_MEMORY_QUERY_MODEL", ""))
    query_recent_turns: int = field(
        default_factory=lambda: max(1, _env_int("MYCODINGAGENT_LONG_TERM_MEMORY_QUERY_RECENT_TURNS", 5))
    )
    max_memories: int = field(
        default_factory=lambda: max(1, _env_int("MYCODINGAGENT_LONG_TERM_MEMORY_MAX_MEMORIES", 8))
    )
    max_workflow_candidates: int = field(
        default_factory=lambda: max(0, _env_int("MYCODINGAGENT_LONG_TERM_MEMORY_MAX_WORKFLOW_CANDIDATES", 3))
    )
    max_skill_candidates: int = field(
        default_factory=lambda: max(0, _env_int("MYCODINGAGENT_LONG_TERM_MEMORY_MAX_SKILL_CANDIDATES", 2))
    )
    skill_candidate_success_threshold: int = field(
        default_factory=lambda: max(1, _env_int("MYCODINGAGENT_LONG_TERM_MEMORY_SKILL_SUCCESS_THRESHOLD", 2))
    )
    skill_candidate_prompt_cooldown_days: int = field(
        default_factory=lambda: max(0, _env_int("MYCODINGAGENT_LONG_TERM_MEMORY_SKILL_PROMPT_COOLDOWN_DAYS", 7))
    )
    lock_ttl_seconds: int = field(
        default_factory=lambda: max(1, _env_int("MYCODINGAGENT_LONG_TERM_MEMORY_LOCK_TTL_SECONDS", 600))
    )
    graceful_exit_extract_timeout_seconds: int = field(
        default_factory=lambda: max(
            1,
            _env_int("MYCODINGAGENT_LONG_TERM_MEMORY_GRACEFUL_EXIT_TIMEOUT_SECONDS", 30),
        )
    )
    startup_backfill_enabled: bool = field(
        default_factory=lambda: _env_bool("MYCODINGAGENT_LONG_TERM_MEMORY_STARTUP_BACKFILL_ENABLED", True)
    )


@dataclass(frozen=True)
class MemoryConfig:
    enabled: bool = field(default_factory=lambda: _env_bool("MYCODINGAGENT_MEMORY_ENABLED", True))
    output_context_compression: bool = field(default_factory=lambda: _env_bool("OUTPUT_CONTEXT_COMPRESSION", True))
    db_path: Path = field(default_factory=lambda: _env_path("MYCODINGAGENT_MEMORY_DB_PATH", _default_memory_db_path()) or _default_memory_db_path())
    prompt_path: Path | None = field(default_factory=lambda: _env_path("MYCODINGAGENT_MEMORY_SUMMARY_PROMPT"))
    default_context_window: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MODEL_CONTEXT_WINDOW", 1_000_000))
    session_ttl_days: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MEMORY_SESSION_TTL_DAYS", 30))
    default_work_mode: str = field(
        default_factory=lambda: (
            _env_str("MYCODINGAGENT_DEFAULT_WORK_MODE", "general").strip().lower()
            if _env_str("MYCODINGAGENT_DEFAULT_WORK_MODE", "general").strip().lower() in {"general", "code"}
            else "general"
        )
    )
    workspace_snapshot_ttl_days: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_MEMORY_WORKSPACE_SNAPSHOT_TTL_DAYS", 30)
    )
    tool_preview_chars: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MEMORY_TOOL_PREVIEW_CHARS", 2000))
    context_preview_threshold_tokens: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_CONTEXT_PREVIEW_THRESHOLD_TOKENS", 12000)
    )
    context_preview_tokens: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_CONTEXT_PREVIEW_TOKENS", 2000))
    raw_tool_output_preview_chars: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_RAW_TOOL_OUTPUT_PREVIEW_CHARS", 1000)
    )
    raw_to_virtualized_ratio: float = field(
        default_factory=lambda: _env_float("MYCODINGAGENT_RAW_TO_VIRTUALIZED_RATIO", 0.60)
    )
    budget_soft_ratio: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_BUDGET_SOFT_RATIO", 0.60))
    budget_working_ratio: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_BUDGET_WORKING_RATIO", 0.80))
    budget_emergency_ratio: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_BUDGET_EMERGENCY_RATIO", 0.90))
    hot_context_warning_ratio: float = field(
        default_factory=lambda: _env_float("MYCODINGAGENT_HOT_CONTEXT_WARNING_RATIO", 0.30)
    )
    hot_context_force_ratio: float = field(
        default_factory=lambda: _env_float("MYCODINGAGENT_HOT_CONTEXT_FORCE_RATIO", 0.40)
    )
    hot_context_retained_turns: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_HOT_CONTEXT_RETAINED_TURNS", 3)
    )
    hot_context_topic_drift_turns: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_HOT_CONTEXT_TOPIC_DRIFT_TURNS", 3)
    )
    hot_context_topic_similarity_threshold: float = field(
        default_factory=lambda: _env_float("MYCODINGAGENT_HOT_CONTEXT_TOPIC_SIMILARITY_THRESHOLD", 0.12)
    )
    archive_cold_context_ratio: float = field(
        default_factory=lambda: _env_float("MYCODINGAGENT_ARCHIVE_COLD_CONTEXT_RATIO", 0.50)
    )
    current_turn_summary_max_per_message: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_CURRENT_TURN_SUMMARY_MAX_PER_MESSAGE", 2)
    )
    current_turn_summary_max_per_turn: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_CURRENT_TURN_SUMMARY_MAX_PER_TURN", 5)
    )
    checkpoint_enabled: bool = field(default_factory=lambda: _env_bool("MYCODINGAGENT_CHECKPOINT_ENABLED", True))
    checkpoint_soft_ratio: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_CHECKPOINT_SOFT_RATIO", 0.60))
    checkpoint_hard_ratio: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_CHECKPOINT_HARD_RATIO", 0.85))
    snapshot_version: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_SNAPSHOT_VERSION", "1.0"))
    checkpoint_min_turns_between_rollovers: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_CHECKPOINT_MIN_TURNS_BETWEEN_ROLLOVERS", 3)
    )
    checkpoint_recent_delta_turns: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_CHECKPOINT_RECENT_DELTA_TURNS", 20)
    )
    reserved_reasoning_tokens: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_RESERVED_REASONING_TOKENS", 8000)
    )
    reserved_output_tokens: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_RESERVED_OUTPUT_TOKENS", 4000))
    reserved_tool_tokens: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_RESERVED_TOOL_TOKENS", 12000))
    context_store_backend: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_CONTEXT_STORE_BACKEND", "sqlite"))
    recent_rounds_for_average: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MEMORY_RECENT_ROUNDS", 20))
    recent_messages_after_summary: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MEMORY_RECENT_MESSAGES_AFTER_SUMMARY", 12))
    model_context_windows: dict = field(
        default_factory=lambda: _env_json_dict(
            "MYCODINGAGENT_MODEL_CONTEXT_WINDOWS",
            {
                "deepseek-v4-flash": 1_000_000,
            },
        )
    )

    def context_window_for(self, model: str) -> int:
        value = self.model_context_windows.get(model)
        if isinstance(value, int) and value > 0:
            return value
        return self.default_context_window


@dataclass(frozen=True)
class SandboxConfig:
    root_env: str = "MYCODINGAGENT_SANDBOX_ROOT"
    root: Path = field(default_factory=lambda: Path(_env_str("MYCODINGAGENT_SANDBOX_ROOT", os.getcwd())))
    docker_workspace_alias: Path = Path("/workspace")
    max_output_chars: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MAX_OUTPUT_CHARS", 10000))
    workspace_lease_enabled: bool = field(
        default_factory=lambda: _env_bool("MYCODINGAGENT_WORKSPACE_LEASE_ENABLED", True)
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
    image_env: str = "MYCODINGAGENT_DOCKER_IMAGE"
    network_env: str = "MYCODINGAGENT_DOCKER_NETWORK"
    build_network_env: str = "MYCODINGAGENT_DOCKER_BUILD_NETWORK"
    cpus_env: str = "MYCODINGAGENT_DOCKER_CPUS"
    memory_env: str = "MYCODINGAGENT_DOCKER_MEMORY"
    pids_limit_env: str = "MYCODINGAGENT_DOCKER_PIDS_LIMIT"
    pull_timeout_env: str = "MYCODINGAGENT_DOCKER_PULL_TIMEOUT"
    image: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_DOCKER_IMAGE", "mycodingagent-sandbox:py312"))
    network: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_DOCKER_NETWORK", "none"))
    build_network: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_DOCKER_BUILD_NETWORK", "host"))
    cpus: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_DOCKER_CPUS", "2"))
    memory: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_DOCKER_MEMORY", "1g"))
    pids_limit: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_DOCKER_PIDS_LIMIT", "256"))
    default_timeout: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_DOCKER_DEFAULT_TIMEOUT", 120))
    max_timeout: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_DOCKER_MAX_TIMEOUT", 600))
    check_timeout: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_DOCKER_CHECK_TIMEOUT", 10))
    pull_timeout: int = field(default_factory=lambda: max(1, _env_int("MYCODINGAGENT_DOCKER_PULL_TIMEOUT", 1800)))


@dataclass(frozen=True)
class SkillConfig:
    builtin_root: Path = field(
        default_factory=lambda: _env_path("MYCODINGAGENT_BUILTIN_SKILLS_ROOT", _default_builtin_skills_root())
        or _default_builtin_skills_root()
    )
    workspace_root: Path = field(default_factory=_default_workspace_skills_root)
    extra_roots: tuple[Path, ...] = field(default_factory=lambda: _env_paths("MYCODINGAGENT_EXTRA_SKILLS_ROOTS"))
    markdown_filename: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_SKILL_MARKDOWN_NAME", "SKILL.md"))
    json_suffix: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_SKILL_JSON_SUFFIX", ".skill.json"))
    skip_dirs: frozenset[str] = frozenset({"__pycache__", ".skill_runtime", ".git", ".venv"})
    small_count: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_SKILL_SMALL_COUNT", 8))
    default_tool_names: tuple[str, ...] = field(
        default_factory=lambda: _env_list("MYCODINGAGENT_DEFAULT_SKILLS", ("coding-standards",))
    )
    prefetch_top_k: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_SKILL_PREFETCH_TOP_K", 3))
    search_top_k: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_SKILL_SEARCH_TOP_K", 8))
    min_score: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_SKILL_MIN_SCORE", 0.18))
    index_dir: Path | None = field(default_factory=lambda: _env_path("MYCODINGAGENT_SKILL_INDEX_DIR"))
    watcher_poll_interval: float = field(
        default_factory=lambda: _env_float("MYCODINGAGENT_SKILL_WATCH_POLL_INTERVAL", 2.0)
    )
    user_id: str = field(default_factory=_default_user_id)
    router_top_n: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_SKILL_ROUTER_TOP_N", 10))
    router_retrieval_top_k: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_TOP_K", 40)
    )
    router_cache_top_k: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_SKILL_ROUTER_CACHE_TOP_K", 40))
    router_retrieval_min_ratio: float = field(
        default_factory=lambda: _env_float("MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_MIN_RATIO", 0.4)
    )
    router_user_weight: float = field(
        default_factory=lambda: _env_float("MYCODINGAGENT_SKILL_ROUTER_USER_WEIGHT", 0.15)
    )
    router_session_weight: float = field(
        default_factory=lambda: _env_float("MYCODINGAGENT_SKILL_ROUTER_SESSION_WEIGHT", 0.45)
    )
    router_retrieval_weight: float = field(
        default_factory=lambda: _env_float("MYCODINGAGENT_SKILL_ROUTER_RETRIEVAL_WEIGHT", 0.40)
    )
    router_pinned_bonus: float = field(
        default_factory=lambda: _env_float("MYCODINGAGENT_SKILL_ROUTER_PINNED_BONUS", 1.0)
    )
    lrfu_decay: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_SKILL_LRFU_DECAY", 0.95))
    skill_call_reward: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_SKILL_CALL_REWARD", 1.0))
    session_activation_reward: float = field(
        default_factory=lambda: _env_float("MYCODINGAGENT_SKILL_SESSION_ACTIVATION_REWARD", 0.3)
    )
    user_skill_cache_max_entries: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_USER_SKILL_CACHE_MAX_ENTRIES", 1000)
    )
    session_skill_cache_max_entries: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_SESSION_SKILL_CACHE_MAX_ENTRIES", 200)
    )
    output_recall_skill: bool = field(
        default_factory=lambda: _env_bool("OUTPUT_RECALL_SKILL", False)
    )
    vector_sync_batch_size: int = field(
        default_factory=lambda: max(1, _env_int("MYCODINGAGENT_SKILL_VECTOR_SYNC_BATCH_SIZE", 2))
    )
    vector_sync_max_retries: int = field(
        default_factory=lambda: max(1, _env_int("MYCODINGAGENT_SKILL_VECTOR_SYNC_MAX_RETRIES", 3))
    )

    @property
    def root(self) -> Path:
        return self.builtin_root

    @property
    def roots(self) -> tuple[Path, ...]:
        return _dedupe_paths((self.builtin_root, *self.extra_roots))


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_EMBEDDING_PROVIDER", "bge_http"))
    model: str = field(
        default_factory=lambda: _alias_str(
            ("MYCODINGAGENT_EMBEDDING_MODEL", "MYCODINGAGENT_BGE_MODEL"),
            ("embedding.model", "embedding.bge_model"),
            "bge-m3",
        )
    )
    endpoint: str = field(
        default_factory=lambda: _alias_str(
            ("MYCODINGAGENT_EMBEDDING_ENDPOINT", "MYCODINGAGENT_BGE_ENDPOINT"),
            ("embedding.endpoint", "embedding.bge_endpoint"),
            "http://127.0.0.1:11434/api/embed",
        )
    )
    api_format: str = field(
        default_factory=lambda: _alias_str(
            ("MYCODINGAGENT_EMBEDDING_API_FORMAT", "MYCODINGAGENT_BGE_API_FORMAT"),
            ("embedding.api_format", "embedding.bge_api_format"),
            _default_embedding_api_format(),
        )
    )
    api_key: str | None = field(
        default_factory=lambda: _alias_str(
            ("MYCODINGAGENT_EMBEDDING_API_KEY", "MYCODINGAGENT_BGE_API_KEY"),
            ("embedding.api_key", "embedding.bge_api_key"),
            "",
        ) or None
    )
    timeout: float = field(
        default_factory=lambda: max(
            0.1,
            _alias_float(
                ("MYCODINGAGENT_EMBEDDING_TIMEOUT", "MYCODINGAGENT_BGE_TIMEOUT"),
                ("embedding.timeout", "embedding.bge_timeout"),
                30.0,
            ),
        )
    )
    query_instruction: str = field(
        default_factory=lambda: _alias_str(
            ("MYCODINGAGENT_EMBEDDING_QUERY_INSTRUCTION", "MYCODINGAGENT_BGE_QUERY_INSTRUCTION"),
            ("embedding.query_instruction", "embedding.bge_query_instruction"),
            "为这个句子生成表示以用于检索相关文章：",
        )
    )
    device: str | None = field(
        default_factory=lambda: _alias_str(
            ("MYCODINGAGENT_EMBEDDING_DEVICE", "MYCODINGAGENT_BGE_DEVICE"),
            ("embedding.device", "embedding.bge_device"),
            "",
        ) or None
    )
    batch_size: int = field(
        default_factory=lambda: max(
            1,
            _alias_int(
                ("MYCODINGAGENT_EMBEDDING_BATCH_SIZE", "MYCODINGAGENT_BGE_BATCH_SIZE"),
                ("embedding.batch_size", "embedding.bge_batch_size"),
                16,
            ),
        )
    )
    dimension: int = field(
        default_factory=lambda: _alias_int(
            ("MYCODINGAGENT_EMBEDDING_DIM", "MYCODINGAGENT_BGE_DIM"),
            ("embedding.dimension", "embedding.bge_dimension"),
            512,
        )
    )
    fallback_to_hash: bool = field(
        default_factory=lambda: _alias_bool(
            ("MYCODINGAGENT_EMBEDDING_FALLBACK_TO_HASH", "MYCODINGAGENT_BGE_FALLBACK_TO_HASH"),
            ("embedding.fallback_to_hash",),
            False,
        )
    )
    hash_dimension: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_HASH_EMBEDDING_DIM", 256))
    request_extra: dict = field(
        default_factory=lambda: _alias_json_dict(
            ("MYCODINGAGENT_EMBEDDING_REQUEST_EXTRA",),
            ("embedding.request_extra",),
            {},
        )
    )
    headers: dict = field(
        default_factory=lambda: _alias_json_dict(
            ("MYCODINGAGENT_EMBEDDING_HEADERS",),
            ("embedding.headers",),
            {},
        )
    )

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
    enabled: bool = field(default_factory=lambda: _env_bool("MYCODINGAGENT_MILVUS_ENABLED", True))
    host: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_MILVUS_HOST", "127.0.0.1"))
    port: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_MILVUS_PORT", "19530"))
    collection: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_MILVUS_COLLECTION", "mycodingagent_skills"))
    token: str | None = field(default_factory=lambda: _env_str("MYCODINGAGENT_MILVUS_TOKEN", "") or None)
    recreate_incompatible: bool = field(
        default_factory=lambda: _env_bool("MYCODINGAGENT_MILVUS_RECREATE_INCOMPATIBLE", True)
    )
    dense_index_type: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_MILVUS_DENSE_INDEX_TYPE", "HNSW"))
    dense_metric_type: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_MILVUS_DENSE_METRIC_TYPE", "COSINE"))
    hnsw_m: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MILVUS_HNSW_M", 16))
    hnsw_ef_construction: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_MILVUS_HNSW_EF_CONSTRUCTION", 256)
    )
    hnsw_ef: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MILVUS_HNSW_EF", 64))
    sparse_index_type: str = field(
        default_factory=lambda: _env_str("MYCODINGAGENT_MILVUS_SPARSE_INDEX_TYPE", "SPARSE_INVERTED_INDEX")
    )
    sparse_metric_type: str = field(default_factory=lambda: _env_str("MYCODINGAGENT_MILVUS_SPARSE_METRIC_TYPE", "BM25"))
    sparse_inverted_index_algo: str = field(
        default_factory=lambda: _env_str("MYCODINGAGENT_MILVUS_SPARSE_ALGO", "DAAT_MAXSCORE")
    )
    rrf_k: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MILVUS_RRF_K", 60))
    text_max_bytes: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MILVUS_TEXT_MAX_BYTES", 65535))
    analyzer_params: dict = field(
        default_factory=lambda: _env_json_dict("MYCODINGAGENT_MILVUS_ANALYZER_PARAMS", {"type": "chinese"})
    )

    @property
    def uri(self) -> str:
        return _env_str("MYCODINGAGENT_MILVUS_URI", f"http://{self.host}:{self.port}")


@dataclass(frozen=True)
class MCPConfig:
    enabled: bool = field(default_factory=lambda: _env_bool("MYCODINGAGENT_MCP_ENABLED", True))
    project_config_path: Path = field(
        default_factory=lambda: _env_path("MYCODINGAGENT_MCP_PROJECT_CONFIG", _default_mcp_project_config_path())
        or _default_mcp_project_config_path()
    )
    user_config_path: Path = field(
        default_factory=lambda: _env_path("MYCODINGAGENT_MCP_USER_CONFIG", _default_mcp_user_config_path())
        or _default_mcp_user_config_path()
    )
    env_config_var: str = "MYCODINGAGENT_MCP_CONFIG"
    reconnect_server_step: int = field(
        default_factory=lambda: max(
            1,
            _env_int(
                "RECONNECT_MCP_SERVER_STEP",
                _env_int("MYCODINGAGENT_RECONNECT_MCP_SERVER_STEP", 10),
            ),
        )
    )


@dataclass(frozen=True)
class AppConfig:
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
