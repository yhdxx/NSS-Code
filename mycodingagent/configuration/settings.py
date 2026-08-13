from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── 统一用户 JSON 配置 ──
_USER_CONFIG_PATH = Path.home() / ".mycodingagent" / "config.json"
_MISSING = object()


def _load_user_json_config() -> dict:
    """加载 ~/.mycodingagent/config.json。

    文件不存在或解析失败时静默返回 {}，格式诊断由 bootstrap.py 处理。
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

_MODEL_PROVIDER_ENV_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "anthropic": {"api": ("ANTHROPIC_API_KEY",), "base_url": ("ANTHROPIC_BASE_URL",)},
    "deepseek": {"api": ("DEEPSEEK_API_KEY",), "base_url": ("DEEPSEEK_BASE_URL",)},
    "doubao": {"api": ("DOUBAO_API_KEY", "ARK_API_KEY", "VOLCENGINE_API_KEY"), "base_url": ("DOUBAO_BASE_URL", "ARK_BASE_URL")},
    "gemini": {"api": ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "base_url": ("GEMINI_BASE_URL",)},
    "grok": {"api": ("GROK_API_KEY", "XAI_API_KEY", "X_AI_API_KEY"), "base_url": ("GROK_BASE_URL", "XAI_BASE_URL")},
    "kimi": {"api": ("KIMI_API_KEY", "MOONSHOT_API_KEY"), "base_url": ("KIMI_BASE_URL", "MOONSHOT_BASE_URL")},
    "meta": {"api": ("META_API_KEY", "LLAMA_API_KEY"), "base_url": ("META_BASE_URL", "LLAMA_BASE_URL")},
    "minimax": {"api": ("MINIMAX_API_KEY",), "base_url": ("MINIMAX_BASE_URL",)},
    "openai": {"api": ("OPENAI_API_KEY",), "base_url": ("OPENAI_BASE_URL",)},
    "qwen": {"api": ("QWEN_API_KEY", "DASHSCOPE_API_KEY"), "base_url": ("QWEN_BASE_URL", "DASHSCOPE_BASE_URL")},
    "zhipu": {"api": ("ZHIPU_API_KEY", "ZHIPUAI_API_KEY"), "base_url": ("ZHIPU_BASE_URL", "ZHIPUAI_BASE_URL")},
}


def _env_key_part(value: str) -> str:
    text = "".join(char.upper() if char.isalnum() else "_" for char in value.strip())
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _env_first(names: tuple[str, ...]) -> object:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return _MISSING


def _model_provider_env_names(provider: str, field_name: str) -> tuple[str, ...]:
    provider_key = provider.strip().lower()
    provider_part = _env_key_part(provider_key)
    field_part = _env_key_part(field_name)
    aliases = _MODEL_PROVIDER_ENV_ALIASES.get(provider_key, {}).get(field_name, ())
    return (f"MYCODINGAGENT_MODEL_PROVIDER_{provider_part}_{field_part}", *aliases)


def _model_profile_env_names(profile_key: str, field_name: str) -> tuple[str, ...]:
    return (f"MYCODINGAGENT_MODEL_PROFILE_{_env_key_part(profile_key)}_{_env_key_part(field_name)}",)


def _raw_or_env(raw: dict, field_name: str, env_names: tuple[str, ...], default: object = _MISSING) -> object:
    if field_name in raw:
        value = raw[field_name]
        if value is not None and not (isinstance(value, str) and not value.strip()):
            return value
    env_value = _env_first(env_names)
    if env_value is not _MISSING:
        return env_value
    return default


def _raw_env_str(raw: dict, field_name: str, env_names: tuple[str, ...], default: str = "") -> str:
    value = _raw_or_env(raw, field_name, env_names, default)
    if value is _MISSING or value is None:
        return default
    return str(value).strip()


def _raw_env_float(raw: dict, field_name: str, env_names: tuple[str, ...]) -> float | None:
    return _optional_float(_raw_or_env(raw, field_name, env_names, None))


def _raw_env_dict(raw: dict, field_name: str, env_names: tuple[str, ...]) -> dict:
    value = _raw_or_env(raw, field_name, env_names, {})
    if isinstance(value, dict):
        return value
    if value is _MISSING or value is None or value == "":
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _raw_env_reasoning(raw: dict, field_name: str, env_names: tuple[str, ...]) -> str | dict[str, Any] | None:
    value = _raw_or_env(raw, field_name, env_names, None)
    if value is _MISSING or value is None or value == "":
        return None
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return str(value).strip()
    return parsed if isinstance(parsed, dict) else str(value).strip()

def _user_raw(json_path: str, env_names: tuple[str, ...]) -> object:
    """统一配置查找：JSON 路径 > 环境变量列表（逐项尝试）。

    json_path 示例："model.active"
    env_names 示例：("MYCODINGAGENT_MODEL_ACTIVE",)
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


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(raw) for key, raw in value.items() if str(key).strip()}


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


def _default_builtin_skills_root() -> Path:
    return Path(__file__).resolve().parents[2] / "skills"


def _default_workspace_skills_root() -> Path:
    raw_root = (
        _user_str("skills.workspace_root", ("MYCODINGAGENT_WORKSPACE_SKILLS_ROOT",), "")
    )
    if raw_root:
        return Path(raw_root).expanduser()
    sandbox_root = _user_str("sandbox.root", ("MYCODINGAGENT_SANDBOX_ROOT",), os.getcwd())
    return Path(sandbox_root).expanduser() / "skills"


def _default_state_dir() -> Path:
    return (
        _user_path("memory.state_dir", ("MYCODINGAGENT_STATE_DIR",))
        or Path.home() / ".mycodingagent" / "state"
    )


def _default_memory_db_path() -> Path:
    return _default_state_dir() / "sessions.sqlite3"


def _default_mcp_project_config_path() -> Path:
    return Path.cwd() / ".mycodingagent" / "mcp.json"


def _default_mcp_user_config_path() -> Path:
    return Path.home() / ".mycodingagent" / "mcp.json"


# ── 配置类定义 ──

@dataclass(frozen=True)
class ModelProviderConfig:
    """单个推理模型厂商的连接配置。API Key 按厂商统一配置。"""

    api: str = ""
    base_url: str = ""
    timeout: float | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: object, *, provider_key: str = "") -> "ModelProviderConfig":
        data = raw if isinstance(raw, dict) else {}
        env_provider = provider_key or str(data.get("provider") or "").strip().lower()
        return cls(
            api=_raw_env_str(data, "api", _model_provider_env_names(env_provider, "api")),
            base_url=_raw_env_str(data, "base_url", _model_provider_env_names(env_provider, "base_url")),
            timeout=_raw_env_float(data, "timeout", _model_provider_env_names(env_provider, "timeout")),
            extra_headers=_string_dict(
                _raw_env_dict(data, "extra_headers", _model_provider_env_names(env_provider, "extra_headers"))
            ),
            extra_body=_raw_env_dict(data, "extra_body", _model_provider_env_names(env_provider, "extra_body")),
        )


@dataclass(frozen=True)
class ModelProfileConfig:
    """单个推理模型 profile。provider/model 为选择模型的必要字段。"""

    provider: str
    model: str
    reasoning: str | dict[str, Any] | None = None
    timeout: float | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: object, *, profile_key: str = "") -> "ModelProfileConfig":
        data = raw if isinstance(raw, dict) else {}
        return cls(
            provider=_raw_env_str(data, "provider", _model_profile_env_names(profile_key, "provider")).lower(),
            model=_raw_env_str(data, "model", _model_profile_env_names(profile_key, "model")),
            reasoning=_raw_env_reasoning(data, "reasoning", _model_profile_env_names(profile_key, "reasoning")),
            timeout=_raw_env_float(data, "timeout", _model_profile_env_names(profile_key, "timeout")),
            extra_headers=_string_dict(
                _raw_env_dict(data, "extra_headers", _model_profile_env_names(profile_key, "extra_headers"))
            ),
            extra_body=_raw_env_dict(data, "extra_body", _model_profile_env_names(profile_key, "extra_body")),
        )

    def missing_required_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.provider:
            missing.append("provider")
        if not self.model:
            missing.append("model")
        return missing


@dataclass(frozen=True)
class ModelLongTermMemoryConfig:
    """长期记忆使用的推理模型 profile key。"""

    storage: str = "main"
    search: str = "main"


@dataclass(frozen=True)
class ModelMediaConfig:
    """One media capability model selected from a shared provider connection."""

    provider: str
    model: str

    @classmethod
    def from_raw(
        cls,
        raw: object,
        *,
        capability: str,
        default_provider: str,
        default_model: str,
    ) -> "ModelMediaConfig":
        data = raw if isinstance(raw, dict) else {}
        env_prefix = f"MYCODINGAGENT_MODEL_{capability.upper()}"
        return cls(
            provider=_raw_env_str(
                data,
                "provider",
                (f"{env_prefix}_PROVIDER",),
                default_provider,
            ).lower(),
            model=_raw_env_str(
                data,
                "model",
                (f"{env_prefix}_MODEL",),
                default_model,
            ),
        )


def _load_model_profiles() -> dict[str, ModelProfileConfig]:
    raw = _user_dict("model.profiles", (), {})
    if not raw:
        raw = {
            "main": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
            },
            "memory_search": {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "reasoning": {"thinking": "disabled"},
            }
        }
    profiles: dict[str, ModelProfileConfig] = {}
    for key, value in raw.items():
        profile_key = str(key).strip()
        if profile_key:
            profiles[profile_key] = ModelProfileConfig.from_raw(value, profile_key=profile_key)
    return profiles or {
        "main": ModelProfileConfig(provider="deepseek", model="deepseek-v4-pro"),
        "memory_search": ModelProfileConfig(
            provider="deepseek",
            model="deepseek-v4-flash",
            reasoning={"thinking": "disabled"},
        ),
    }


def _load_model_providers() -> dict[str, ModelProviderConfig]:
    raw = _user_dict("model.providers", (), {})
    if not raw:
        raw = {"deepseek": {"api": ""}}
    providers: dict[str, ModelProviderConfig] = {}
    for key, value in raw.items():
        provider_key = str(key).strip().lower()
        if provider_key:
            providers[provider_key] = ModelProviderConfig.from_raw(value, provider_key=provider_key)
    return providers or {"deepseek": ModelProviderConfig(api="")}


def _load_model_ltm_config() -> ModelLongTermMemoryConfig:
    active = _user_str("model.active", ("MYCODINGAGENT_MODEL_ACTIVE",), "main").strip() or "main"
    raw = _user_dict("model.long_term_memory", (), {})
    return ModelLongTermMemoryConfig(
        storage=_raw_env_str(
            raw,
            "storage",
            ("MYCODINGAGENT_MODEL_LONG_TERM_MEMORY_STORAGE",),
            active,
        ) or active,
        search=_raw_env_str(
            raw,
            "search",
            ("MYCODINGAGENT_MODEL_LONG_TERM_MEMORY_SEARCH",),
            "memory_search",
        ) or "memory_search",
    )


def _load_model_media_config(
    capability: str,
    *,
    default_provider: str,
    default_model: str,
) -> ModelMediaConfig:
    return ModelMediaConfig.from_raw(
        _user_dict(f"model.{capability}", (), {}),
        capability=capability,
        default_provider=default_provider,
        default_model=default_model,
    )


@dataclass(frozen=True)
class ModelConfig:
    """推理模型配置入口。旧 api.* 配置已移除。"""

    active: str = field(default_factory=lambda: _user_str("model.active", ("MYCODINGAGENT_MODEL_ACTIVE",), "main").strip() or "main")
    providers: dict[str, ModelProviderConfig] = field(default_factory=_load_model_providers)
    profiles: dict[str, ModelProfileConfig] = field(default_factory=_load_model_profiles)
    long_term_memory: ModelLongTermMemoryConfig = field(default_factory=_load_model_ltm_config)
    audio: ModelMediaConfig = field(
        default_factory=lambda: _load_model_media_config(
            "audio",
            default_provider="qwen",
            default_model="qwen3-asr-flash",
        )
    )
    vision: ModelMediaConfig = field(
        default_factory=lambda: _load_model_media_config(
            "vision",
            default_provider="zhipu",
            default_model="glm-4v-flash",
        )
    )

    @property
    def active_profile(self) -> ModelProfileConfig | None:
        return self.profiles.get(self.active)

    def profile(self, key: str) -> ModelProfileConfig | None:
        return self.profiles.get(key)

    def provider(self, key: str) -> ModelProviderConfig | None:
        provider_key = key.strip().lower()
        if not provider_key:
            return None
        return self.providers.get(provider_key) or ModelProviderConfig.from_raw({}, provider_key=provider_key)

    def validation_errors(
        self,
        *,
        require_long_term_memory: bool = True,
    ) -> list[str]:
        errors: list[str] = []
        checked_providers: set[str] = set()

        def check_provider_api(provider: str) -> None:
            provider_key = provider.strip().lower()
            if not provider_key or provider_key in checked_providers:
                return
            checked_providers.add(provider_key)
            provider_config = self.provider(provider_key)
            if provider_config is None:
                errors.append(f"model.providers 缺少厂商配置：{provider_key}")
            elif not provider_config.api:
                errors.append(f"model.providers.{provider_key}.api 缺少必要字段：api")

        active_profile = self.active_profile
        if active_profile is None:
            errors.append(f"model.active 指向不存在的 profile：{self.active}")
        else:
            missing = active_profile.missing_required_fields()
            if missing:
                errors.append(f"model.profiles.{self.active} 缺少必要字段：{', '.join(missing)}")
            check_provider_api(active_profile.provider)
        if require_long_term_memory:
            for label, key in (
                ("storage", self.long_term_memory.storage),
                ("search", self.long_term_memory.search),
            ):
                profile = self.profile(key) if key else None
                if key and profile is None:
                    errors.append(f"model.long_term_memory.{label} 指向不存在的 profile：{key}")
                elif profile is not None:
                    check_provider_api(profile.provider)
        supported_media_providers = {"zhipu", "qwen"}
        for capability, media in (("audio", self.audio), ("vision", self.vision)):
            if media.provider not in supported_media_providers:
                errors.append(
                    f"model.{capability}.provider={media.provider or '<empty>'} 不受支持；支持：qwen, zhipu"
                )
            if not media.model:
                errors.append(f"model.{capability}.model 缺少必要字段：model")
        return errors


@dataclass(frozen=True)
class ClientConfig:
    """LLM 客户端运行时行为配置：重试、展示、调试和系统提示词。"""
    max_tool_rounds: int = field(
        default_factory=lambda: max(
            1,
            _user_int("client.max_tool_rounds", ("MYCODINGAGENT_MAX_TOOL_ROUNDS",), 100),
        )
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
        default_factory=lambda: _user_bool("client.debug", ("MYCODINGAGENT_DEBUG",), False)
    )
    step_token: bool = field(
        default_factory=lambda: _user_bool("client.step_token", ("MYCODINGAGENT_STEP_TOKEN",), True)
    )
    round_token: bool = field(
        default_factory=lambda: _user_bool("client.round_token", ("MYCODINGAGENT_ROUND_TOKEN",), True)
    )
    conversation_token: bool = field(
        default_factory=lambda: _user_bool("client.conversation_token", ("MYCODINGAGENT_CONVERSATION_TOKEN",), True)
    )


@dataclass(frozen=True)
class ApprovalConfig:
    """Process-wide Bash and MCP approval behavior."""

    mode: str = field(
        default_factory=lambda: _user_str(
            "approval.mode",
            ("MYCODINGAGENT_APPROVAL_MODE",),
            "default",
        ).strip().lower()
    )

    def validation_errors(self) -> list[str]:
        if self.mode not in {"default", "auto"}:
            return ["approval.mode 只能是 default 或 auto"]
        return []


@dataclass(frozen=True)
class LongTermMemoryConfig:
    """长期记忆存储和查询行为配置。模型选择位于 model.long_term_memory。"""
    enabled: bool = field(
        default_factory=lambda: _user_bool("long_term_memory.enabled", ("MYCODINGAGENT_LONG_TERM_MEMORY_ENABLED",), True)
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
        default_factory=lambda: _user_bool("memory.output_context_compression", ("MYCODINGAGENT_OUTPUT_CONTEXT_COMPRESSION",), True)
    )
    state_dir: Path = field(default_factory=_default_state_dir)
    db_path: Path = field(
        default_factory=lambda: _user_path("memory.db_path", ("MYCODINGAGENT_MEMORY_DB_PATH",)) or _default_memory_db_path()
    )
    prompt_path: Path | None = field(
        default_factory=lambda: _user_path("memory.prompt_path", ("MYCODINGAGENT_MEMORY_SUMMARY_PROMPT",))
    )
    default_context_window: int = field(
        default_factory=lambda: _user_int("memory.default_context_window", ("MYCODINGAGENT_MODEL_CONTEXT_WINDOW",), 1_000_000)
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
            {},
        )
    )

    def context_window_for(self, model: str) -> int:
        value = self.model_context_windows.get(model)
        if isinstance(value, int) and value > 0:
            return value
        return self.default_context_window


BUILTIN_READ_DENYLIST = ("~/.ssh", "~/.aws", "~/.gnupg")


@dataclass(frozen=True)
class SandboxConfig:
    """Docker 沙箱工作区配置。"""
    root_env: str = "MYCODINGAGENT_SANDBOX_ROOT"
    root: Path = field(
        default_factory=lambda: Path(_user_str("sandbox.root", ("MYCODINGAGENT_SANDBOX_ROOT",), os.getcwd()))
    )
    docker_workspace_alias: Path = Path("/workspace")
    access_mode: str = field(
        default_factory=lambda: _user_str("sandbox.access_mode", ("MYCODINGAGENT_SANDBOX_ACCESS_MODE",), "global_read")
    )
    read_allowlist: tuple[str, ...] = field(
        default_factory=lambda: _user_list("sandbox.read_allowlist", ("MYCODINGAGENT_SANDBOX_READ_ALLOWLIST",), ())
    )
    read_denylist: tuple[str, ...] = field(
        default_factory=lambda: _user_list("sandbox.read_denylist", ("MYCODINGAGENT_SANDBOX_READ_DENYLIST",), ())
    )
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
        ".mycodingagent",
        "build",
        "dist",
    })

    def effective_read_denylist(self) -> tuple[Path, ...]:
        builtin = tuple(Path(item).expanduser() for item in BUILTIN_READ_DENYLIST)
        user = tuple(Path(item).expanduser() for item in self.read_denylist)
        return _dedupe_paths(builtin + user)


@dataclass(frozen=True)
class DockerConfig:
    """Docker 沙箱容器资源限制。"""
    image_env: str = "MYCODINGAGENT_DOCKER_IMAGE"
    build_network_env: str = "MYCODINGAGENT_DOCKER_BUILD_NETWORK"
    cpus_env: str = "MYCODINGAGENT_DOCKER_CPUS"
    memory_env: str = "MYCODINGAGENT_DOCKER_MEMORY"
    pids_limit_env: str = "MYCODINGAGENT_DOCKER_PIDS_LIMIT"
    pull_timeout_env: str = "MYCODINGAGENT_DOCKER_PULL_TIMEOUT"
    image: str = field(
        default_factory=lambda: _user_str("docker.image", ("MYCODINGAGENT_DOCKER_IMAGE",), "mycodingagent-sandbox:py312")
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
        default_factory=lambda: _user_int("docker.pull_timeout", ("MYCODINGAGENT_DOCKER_PULL_TIMEOUT",), 1800)
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
    user_root: Path = field(
        default_factory=lambda: (
            _user_path("skills.user_root", ("MYCODINGAGENT_USER_SKILLS_ROOT",))
            or (Path.home() / ".mycodingagent" / "skills")
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
    prefetch_top_k: int = field(
        default_factory=lambda: _user_int("skills.prefetch_top_k", ("MYCODINGAGENT_SKILL_PREFETCH_TOP_K",), 3)
    )
    search_top_k: int = field(
        default_factory=lambda: _user_int("skills.search_top_k", ("MYCODINGAGENT_SKILL_SEARCH_TOP_K",), 8)
    )
    fixed_prompt_max_tokens: int = field(
        default_factory=lambda: max(
            1,
            _user_int("skills.fixed_prompt_max_tokens", ("MYCODINGAGENT_FIXED_SKILL_PROMPT_MAX_TOKENS",), 2000),
        )
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
        return _dedupe_paths((self.builtin_root, *self.extra_roots, self.user_root))

    @property
    def fixed_roots(self) -> tuple[Path, ...]:
        return _dedupe_paths(tuple(root / "fixed" for root in self.roots))

    @property
    def dynamic_roots(self) -> tuple[Path, ...]:
        return _dedupe_paths(tuple(root / "Dynamic" for root in self.roots))


@dataclass(frozen=True)
class EmbeddingConfig:
    """Embedding 模型配置：provider/model/endpoint/api_key 等。"""
    provider: str = field(
        default_factory=lambda: _user_str("embedding.provider", ("MYCODINGAGENT_EMBEDDING_PROVIDER",), "http")
    )
    model: str = field(
        default_factory=lambda: _user_str("embedding.model", ("MYCODINGAGENT_EMBEDDING_MODEL",), "bge-m3")
    )
    endpoint: str = field(
        default_factory=lambda: _user_str(
            "embedding.endpoint",
            ("MYCODINGAGENT_EMBEDDING_ENDPOINT",),
            "http://127.0.0.1:11434/api/embed",
        )
    )
    api_format: str = field(
        default_factory=lambda: _user_str(
            "embedding.api_format",
            ("MYCODINGAGENT_EMBEDDING_API_FORMAT",),
            "ollama",
        )
    )
    api_key: str | None = field(
        default_factory=lambda: _user_str(
            "embedding.api_key",
            ("MYCODINGAGENT_EMBEDDING_API_KEY",),
            "",
        ) or None
    )
    timeout: float = field(
        default_factory=lambda: max(
            0.1,
            _user_float(
                "embedding.timeout",
                ("MYCODINGAGENT_EMBEDDING_TIMEOUT",),
                300.0,
            ),
        )
    )
    download_timeout: float = field(
        default_factory=lambda: max(
            1.0,
            _user_float(
                "embedding.download_timeout",
                ("MYCODINGAGENT_EMBEDDING_DOWNLOAD_TIMEOUT",),
                900.0,
            ),
        )
    )
    query_instruction: str = field(
        default_factory=lambda: _user_str(
            "embedding.query_instruction",
            ("MYCODINGAGENT_EMBEDDING_QUERY_INSTRUCTION",),
            "为这个句子生成表示以用于检索相关文章：",
        )
    )
    normalize: bool = field(
        default_factory=lambda: _user_bool("embedding.normalize", ("MYCODINGAGENT_EMBEDDING_NORMALIZE",), True)
    )
    device: str | None = field(
        default_factory=lambda: _user_str(
            "embedding.device",
            ("MYCODINGAGENT_EMBEDDING_DEVICE",),
            "",
        ) or None
    )
    batch_size: int = field(
        default_factory=lambda: max(
            1,
            _user_int(
                "embedding.batch_size",
                ("MYCODINGAGENT_EMBEDDING_BATCH_SIZE",),
                16,
            ),
        )
    )

    dimension: int = field(
        default_factory=lambda: max(1, _user_int("embedding.dimension", ("MYCODINGAGENT_EMBEDDING_DIMENSION",), 1024))
    )
    fallback_to_hash: bool = field(
        default_factory=lambda: _user_bool(
            "embedding.fallback_to_hash",
            ("MYCODINGAGENT_EMBEDDING_FALLBACK_TO_HASH",),
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

    def validation_errors(self) -> list[str]:
        provider = self.provider.strip().lower()
        errors: list[str] = []
        if provider not in {"http", "local", "hash"}:
            errors.append(
                f"embedding.provider={self.provider!r} 不受支持；支持：http、local、hash"
            )
        elif provider == "http":
            api_format = self.api_format.strip().lower()
            if api_format not in {"ollama", "openai", "dashscope"}:
                errors.append(
                    f"embedding.api_format={self.api_format!r} 不受支持；"
                    "支持：ollama、openai、dashscope"
                )
            if not self.endpoint.strip():
                errors.append("embedding.endpoint 不能为空")
            if not self.model.strip():
                errors.append("embedding.model 不能为空")
        return errors

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
    dense_index_type: str = field(
        default_factory=lambda: _user_str("milvus.dense_index_type", ("MYCODINGAGENT_MILVUS_DENSE_INDEX_TYPE",), "HNSW")
    )
    dense_metric_type: str = field(
        default_factory=lambda: _user_str("milvus.dense_metric_type", ("MYCODINGAGENT_MILVUS_DENSE_METRIC_TYPE",), "COSINE")
    )
    hnsw_m: int = field(
        default_factory=lambda: _user_int("milvus.hnsw_m", ("MYCODINGAGENT_MILVUS_HNSW_M",), 16)
    )
    hnsw_ef_construction: int = field(
        default_factory=lambda: _user_int(
            "milvus.hnsw_ef_construction",
            ("MYCODINGAGENT_MILVUS_HNSW_EF_CONSTRUCTION",),
            200,
        )
    )
    hnsw_ef: int = field(
        default_factory=lambda: _user_int("milvus.hnsw_ef", ("MYCODINGAGENT_MILVUS_HNSW_EF",), 64)
    )
    sparse_index_type: str = field(
        default_factory=lambda: _user_str(
            "milvus.sparse_index_type",
            ("MYCODINGAGENT_MILVUS_SPARSE_INDEX_TYPE",),
            "SPARSE_INVERTED_INDEX",
        )
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
class SearchConfig:
    """Optional Tavily MCP search credential."""

    tavily_api_key: str = field(
        default_factory=lambda: _user_str(
            "search.tavily_api_key",
            ("MYCODINGAGENT_TAVILY_API_KEY", "TAVILY_API_KEY"),
            "",
        ).strip()
    )


@dataclass(frozen=True)
class WebFetchConfig:
    """Static HTTP/HTTPS page retrieval limits."""

    enabled: bool = field(
        default_factory=lambda: _user_bool(
            "web_fetch.enabled", ("MYCODINGAGENT_WEB_FETCH_ENABLED",), True
        )
    )
    timeout: float = field(
        default_factory=lambda: max(
            0.1,
            _user_float("web_fetch.timeout", ("MYCODINGAGENT_WEB_FETCH_TIMEOUT",), 20.0),
        )
    )
    max_bytes: int = field(
        default_factory=lambda: max(
            1024,
            _user_int("web_fetch.max_bytes", ("MYCODINGAGENT_WEB_FETCH_MAX_BYTES",), 2_000_000),
        )
    )
    max_chars: int = field(
        default_factory=lambda: max(
            1000,
            _user_int("web_fetch.max_chars", ("MYCODINGAGENT_WEB_FETCH_MAX_CHARS",), 50_000),
        )
    )
    max_redirects: int = field(
        default_factory=lambda: max(
            0,
            min(
                10,
                _user_int(
                    "web_fetch.max_redirects",
                    ("MYCODINGAGENT_WEB_FETCH_MAX_REDIRECTS",),
                    5,
                ),
            ),
        )
    )


@dataclass(frozen=True)
class NetworkConfig:
    """Runtime-managed outbound network policy for agent tools."""

    enabled: bool = field(
        default_factory=lambda: _user_bool("network.enabled", ("MYCODINGAGENT_NETWORK_ENABLED",), True)
    )
    upstream_proxy: str = field(
        default_factory=lambda: _user_str(
            "network.upstream_proxy", ("MYCODINGAGENT_NETWORK_UPSTREAM_PROXY",), "auto"
        ).strip()
    )
    allow_domains: tuple[str, ...] = field(
        default_factory=lambda: _user_list(
            "network.allow_domains", ("MYCODINGAGENT_NETWORK_ALLOW_DOMAINS",), ("*",)
        )
    )
    deny_domains: tuple[str, ...] = field(
        default_factory=lambda: _user_list(
            "network.deny_domains", ("MYCODINGAGENT_NETWORK_DENY_DOMAINS",), ()
        )
    )
    connect_timeout: float = field(
        default_factory=lambda: max(
            0.1,
            _user_float("network.connect_timeout", ("MYCODINGAGENT_NETWORK_CONNECT_TIMEOUT",), 10.0),
        )
    )
    idle_timeout: float = field(
        default_factory=lambda: max(
            1.0,
            _user_float("network.idle_timeout", ("MYCODINGAGENT_NETWORK_IDLE_TIMEOUT",), 300.0),
        )
    )
    ca_bundle: str = field(
        default_factory=lambda: _user_str(
            "network.ca_bundle", ("MYCODINGAGENT_NETWORK_CA_BUNDLE",), ""
        ).strip()
    )


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
            _user_int("mcp.reconnect_server_step", ("MYCODINGAGENT_RECONNECT_MCP_SERVER_STEP",), 10),
        )
    )


@dataclass(frozen=True)
class AppConfig:
    """应用顶层配置，聚合所有子配置模块。"""
    user_id: str = field(default_factory=_default_user_id)
    model: ModelConfig = field(default_factory=ModelConfig)
    client: ClientConfig = field(default_factory=ClientConfig)
    approval: ApprovalConfig = field(default_factory=ApprovalConfig)
    long_term_memory: LongTermMemoryConfig = field(default_factory=LongTermMemoryConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    docker: DockerConfig = field(default_factory=DockerConfig)
    skills: SkillConfig = field(default_factory=SkillConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    milvus: MilvusConfig = field(default_factory=MilvusConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    web_fetch: WebFetchConfig = field(default_factory=WebFetchConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)


CONFIG = AppConfig()
