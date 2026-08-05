from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mycodingagent.configuration.bootstrap import USER_CONFIG_PATH
from mycodingagent.configuration.settings import (
    CONFIG,
    ModelConfig,
    ModelLongTermMemoryConfig,
    ModelMediaConfig,
    ModelProviderConfig,
    ModelProfileConfig,
    _raw_env_str,
)
from mycodingagent.llm_runtime.providers import (
    InferenceProvider,
    ModelProfile,
    create_provider,
    is_provider_registered,
    registered_provider_names,
)


class ModelConfigError(ValueError):
    pass


class ModelManager:
    def __init__(self, *, config_path: Path = USER_CONFIG_PATH, model_config: ModelConfig | None = None) -> None:
        self.config_path = config_path
        self.model_config = model_config or CONFIG.model
        self._providers: dict[str, InferenceProvider] = {}

    @property
    def active_profile_key(self) -> str:
        return self.model_config.active

    @property
    def active_model(self) -> str:
        return self.active_profile.model

    @property
    def active_profile(self) -> ModelProfile:
        return self.profile(self.model_config.active)

    def profile(self, key: str) -> ModelProfile:
        config = self.model_config.profiles.get(key)
        if config is None:
            raise ModelConfigError(f"未找到推理模型 profile：{key}")
        provider_config = self.model_config.provider(config.provider) or ModelProviderConfig()
        return _runtime_profile(key, config, provider_config)

    def provider(self, key: str) -> InferenceProvider:
        profile = self.profile(key)
        cached = self._providers.get(key)
        if cached is not None and cached.profile == profile:
            return cached
        if cached is not None:
            self._providers.pop(key, None)
        provider = create_provider(profile)
        self._providers[key] = provider
        return provider

    def active_provider(self) -> InferenceProvider:
        return self.provider(self.model_config.active)

    def storage_provider(self) -> InferenceProvider:
        key = self.model_config.long_term_memory.storage or self.model_config.active
        return self.provider(key)

    def search_provider(self) -> InferenceProvider:
        key = self.model_config.long_term_memory.search or self.model_config.active
        return self.provider(key)

    def research_provider(self) -> InferenceProvider:
        return self.provider(self.model_config.research or self.model_config.active)

    def validation_errors(
        self,
        *,
        require_long_term_memory: bool = True,
        require_research: bool = True,
    ) -> list[str]:
        errors = self.model_config.validation_errors(
            require_long_term_memory=require_long_term_memory,
            require_research=require_research,
        )
        for key, profile in self.model_config.profiles.items():
            if profile.provider and not is_provider_registered(profile.provider):
                errors.append(
                    f"model.profiles.{key}.provider={profile.provider} 未注册；支持：{', '.join(registered_provider_names())}"
                )
        return errors

    def configured_profiles(self) -> dict[str, ModelProfile]:
        return {
            key: _runtime_profile(
                key,
                value,
                self.model_config.provider(value.provider) or ModelProviderConfig(),
            )
            for key, value in self.model_config.profiles.items()
        }

    def configured_profiles_with_api(self) -> dict[str, ModelProfile]:
        return {
            key: profile
            for key, profile in self.configured_profiles().items()
            if profile.api and is_provider_registered(profile.provider)
        }

    def profiles_by_provider(self) -> dict[str, list[ModelProfile]]:
        grouped: dict[str, list[ModelProfile]] = {}
        for profile in self.configured_profiles_with_api().values():
            grouped.setdefault(profile.provider, []).append(profile)
        return grouped

    def reload(self) -> None:
        self.model_config = load_model_config(self.config_path)

    def switch_active(self, profile_key: str, *, reasoning: str | dict[str, Any] | None = None) -> None:
        self._update_model_config(active=profile_key, profile_key=profile_key, reasoning=reasoning)

    def switch_long_term_memory(
        self,
        target: str,
        profile_key: str,
        *,
        reasoning: str | dict[str, Any] | None = None,
    ) -> None:
        if target not in {"storage", "search"}:
            raise ValueError(f"unknown long-term memory model target: {target}")
        self._update_model_config(ltm_target=target, ltm_profile_key=profile_key, profile_key=profile_key, reasoning=reasoning)

    async def close(self) -> None:
        providers = list(self._providers.values())
        self._providers.clear()
        await asyncio.gather(*(provider.close() for provider in providers), return_exceptions=True)

    def _update_model_config(
        self,
        *,
        active: str | None = None,
        ltm_target: str | None = None,
        ltm_profile_key: str | None = None,
        profile_key: str,
        reasoning: str | dict[str, Any] | None = None,
    ) -> None:
        raw = _read_config_json(self.config_path)
        model_section = raw.setdefault("model", {})
        profiles = model_section.setdefault("profiles", {})
        if profile_key not in profiles:
            raise ModelConfigError(f"未找到推理模型 profile：{profile_key}")
        if active is not None:
            model_section["active"] = active
        if ltm_target is not None and ltm_profile_key is not None:
            ltm = model_section.setdefault("long_term_memory", {})
            ltm[ltm_target] = ltm_profile_key
        if reasoning is not None:
            profile_data = profiles.setdefault(profile_key, {})
            profile_data["reasoning"] = reasoning
        _write_config_json(self.config_path, raw)
        self.reload()


def load_model_config(config_path: Path = USER_CONFIG_PATH) -> ModelConfig:
    raw = _read_config_json(config_path)
    model = raw.get("model") if isinstance(raw.get("model"), dict) else {}
    active = _raw_env_str(model, "active", ("MYCODINGAGENT_MODEL_ACTIVE",), "main") or "main"
    providers_raw = model.get("providers") if isinstance(model.get("providers"), dict) else {}
    providers: dict[str, ModelProviderConfig] = {}
    for key, value in providers_raw.items():
        provider_key = str(key).strip().lower()
        if provider_key:
            providers[provider_key] = ModelProviderConfig.from_raw(value, provider_key=provider_key)
    profiles_raw = model.get("profiles") if isinstance(model.get("profiles"), dict) else {}
    profiles: dict[str, ModelProfileConfig] = {}
    for key, value in profiles_raw.items():
        profile_key = str(key).strip()
        if profile_key:
            profiles[profile_key] = ModelProfileConfig.from_raw(value, profile_key=profile_key)
    if not profiles:
        profiles = dict(CONFIG.model.profiles)
    if not providers:
        provider_keys = sorted({profile.provider for profile in profiles.values() if profile.provider})
        providers = (
            {
                provider_key: ModelProviderConfig.from_raw({}, provider_key=provider_key)
                for provider_key in provider_keys
            }
            if provider_keys
            else dict(CONFIG.model.providers)
        )
    ltm_raw = model.get("long_term_memory") if isinstance(model.get("long_term_memory"), dict) else {}
    audio_raw = model.get("audio") if isinstance(model.get("audio"), dict) else {}
    vision_raw = model.get("vision") if isinstance(model.get("vision"), dict) else {}
    return ModelConfig(
        active=active,
        providers=providers,
        profiles=profiles,
        research=_raw_env_str(
            model,
            "research",
            ("MYCODINGAGENT_MODEL_RESEARCH",),
            active,
        ) or active,
        long_term_memory=ModelLongTermMemoryConfig(
            storage=_raw_env_str(
                ltm_raw,
                "storage",
                ("MYCODINGAGENT_MODEL_LONG_TERM_MEMORY_STORAGE",),
                active,
            ) or active,
            search=_raw_env_str(
                ltm_raw,
                "search",
                ("MYCODINGAGENT_MODEL_LONG_TERM_MEMORY_SEARCH",),
                "memory_search",
            ) or "memory_search",
        ),
        audio=ModelMediaConfig.from_raw(
            audio_raw,
            capability="audio",
            default_provider="qwen",
            default_model="qwen3-asr-flash",
        ),
        vision=ModelMediaConfig.from_raw(
            vision_raw,
            capability="vision",
            default_provider="zhipu",
            default_model="glm-4v-flash",
        ),
    )


def _runtime_profile(
    key: str,
    config: ModelProfileConfig,
    provider_config: ModelProviderConfig,
) -> ModelProfile:
    timeout = config.timeout if config.timeout is not None else provider_config.timeout
    return ModelProfile(
        key=key,
        provider=config.provider,
        model=config.model,
        api=provider_config.api,
        base_url=provider_config.base_url,
        reasoning=config.reasoning,
        timeout=timeout,
        extra_headers={**provider_config.extra_headers, **config.extra_headers},
        extra_body={**provider_config.extra_body, **config.extra_body},
    )


def _read_config_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelConfigError(f"配置文件 JSON 无效：{path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelConfigError(f"配置文件必须是 JSON 对象：{path}")
    return payload


def _write_config_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
