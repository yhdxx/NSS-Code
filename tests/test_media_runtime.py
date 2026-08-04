from __future__ import annotations

import asyncio
import io
import json
import wave

import httpx
import pytest
from pydantic import ValidationError

from mycodingagent.configuration.settings import (
    ModelConfig,
    ModelMediaConfig,
    ModelProviderConfig,
)
from mycodingagent.media_runtime import MediaModelRuntime, MediaRuntimeError
from mycodingagent.media_runtime.source import MediaSourceError, ensure_public_http_url
from mycodingagent.tool_runtime import create_default_registry
from mycodingagent.tool_runtime.command_policy import BashPolicyEvaluator, BashPolicyStore
from mycodingagent.tool_runtime.media import AnalyzeImageParams


PNG = b"\x89PNG\r\n\x1a\nimage"
WAV = b"RIFF\x04\x00\x00\x00WAVEaudio"


def _wav_with_duration(seconds: int, frame_rate: int = 8_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(1)
        audio.setframerate(frame_rate)
        audio.writeframes(b"\x80" * frame_rate * seconds)
    return output.getvalue()


def _config(
    *,
    audio_provider: str = "zhipu",
    vision_provider: str = "zhipu",
    zhipu_api: str = "sk-zhipu",
    qwen_api: str = "sk-qwen",
) -> ModelConfig:
    return ModelConfig(
        providers={
            "zhipu": ModelProviderConfig(api=zhipu_api),
            "qwen": ModelProviderConfig(api=qwen_api),
        },
        audio=ModelMediaConfig(
            provider=audio_provider,
            model="glm-asr-2512" if audio_provider == "zhipu" else "qwen3-asr-flash",
        ),
        vision=ModelMediaConfig(
            provider=vision_provider,
            model="glm-4v-flash" if vision_provider == "zhipu" else "qwen3-vl-flash",
        ),
    )


def _run_with_client(config: ModelConfig, tmp_path, handler, operation):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = MediaModelRuntime(config, sandbox_root=tmp_path, http_client=client)
            return await operation(runtime)

    return asyncio.run(run())


def test_media_capabilities_are_disabled_independently_when_api_is_missing(tmp_path):
    runtime = MediaModelRuntime(
        _config(zhipu_api="", qwen_api="sk-qwen", audio_provider="zhipu", vision_provider="qwen"),
        sandbox_root=tmp_path,
    )

    assert runtime.audio_availability().enabled is False
    assert "model.providers.zhipu.api" in runtime.audio_availability().reason
    assert runtime.vision_availability().enabled is True


def test_default_registry_only_registers_available_media_tools(tmp_path):
    runtime = MediaModelRuntime(
        _config(zhipu_api="", qwen_api="sk-qwen", audio_provider="zhipu", vision_provider="qwen"),
        sandbox_root=tmp_path,
    )
    registry = create_default_registry(
        bash_policy_evaluator=BashPolicyEvaluator(BashPolicyStore(tmp_path / "policy.sqlite3")),
        media_runtime=runtime,
    )

    assert registry.get("TranscribeAudio") is None
    assert registry.get("AnalyzeImage") is not None


def test_zhipu_audio_uses_transcription_multipart_endpoint(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(WAV)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/audio/transcriptions")
        assert request.headers["authorization"] == "Bearer sk-zhipu"
        assert b'filename="sample.wav"' in request.content
        assert b"glm-asr-2512" in request.content
        return httpx.Response(200, json={"text": "hello world"})

    result = _run_with_client(
        _config(),
        tmp_path,
        handler,
        lambda runtime: runtime.transcribe_audio("sample.wav"),
    )

    assert result == {"provider": "zhipu", "model": "glm-asr-2512", "text": "hello world"}


def test_qwen_audio_uses_input_audio_data_url(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(WAV)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        audio_item = payload["messages"][0]["content"][0]
        assert payload["model"] == "qwen3-asr-flash"
        assert audio_item["type"] == "input_audio"
        assert audio_item["input_audio"]["data"].startswith("data:audio/wav;base64,")
        return httpx.Response(200, json={"choices": [{"message": {"content": "transcript"}}]})

    result = _run_with_client(
        _config(audio_provider="qwen"),
        tmp_path,
        handler,
        lambda runtime: runtime.transcribe_audio("sample.wav"),
    )

    assert result["text"] == "transcript"


def test_qwen_vision_sends_multiple_images_in_one_request(tmp_path):
    (tmp_path / "one.png").write_bytes(PNG)
    (tmp_path / "two.png").write_bytes(PNG)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        content = payload["messages"][0]["content"]
        assert [item["type"] for item in content] == ["image_url", "image_url", "text"]
        assert content[-1]["text"] == "compare colors"
        return httpx.Response(200, json={"choices": [{"message": {"content": "comparison"}}]})

    result = _run_with_client(
        _config(vision_provider="qwen"),
        tmp_path,
        handler,
        lambda runtime: runtime.analyze_images(["one.png", "two.png"], "compare colors"),
    )

    assert calls == 1
    assert result["image_count"] == 2
    assert result["strategy"] == "native_multi_image"
    assert result["text"] == "comparison"


def test_zhipu_multi_image_comparison_collects_each_image_then_synthesizes(tmp_path):
    (tmp_path / "one.png").write_bytes(PNG)
    (tmp_path / "two.png").write_bytes(PNG)
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        content = payload["messages"][0]["content"]
        if len(requests) <= 2:
            assert [item["type"] for item in content] == ["image_url", "text"]
            answer = f"observation {len(requests)}"
        else:
            assert [item["type"] for item in content] == ["text"]
            assert "[图片 1]" in content[0]["text"]
            assert "observation 2" in content[0]["text"]
            answer = "synthesized comparison"
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

    result = _run_with_client(
        _config(),
        tmp_path,
        handler,
        lambda runtime: runtime.analyze_images(["one.png", "two.png"], "compare layout"),
    )

    assert len(requests) == 3
    assert result["strategy"] == "per_image_then_synthesis"
    assert result["text"] == "synthesized comparison"


@pytest.mark.parametrize("count", [0, 9])
def test_analyze_image_tool_rejects_source_counts_outside_one_to_eight(count):
    with pytest.raises(ValidationError):
        AnalyzeImageParams(sources=["image.png"] * count, query="compare")


@pytest.mark.parametrize("sources", [[], ["image.png"] * 9])
def test_media_runtime_enforces_multi_image_count_without_tool_validation(tmp_path, sources):
    runtime = MediaModelRuntime(_config(), sandbox_root=tmp_path)

    with pytest.raises(MediaRuntimeError, match="1 到 8 张"):
        asyncio.run(runtime.analyze_images(sources, "compare"))


def test_zhipu_wav_over_duration_limit_is_rejected_without_api_call(tmp_path):
    (tmp_path / "long.wav").write_bytes(_wav_with_duration(31))

    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("超限音频不应调用远程 API")

    async def operation(runtime):
        with pytest.raises(MediaRuntimeError, match="30 秒限制"):
            await runtime.transcribe_audio("long.wav")

    _run_with_client(_config(), tmp_path, handler, operation)


def test_media_local_path_cannot_escape_workspace(tmp_path):
    outside = tmp_path.parent / "outside.wav"
    outside.write_bytes(WAV)

    async def operation(runtime):
        with pytest.raises(Exception, match="沙箱之外"):
            await runtime.transcribe_audio(str(outside))

    _run_with_client(_config(), tmp_path, lambda _request: None, operation)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/media.png",
        "http://[::1]/media.png",
        "http://localhost/media.png",
        "file:///tmp/media.png",
        "https://user:pass@example.com/media.png",
    ],
)
def test_media_url_rejects_non_public_or_credentialed_targets(url):
    with pytest.raises(MediaSourceError):
        asyncio.run(ensure_public_http_url(url))


def test_media_config_rejects_unsupported_provider():
    config = _config()
    config = ModelConfig(
        providers=config.providers,
        audio=ModelMediaConfig(provider="openai", model="whisper"),
        vision=config.vision,
    )

    assert any(
        "model.audio.provider=openai" in error
        for error in config.validation_errors(require_long_term_memory=False)
    )
