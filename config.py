from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_path(name: str, default: Path | None = None) -> Path | None:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    return Path(raw_value).expanduser()


def _env_paths(name: str) -> tuple[Path, ...]:
    raw_value = os.getenv(name)
    if not raw_value:
        return ()
    return tuple(Path(item).expanduser() for item in raw_value.split(os.pathsep) if item.strip())


def _env_list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    return tuple(item.strip() for item in raw_value.split(",") if item.strip())


def _default_user_id() -> str:
    return (
        os.getenv("MYCODINGAGENT_USER_ID")
        or os.getenv("USER")
        or os.getenv("USERNAME")
        or "default_user"
    )


def _env_json_dict(name: str, default: dict) -> dict:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return default
    return value if isinstance(value, dict) else default


def _default_builtin_skills_root() -> Path:
    return Path(__file__).resolve().parent / "skills"


def _default_workspace_skills_root() -> Path:
    raw_root = (
        os.getenv("MYCODINGAGENT_WORKSPACE_SKILLS_ROOT")
        or os.getenv("MYCODINGAGENT_SKILLS_ROOT")
    )
    if raw_root:
        return Path(raw_root).expanduser()
    return Path(os.getenv("MYCODINGAGENT_SANDBOX_ROOT", os.getcwd())).expanduser() / "skills"


def _default_memory_db_path() -> Path:
    state_dir = os.getenv("MYCODINGAGENT_STATE_DIR")
    if state_dir:
        return Path(state_dir).expanduser() / "sessions.sqlite3"
    xdg_state_home = os.getenv("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "myCodingAgent" / "sessions.sqlite3"
    return Path.home() / ".local" / "state" / "myCodingAgent" / "sessions.sqlite3"


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
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "sk-075f2aa02c094f4d9729c9619b77c438")
    )
    base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"))


@dataclass(frozen=True)
class ClientConfig:
    max_tool_rounds: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MAX_TOOL_ROUNDS", 50))
    max_display_string_chars: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_MAX_DISPLAY_STRING_CHARS", 12000)
    )
    max_tool_output_chars: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MAX_TOOL_OUTPUT_CHARS", 12000))
    multiline_argument_fields: frozenset[str] = frozenset({"command", "content", "old_string", "new_string"})


@dataclass(frozen=True)
class MemoryConfig:
    enabled: bool = field(default_factory=lambda: _env_bool("MYCODINGAGENT_MEMORY_ENABLED", True))
    output_context_compression: bool = field(default_factory=lambda: _env_bool("OUTPUT_CONTEXT_COMPRESSION", True))
    db_path: Path = field(default_factory=lambda: _env_path("MYCODINGAGENT_MEMORY_DB_PATH", _default_memory_db_path()) or _default_memory_db_path())
    prompt_path: Path | None = field(default_factory=lambda: _env_path("MYCODINGAGENT_MEMORY_SUMMARY_PROMPT"))
    default_context_window: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MODEL_CONTEXT_WINDOW", 1_000_000))
    session_ttl_days: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MEMORY_SESSION_TTL_DAYS", 30))
    tool_preview_chars: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MEMORY_TOOL_PREVIEW_CHARS", 2000))
    context_preview_threshold_tokens: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_CONTEXT_PREVIEW_THRESHOLD_TOKENS", 12000)
    )
    context_preview_tokens: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_CONTEXT_PREVIEW_TOKENS", 2000))
    budget_soft_ratio: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_BUDGET_SOFT_RATIO", 0.60))
    budget_working_ratio: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_BUDGET_WORKING_RATIO", 0.80))
    budget_emergency_ratio: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_BUDGET_EMERGENCY_RATIO", 0.90))
    current_turn_summary_max_per_message: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_CURRENT_TURN_SUMMARY_MAX_PER_MESSAGE", 2)
    )
    current_turn_summary_max_per_turn: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_CURRENT_TURN_SUMMARY_MAX_PER_TURN", 5)
    )
    checkpoint_enabled: bool = field(default_factory=lambda: _env_bool("MYCODINGAGENT_CHECKPOINT_ENABLED", True))
    checkpoint_soft_ratio: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_CHECKPOINT_SOFT_RATIO", 0.60))
    checkpoint_hard_ratio: float = field(default_factory=lambda: _env_float("MYCODINGAGENT_CHECKPOINT_HARD_RATIO", 0.85))
    snapshot_version: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_SNAPSHOT_VERSION", "1.0"))
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
    context_store_backend: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_CONTEXT_STORE_BACKEND", "sqlite"))
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
    root: Path = field(default_factory=lambda: Path(os.getenv("MYCODINGAGENT_SANDBOX_ROOT", os.getcwd())))
    docker_workspace_alias: Path = Path("/workspace")
    max_output_chars: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MAX_OUTPUT_CHARS", 10000))
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
    image: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_DOCKER_IMAGE", "mycodingagent-sandbox:py312"))
    network: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_DOCKER_NETWORK", "none"))
    build_network: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_DOCKER_BUILD_NETWORK", "host"))
    cpus: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_DOCKER_CPUS", "2"))
    memory: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_DOCKER_MEMORY", "1g"))
    pids_limit: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_DOCKER_PIDS_LIMIT", "256"))
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
    markdown_filename: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_SKILL_MARKDOWN_NAME", "SKILL.md"))
    json_suffix: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_SKILL_JSON_SUFFIX", ".skill.json"))
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
    router_top_n: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_SKILL_ROUTER_TOP_N", 20))
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
    provider: str = "bge_http"
    bge_model: str = "bge-m3"
    bge_endpoint: str = field(
        default_factory=lambda: os.getenv("MYCODINGAGENT_BGE_ENDPOINT", "http://127.0.0.1:11434/api/embed")
    )
    bge_api_format: str = "ollama"
    bge_api_key: str | None = None
    bge_timeout: float = 30.0
    bge_query_instruction: str = "为这个句子生成表示以用于检索相关文章："
    bge_device: str | None = field(default_factory=lambda: os.getenv("MYCODINGAGENT_BGE_DEVICE") or None)
    bge_batch_size: int = field(default_factory=lambda: max(1, _env_int("MYCODINGAGENT_BGE_BATCH_SIZE", 16)))
    bge_dimension: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_BGE_DIM", 512))
    fallback_to_hash: bool = field(default_factory=lambda: _env_bool("MYCODINGAGENT_BGE_FALLBACK_TO_HASH", False))
    hash_dimension: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_HASH_EMBEDDING_DIM", 256))


@dataclass(frozen=True)
class MilvusConfig:
    enabled: bool = field(default_factory=lambda: _env_bool("MYCODINGAGENT_MILVUS_ENABLED", True))
    host: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_MILVUS_HOST", "127.0.0.1"))
    port: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_MILVUS_PORT", "19530"))
    collection: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_MILVUS_COLLECTION", "mycodingagent_skills"))
    token: str | None = field(default_factory=lambda: os.getenv("MYCODINGAGENT_MILVUS_TOKEN") or None)
    recreate_incompatible: bool = field(
        default_factory=lambda: _env_bool("MYCODINGAGENT_MILVUS_RECREATE_INCOMPATIBLE", True)
    )
    dense_index_type: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_MILVUS_DENSE_INDEX_TYPE", "HNSW"))
    dense_metric_type: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_MILVUS_DENSE_METRIC_TYPE", "COSINE"))
    hnsw_m: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MILVUS_HNSW_M", 16))
    hnsw_ef_construction: int = field(
        default_factory=lambda: _env_int("MYCODINGAGENT_MILVUS_HNSW_EF_CONSTRUCTION", 256)
    )
    hnsw_ef: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MILVUS_HNSW_EF", 64))
    sparse_index_type: str = field(
        default_factory=lambda: os.getenv("MYCODINGAGENT_MILVUS_SPARSE_INDEX_TYPE", "SPARSE_INVERTED_INDEX")
    )
    sparse_metric_type: str = field(default_factory=lambda: os.getenv("MYCODINGAGENT_MILVUS_SPARSE_METRIC_TYPE", "BM25"))
    sparse_inverted_index_algo: str = field(
        default_factory=lambda: os.getenv("MYCODINGAGENT_MILVUS_SPARSE_ALGO", "DAAT_MAXSCORE")
    )
    rrf_k: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MILVUS_RRF_K", 60))
    text_max_bytes: int = field(default_factory=lambda: _env_int("MYCODINGAGENT_MILVUS_TEXT_MAX_BYTES", 65535))
    analyzer_params: dict = field(
        default_factory=lambda: _env_json_dict("MYCODINGAGENT_MILVUS_ANALYZER_PARAMS", {"type": "chinese"})
    )

    @property
    def uri(self) -> str:
        return os.getenv("MYCODINGAGENT_MILVUS_URI", f"http://{self.host}:{self.port}")


@dataclass(frozen=True)
class AppConfig:
    api: ApiConfig = field(default_factory=ApiConfig)
    client: ClientConfig = field(default_factory=ClientConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    docker: DockerConfig = field(default_factory=DockerConfig)
    skills: SkillConfig = field(default_factory=SkillConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    milvus: MilvusConfig = field(default_factory=MilvusConfig)


CONFIG = AppConfig()
