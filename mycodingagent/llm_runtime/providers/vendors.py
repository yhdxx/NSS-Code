from __future__ import annotations

from typing import Any

from mycodingagent.llm_runtime.providers.base import ModelProfile, ReasoningOption
from mycodingagent.llm_runtime.providers.openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    provider_name = "deepseek"
    default_base_url = "https://api.deepseek.com"
    models = ("deepseek-chat", "deepseek-reasoner", "deepseek-v4-pro", "deepseek-v4-flash")
    _reasoning_options = (
        ReasoningOption("enabled", "开启思考", "向 DeepSeek 兼容接口传递 thinking enabled。"),
        ReasoningOption("disabled", "关闭思考", "向 DeepSeek 兼容接口传递 thinking disabled。"),
    )

    def _reasoning_payload(self, reasoning: str | dict[str, Any] | None) -> dict[str, Any]:
        if isinstance(reasoning, dict):
            return dict(reasoning)
        if reasoning in {"enabled", "able", "on", "true"}:
            return {"thinking": {"type": "enabled"}}
        if reasoning in {"disabled", "disable", "off", "false"}:
            return {"thinking": {"type": "disabled"}}
        return {}


class QwenProvider(OpenAICompatibleProvider):
    provider_name = "qwen"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    models = ("qwen-plus", "qwen-max", "qwen3-coder-plus", "qwen3-max")


class KimiProvider(OpenAICompatibleProvider):
    provider_name = "kimi"
    default_base_url = "https://api.moonshot.cn/v1"
    models = ("kimi-k2", "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k")


class DoubaoProvider(OpenAICompatibleProvider):
    provider_name = "doubao"
    default_base_url = "https://ark.cn-beijing.volces.com/api/v3"
    models = ("doubao-seed-1-6", "doubao-seed-1-6-thinking", "doubao-1-5-pro-32k")


class ZhipuProvider(OpenAICompatibleProvider):
    provider_name = "zhipu"
    default_base_url = "https://open.bigmodel.cn/api/paas/v4"
    models = ("glm-4.5", "glm-4.5-air", "glm-4-plus", "glm-4-flash")


class MiniMaxProvider(OpenAICompatibleProvider):
    provider_name = "minimax"
    default_base_url = "https://api.minimax.chat/v1"
    models = ("MiniMax-M1", "MiniMax-Text-01")


class OpenAIProvider(OpenAICompatibleProvider):
    provider_name = "openai"
    default_base_url = "https://api.openai.com/v1"
    models = ("gpt-5", "gpt-5-mini", "gpt-4.1", "o4-mini")
    _reasoning_options = (
        ReasoningOption("low", "低", "OpenAI reasoning effort: low。"),
        ReasoningOption("medium", "中", "OpenAI reasoning effort: medium。"),
        ReasoningOption("high", "高", "OpenAI reasoning effort: high。"),
    )

    def _reasoning_payload(self, reasoning: str | dict[str, Any] | None) -> dict[str, Any]:
        if isinstance(reasoning, dict):
            return dict(reasoning)
        if reasoning in {"low", "medium", "high"}:
            return {"reasoning_effort": reasoning}
        return {}


class GrokProvider(OpenAICompatibleProvider):
    provider_name = "grok"
    default_base_url = "https://api.x.ai/v1"
    models = ("grok-4", "grok-3", "grok-3-mini")
    _reasoning_options = (
        ReasoningOption("low", "低", "Grok reasoning effort: low。"),
        ReasoningOption("medium", "中", "Grok reasoning effort: medium。"),
        ReasoningOption("high", "高", "Grok reasoning effort: high。"),
    )

    def _reasoning_payload(self, reasoning: str | dict[str, Any] | None) -> dict[str, Any]:
        if isinstance(reasoning, dict):
            return dict(reasoning)
        if reasoning in {"low", "medium", "high"}:
            return {"reasoning_effort": reasoning}
        return {}


class MetaProvider(OpenAICompatibleProvider):
    provider_name = "meta"
    default_base_url = "https://api.llama.com/compat/v1"
    models = ("Llama-4-Maverick-17B-128E-Instruct-FP8", "Llama-4-Scout-17B-16E-Instruct-FP8")


def clone_profile_with_model(profile: ModelProfile, model: str) -> ModelProfile:
    return ModelProfile(
        key=profile.key,
        provider=profile.provider,
        model=model,
        api=profile.api,
        base_url=profile.base_url,
        reasoning=profile.reasoning,
        timeout=profile.timeout,
        extra_headers=profile.extra_headers,
        extra_body=profile.extra_body,
    )
