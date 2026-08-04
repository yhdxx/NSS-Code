from __future__ import annotations

import json
from pathlib import Path

from mycodingagent.commands.handlers import build_command_registry
from mycodingagent.configuration.settings import (
    ModelConfig,
    ModelLongTermMemoryConfig,
    ModelMediaConfig,
    ModelProfileConfig,
    ModelProviderConfig,
)
from mycodingagent.llm_runtime.model_manager import ModelManager, load_model_config
from mycodingagent.llm_runtime.providers import registered_provider_names
from mycodingagent.llm_runtime.providers.vendors import DeepSeekProvider, OpenAIProvider


def _clear_provider_env(monkeypatch, provider: str) -> None:
    provider_part = provider.upper()
    for name in (
        f"MYCODINGAGENT_MODEL_PROVIDER_{provider_part}_API",
        f"MYCODINGAGENT_MODEL_PROVIDER_{provider_part}_BASE_URL",
        f"{provider_part}_API_KEY",
        f"{provider_part}_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    for name in {
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "QWEN_API_KEY",
        "QWEN_BASE_URL",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_BASE_URL",
    }:
        monkeypatch.delenv(name, raising=False)


def _write_model_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "model": {
                    "active": "deepseek_main",
                    "providers": {
                        "deepseek": {"api": "sk-deepseek", "base_url": "https://api.deepseek.com"},
                        "qwen": {"api": "sk-qwen"},
                        "openai": {"api": ""},
                    },
                    "profiles": {
                        "deepseek_main": {
                            "provider": "deepseek",
                            "model": "deepseek-v4-pro",
                        },
                        "qwen_main": {
                            "provider": "qwen",
                            "model": "qwen-plus",
                        },
                        "missing_api": {
                            "provider": "openai",
                            "model": "gpt-5",
                        },
                    },
                    "long_term_memory": {
                        "storage": "deepseek_main",
                        "search": "deepseek_main",
                    },
                },
                "client": {"max_tool_rounds": 50},
            }
        ),
        encoding="utf-8",
    )


def test_provider_registry_includes_required_vendors():
    assert set(registered_provider_names()) >= {
        "anthropic",
        "deepseek",
        "doubao",
        "gemini",
        "grok",
        "kimi",
        "meta",
        "minimax",
        "openai",
        "qwen",
        "zhipu",
    }


def test_model_manager_groups_only_configured_profiles_with_api(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch, "openai")
    config_path = tmp_path / "config.json"
    _write_model_config(config_path)
    manager = ModelManager(config_path=config_path, model_config=load_model_config(config_path))

    grouped = manager.profiles_by_provider()

    assert [profile.key for profile in grouped["deepseek"]] == ["deepseek_main"]
    assert grouped["deepseek"][0].api == "sk-deepseek"
    assert grouped["deepseek"][0].base_url == "https://api.deepseek.com"
    assert [profile.key for profile in grouped["qwen"]] == ["qwen_main"]
    assert "openai" not in grouped


def test_model_provider_api_falls_back_to_environment(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch, "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://env.deepseek.example")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "model": {
                    "active": "main",
                    "providers": {"deepseek": {"api": "", "base_url": ""}},
                    "profiles": {"main": {"provider": "deepseek", "model": "deepseek-v4-pro"}},
                    "long_term_memory": {"storage": "main", "search": "main"},
                }
            }
        ),
        encoding="utf-8",
    )
    manager = ModelManager(config_path=config_path, model_config=load_model_config(config_path))

    profile = manager.active_profile

    assert manager.validation_errors() == []
    assert profile.api == "sk-from-env"
    assert profile.base_url == "https://env.deepseek.example"


def test_model_provider_config_overrides_environment(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch, "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    config_path = tmp_path / "config.json"
    _write_model_config(config_path)
    manager = ModelManager(config_path=config_path, model_config=load_model_config(config_path))

    assert manager.active_profile.api == "sk-deepseek"


def test_model_manager_loads_media_models_without_duplicate_api_keys(tmp_path):
    config_path = tmp_path / "config.json"
    _write_model_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["model"]["audio"] = {"provider": "qwen", "model": "qwen3-asr-flash"}
    payload["model"]["vision"] = {"provider": "qwen", "model": "qwen3-vl-flash"}
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    config = load_model_config(config_path)

    assert config.audio == ModelMediaConfig(provider="qwen", model="qwen3-asr-flash")
    assert config.vision == ModelMediaConfig(provider="qwen", model="qwen3-vl-flash")
    assert config.provider("qwen").api == "sk-qwen"


def test_missing_provider_entry_can_be_supplied_by_environment(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch, "qwen")
    monkeypatch.setenv("QWEN_API_KEY", "sk-qwen-env")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "model": {
                    "active": "qwen_main",
                    "profiles": {"qwen_main": {"provider": "qwen", "model": "qwen-plus"}},
                    "long_term_memory": {"storage": "qwen_main", "search": "qwen_main"},
                }
            }
        ),
        encoding="utf-8",
    )
    manager = ModelManager(config_path=config_path, model_config=load_model_config(config_path))

    assert manager.validation_errors() == []
    assert manager.active_profile.api == "sk-qwen-env"


def test_model_manager_switches_active_profile_and_persists_reasoning(tmp_path):
    config_path = tmp_path / "config.json"
    _write_model_config(config_path)
    manager = ModelManager(config_path=config_path, model_config=load_model_config(config_path))

    manager.switch_active("qwen_main", reasoning="enabled")

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["model"]["active"] == "qwen_main"
    assert payload["model"]["profiles"]["qwen_main"]["reasoning"] == "enabled"
    assert manager.active_profile_key == "qwen_main"
    assert manager.active_model == "qwen-plus"


def test_model_manager_switches_long_term_memory_target(tmp_path):
    config_path = tmp_path / "config.json"
    _write_model_config(config_path)
    manager = ModelManager(config_path=config_path, model_config=load_model_config(config_path))

    manager.switch_long_term_memory("search", "qwen_main", reasoning="disabled")

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["model"]["long_term_memory"]["search"] == "qwen_main"
    assert payload["model"]["profiles"]["qwen_main"]["reasoning"] == "disabled"
    assert manager.model_config.long_term_memory.search == "qwen_main"


def test_model_manager_reports_only_critical_model_config_errors(monkeypatch):
    _clear_provider_env(monkeypatch, "deepseek")
    manager = ModelManager(
        model_config=ModelConfig(
            active="main",
            providers={"deepseek": ModelProviderConfig(api="")},
            profiles={
                "main": ModelProfileConfig(provider="deepseek", model=""),
            },
            long_term_memory=ModelLongTermMemoryConfig(storage="main", search="unknown"),
        )
    )

    errors = manager.validation_errors(require_long_term_memory=True)

    assert "model.profiles.main 缺少必要字段：model" in errors
    assert "model.providers.deepseek.api 缺少必要字段：api" in errors
    assert "model.long_term_memory.search 指向不存在的 profile：unknown" in errors


def test_model_switch_commands_are_registered():
    registry = build_command_registry()

    assert registry.match("/model") is not None
    assert registry.match("/long_mem_model_storage") is not None
    assert registry.match("/long_mem_model_search") is not None


def test_vendor_specific_reasoning_config_is_normalized():
    deepseek = object.__new__(DeepSeekProvider)
    openai = object.__new__(OpenAIProvider)

    assert deepseek._reasoning_payload({"thinking": "disabled"}) == {"thinking": {"type": "disabled"}}
    assert openai._reasoning_payload({"effort": "high"}) == {"reasoning_effort": "high"}
