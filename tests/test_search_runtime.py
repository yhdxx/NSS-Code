from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from mycodingagent.configuration.settings import SearchConfig
from mycodingagent.network_access import NetworkAccessRuntime
from mycodingagent.search_runtime import SearchRuntime, SearchRuntimeError
from mycodingagent.search_runtime.runtime import SEARCH_USER_AGENT
from mycodingagent.tool_runtime.search_web import FetchUrl, SearchWeb


def _config(**overrides) -> SearchConfig:
    values = {
        "enabled": True,
        "endpoint": "https://search.test/search",
        "timeout": 2.0,
        "max_results": 10,
        "max_query_chars": 500,
        "language": "zh-CN",
        "safesearch": 0,
        "fetch_max_bytes": 100_000,
        "fetch_max_chars": 50_000,
        "max_redirects": 5,
    }
    values.update(overrides)
    return SearchConfig(**values)


def test_searxng_search_normalizes_deduplicates_and_limits_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "Playwright Python"
        assert request.url.params["format"] == "json"
        assert request.url.params["categories"] == "general,it"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "One", "url": "https://example.com/1", "content": "first", "engines": ["bing"]},
                    {"title": "Duplicate", "url": "https://example.com/1", "content": "again"},
                    {"title": "Two", "url": "https://example.com/2", "content": "second"},
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = SearchRuntime(_config(), http_client=client)
            return await runtime.search(
                "  Playwright   Python ",
                categories=["it", "general"],
                max_results=2,
            )

    result = asyncio.run(run())

    assert result["query"] == "Playwright Python"
    assert result["result_count"] == 2
    assert [item["url"] for item in result["results"]] == [
        "https://example.com/1",
        "https://example.com/2",
    ]


def test_search_disabled_fails_without_network_call():
    runtime = SearchRuntime(_config(enabled=False))

    with pytest.raises(SearchRuntimeError, match="search.enabled=false"):
        asyncio.run(runtime.search("docs"))


def test_search_reports_local_service_recovery_failure_without_network_call():
    runtime = SearchRuntime(_config())
    runtime.set_service_error("SearXNG 会话容器启动失败")

    with pytest.raises(SearchRuntimeError, match="本地 SearXNG 自动恢复失败"):
        asyncio.run(runtime.search("docs"))


def test_search_rejects_invalid_json():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = SearchRuntime(_config(), http_client=client)
            return await runtime.search("docs")

    with pytest.raises(SearchRuntimeError, match="无效 JSON"):
        asyncio.run(run())


def test_search_reports_unresponsive_upstream_engines():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [],
                "unresponsive_engines": [
                    ["duckduckgo", "timeout"],
                    ["wikipedia", "HTTP connection error"],
                ],
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = SearchRuntime(_config(), http_client=client)
            return await runtime.search("docs")

    with pytest.raises(SearchRuntimeError, match="duckduckgo: timeout"):
        asyncio.run(run())


def test_search_does_not_retry_non_retryable_http_status():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, text="missing")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = SearchRuntime(_config(), http_client=client)
            return await runtime.search("docs")

    with pytest.raises(SearchRuntimeError, match="搜索请求失败") as raised:
        asyncio.run(run())
    assert calls == 1
    assert raised.value.error_code == "http_404"
    assert raised.value.retryable is False


def test_fetch_url_extracts_html_text():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>Docs</title><style>hidden</style></head><body>Hello <b>world</b><script>bad</script></body></html>",
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = SearchRuntime(_config(), http_client=client)
            return await runtime.fetch_url("https://example.com/docs")

    result = asyncio.run(run())

    assert result["title"] == "Docs"
    assert result["text"] == "Hello world"
    assert result["truncated"] is False


def test_fetch_url_stops_when_stream_exceeds_limit():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 101)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = SearchRuntime(_config(fetch_max_bytes=100), http_client=client)
            return await runtime.fetch_url("https://example.com/large")

    with pytest.raises(SearchRuntimeError, match="大小限制"):
        asyncio.run(run())


def test_fetch_preserves_structured_proxy_error_without_retry():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            403,
            json={
                "error_code": "domain_denied",
                "message": "目标域名被网络策略拒绝",
                "retryable": False,
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = SearchRuntime(_config(), http_client=client)
            return await runtime.fetch_url("https://blocked.example")

    with pytest.raises(SearchRuntimeError) as raised:
        asyncio.run(run())

    assert calls == 1
    assert raised.value.error_code == "domain_denied"
    assert raised.value.retryable is False
    assert "目标域名被网络策略拒绝" in str(raised.value)


def test_proxy_retryable_flag_overrides_generic_5xx_classification():
    response = httpx.Response(
        502,
        request=httpx.Request("GET", "https://example.com"),
        json={
            "error_code": "upstream_proxy_rejected",
            "message": "上游代理明确拒绝",
            "retryable": False,
        },
    )

    from mycodingagent.search_runtime.runtime import _request_failure

    error = _request_failure("网页读取失败", httpx.HTTPStatusError("bad gateway", request=response.request, response=response))

    assert error.error_code == "upstream_proxy_rejected"
    assert error.retryable is False


def test_structured_non_retryable_502_is_not_retried():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            502,
            json={
                "error_code": "upstream_proxy_rejected",
                "message": "上游代理明确拒绝",
                "retryable": False,
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = SearchRuntime(_config(), http_client=client)
            return await runtime.search("docs")

    with pytest.raises(SearchRuntimeError) as raised:
        asyncio.run(run())

    assert calls == 1
    assert raised.value.error_code == "upstream_proxy_rejected"
    assert raised.value.retryable is False


def test_fetch_url_revalidates_each_redirect(monkeypatch):
    checked: list[str] = []

    async def allow(url: str) -> None:
        checked.append(url)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="done")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = SearchRuntime(_config(), http_client=client)
            monkeypatch.setattr(runtime, "_validate_fetch_url", allow)
            return await runtime.fetch_url("https://example.com/start")

    result = asyncio.run(run())

    assert checked == ["https://example.com/start", "https://example.com/final"]
    assert result["url"] == "https://example.com/final"
    assert result["text"] == "done"


def test_search_off_blocks_search_but_allows_localhost_fetch():
    access = NetworkAccessRuntime(enabled=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "localhost"
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="local")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            runtime = SearchRuntime(_config(), http_client=client, network_access=access)
            with pytest.raises(SearchRuntimeError, match="智能搜索已关闭"):
                await runtime.search("docs")
            return await runtime.fetch_url("http://localhost:3000/health")

    result = asyncio.run(run())

    assert result["text"] == "local"


def test_search_off_blocks_external_fetch():
    runtime = SearchRuntime(_config(), network_access=NetworkAccessRuntime(enabled=False))

    with pytest.raises(SearchRuntimeError, match="仅允许访问 localhost"):
        asyncio.run(runtime.fetch_url("https://example.com"))


def test_search_tools_return_structured_results():
    class FakeRuntime:
        async def search(self, *_args, **_kwargs):
            return {"results": [{"url": "https://example.com"}]}

        async def fetch_url(self, *_args, **_kwargs):
            return {"url": "https://example.com", "text": "ok"}

    runtime = FakeRuntime()
    search = SearchWeb(runtime)
    fetch = FetchUrl(runtime)

    search_result = asyncio.run(search.execute(search.params_model(query="docs", intent="搜索文档")))
    fetch_result = asyncio.run(
        fetch.execute(fetch.params_model(url="https://example.com", intent="读取文档"))
    )

    assert json.loads(search_result.output)["results"][0]["url"] == "https://example.com"
    assert json.loads(fetch_result.output)["text"] == "ok"


def test_search_tool_returns_structured_non_retryable_error():
    class FakeRuntime:
        async def search(self, *_args, **_kwargs):
            raise SearchRuntimeError(
                "目标域名被拒绝",
                error_code="domain_denied",
                retryable=False,
                suggested_action="不要重复请求。",
            )

    search = SearchWeb(FakeRuntime())
    result = asyncio.run(search.execute(search.params_model(query="docs", intent="搜索文档")))

    payload = json.loads(result.output)
    assert result.is_error is True
    assert payload == {
        "error_code": "domain_denied",
        "message": "目标域名被拒绝",
        "retryable": False,
        "suggested_action": "不要重复请求。",
    }


def test_managed_searxng_endpoint_is_explicitly_direct(monkeypatch):
    runtime = SearchRuntime(_config(), proxy_url="http://proxy.test:3128")
    calls: list[bool] = []

    async def request(_method, _url, *, use_proxy, **_kwargs):
        calls.append(use_proxy)
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(runtime, "_request", request)
    runtime.set_endpoint("http://172.24.0.3:8080/search", route="managed_local")

    result = asyncio.run(runtime.search("docs"))

    assert result["results"] == []
    assert calls == [False]


def test_custom_public_searxng_endpoint_uses_managed_proxy(monkeypatch):
    runtime = SearchRuntime(_config(), proxy_url="http://proxy.test:3128")
    calls: list[bool] = []

    async def request(_method, _url, *, use_proxy, **_kwargs):
        calls.append(use_proxy)
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(runtime, "_request", request)
    runtime.set_endpoint("https://search.example/search", route="public")

    asyncio.run(runtime.search("docs"))

    assert calls == [True]


def test_owned_http_clients_use_identifiable_user_agent():
    runtime = SearchRuntime(_config(), proxy_url="http://proxy.test:3128")

    direct = runtime._http_client(use_proxy=False)
    proxied = runtime._http_client(use_proxy=True)

    assert direct.headers["user-agent"] == SEARCH_USER_AGENT
    assert proxied.headers["user-agent"] == SEARCH_USER_AGENT
    asyncio.run(runtime.close())


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.1/data",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_fetch_rejects_private_ip_literals_without_network_call(url):
    runtime = SearchRuntime(_config())

    with pytest.raises(SearchRuntimeError) as raised:
        asyncio.run(runtime.fetch_url(url))

    assert raised.value.error_code == "private_target_denied"
    assert raised.value.retryable is False
