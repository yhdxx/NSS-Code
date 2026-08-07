from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from mycodingagent.configuration.settings import WebFetchConfig
from mycodingagent.network_access import NetworkAccessRuntime
from mycodingagent.tool_runtime import create_default_registry
from mycodingagent.tool_runtime.fetch_url import FetchUrl, FetchUrlParams
from mycodingagent.web_fetch_runtime import WebFetchRuntime, WebFetchRuntimeError
from mycodingagent.web_fetch_runtime.runtime import _request_failure


def _config(**overrides) -> WebFetchConfig:
    values = {
        "enabled": True,
        "timeout": 2.0,
        "max_bytes": 2_000_000,
        "max_chars": 50_000,
        "max_redirects": 5,
    }
    values.update(overrides)
    return WebFetchConfig(**values)


def test_fetch_url_extracts_html_title_and_text():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"].startswith("myCodingAgent/")
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>Example</title><style>x</style></head><body>Hello <b>world</b></body></html>",
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = WebFetchRuntime(_config(), http_client=client)
            return await runtime.fetch_url("https://example.test/page")

    payload = asyncio.run(run())

    assert payload["title"] == "Example"
    assert payload["text"] == "Hello world"
    assert payload["truncated"] is False


def test_fetch_url_formats_json_and_honors_character_limit():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, json={"value": "abcdef"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = WebFetchRuntime(_config(), http_client=client)
            return await runtime.fetch_url("https://example.test/data", max_chars=10)

    payload = asyncio.run(run())

    assert payload["text"] == '{ "value":'
    assert payload["truncated"] is True


def test_fetch_url_validates_every_redirect_target():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = WebFetchRuntime(_config(), http_client=client)
            await runtime.fetch_url("https://example.test/start")

    with pytest.raises(WebFetchRuntimeError, match="私网") as raised:
        asyncio.run(run())
    assert raised.value.error_code == "private_target_denied"


def test_network_off_blocks_public_fetch_but_allows_localhost():
    access = NetworkAccessRuntime(enabled=False)
    runtime = WebFetchRuntime(_config(), network_access=access)

    with pytest.raises(WebFetchRuntimeError, match="网络访问已关闭"):
        asyncio.run(runtime.fetch_url("https://example.test"))

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="local")

    async def run_local():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            local_runtime = WebFetchRuntime(_config(), http_client=client, network_access=access)
            return await local_runtime.fetch_url("http://localhost:3000")

    assert asyncio.run(run_local())["text"] == "local"


def test_fetch_url_rejects_oversized_stream():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 101)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = WebFetchRuntime(_config(max_bytes=100), http_client=client)
            await runtime.fetch_url("https://example.test/large")

    with pytest.raises(WebFetchRuntimeError, match="大小限制") as raised:
        asyncio.run(run())
    assert raised.value.error_code == "response_too_large"


def test_fetch_url_disabled_returns_structured_tool_error():
    tool = FetchUrl(WebFetchRuntime(_config(enabled=False)))

    result = asyncio.run(tool.execute(FetchUrlParams(url="https://example.test")))
    payload = json.loads(result.output)

    assert result.is_error is True
    assert payload["error_code"] == "web_fetch_disabled"


def test_registry_only_registers_fetch_url_when_runtime_is_enabled():
    runtime = WebFetchRuntime(_config())

    enabled = create_default_registry(web_fetch_runtime=runtime, bash_policy_evaluator=object())
    disabled = create_default_registry(web_fetch_runtime=None, bash_policy_evaluator=object())

    assert enabled.get("FetchUrl") is not None
    assert disabled.get("FetchUrl") is None


def test_proxy_auth_failure_is_not_retryable():
    request = httpx.Request("GET", "https://example.test")
    error = httpx.ProxyError("407 Proxy Authentication Required", request=request)

    failure = _request_failure("网页读取失败", error)

    assert failure.error_code == "network_transport_error"
    assert failure.retryable is False
