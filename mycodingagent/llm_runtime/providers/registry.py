from __future__ import annotations

from typing import Type

from mycodingagent.llm_runtime.providers.anthropic import AnthropicProvider
from mycodingagent.llm_runtime.providers.base import InferenceProvider, ModelProfile
from mycodingagent.llm_runtime.providers.gemini import GeminiProvider
from mycodingagent.llm_runtime.providers.vendors import (
    DeepSeekProvider,
    DoubaoProvider,
    GrokProvider,
    KimiProvider,
    MetaProvider,
    MiniMaxProvider,
    OpenAIProvider,
    QwenProvider,
    ZhipuProvider,
)


PROVIDER_CLASSES: dict[str, Type] = {
    "deepseek": DeepSeekProvider,
    "qwen": QwenProvider,
    "kimi": KimiProvider,
    "doubao": DoubaoProvider,
    "zhipu": ZhipuProvider,
    "minimax": MiniMaxProvider,
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "grok": GrokProvider,
    "meta": MetaProvider,
}


def registered_provider_names() -> tuple[str, ...]:
    return tuple(sorted(PROVIDER_CLASSES))


def is_provider_registered(provider: str) -> bool:
    return provider.strip().lower() in PROVIDER_CLASSES


def create_provider(profile: ModelProfile) -> InferenceProvider:
    provider_key = profile.provider.strip().lower()
    cls = PROVIDER_CLASSES.get(provider_key)
    if cls is None:
        supported = ", ".join(registered_provider_names())
        raise ValueError(f"未知推理模型厂商：{profile.provider}。支持：{supported}")
    return cls(profile)
