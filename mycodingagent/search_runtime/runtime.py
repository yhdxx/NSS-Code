from __future__ import annotations

import asyncio
import ipaddress
import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

import httpx

from mycodingagent.configuration.settings import CONFIG, SearchConfig
from mycodingagent.network_access import NetworkAccessRuntime, is_local_http_url

SEARCH_USER_AGENT = "myCodingAgent/1.0 (+https://github.com/yhdxx/myAgent)"


class SearchRuntimeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "search_error",
        retryable: bool = False,
        suggested_action: str = "",
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable
        self.suggested_action = suggested_action

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error_code": self.error_code,
            "message": str(self),
            "retryable": self.retryable,
        }
        if self.suggested_action:
            payload["suggested_action"] = self.suggested_action
        return payload


@dataclass(frozen=True)
class SearchRuntimeAvailability:
    enabled: bool
    reason: str = ""


class SearchRuntime:
    def __init__(
        self,
        config: SearchConfig | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        network_access: NetworkAccessRuntime | None = None,
        proxy_url: str = "",
    ) -> None:
        self.config = config or CONFIG.search
        self.network_access = network_access or NetworkAccessRuntime()
        self.proxy_url = proxy_url.strip()
        self._client = http_client
        self._owns_client = http_client is None
        self._direct_client: httpx.AsyncClient | None = None
        self._proxy_client: httpx.AsyncClient | None = None
        self._service_error = ""
        self._endpoint_route: Literal["public", "managed_local"] = "public"

    def set_service_error(self, reason: str) -> None:
        self._service_error = reason.strip()

    def set_endpoint(
        self,
        endpoint: str,
        *,
        route: Literal["public", "managed_local"] = "public",
    ) -> None:
        self._endpoint = endpoint.strip()
        self._endpoint_route = route

    def availability(self) -> SearchRuntimeAvailability:
        if not self.config.enabled:
            return SearchRuntimeAvailability(False, "search.enabled=false")
        if not self.endpoint:
            return SearchRuntimeAvailability(False, "search.endpoint 为空")
        if not self.network_access.enabled:
            return SearchRuntimeAvailability(False, "智能搜索已关闭")
        if self._service_error:
            return SearchRuntimeAvailability(False, f"本地 SearXNG 自动恢复失败：{self._service_error}")
        return SearchRuntimeAvailability(True)

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
        if self._owns_client and self._direct_client is not None:
            await self._direct_client.aclose()
        if self._owns_client and self._proxy_client is not None:
            await self._proxy_client.aclose()
        self._client = None
        self._direct_client = None
        self._proxy_client = None

    async def search(
        self,
        query: str,
        *,
        categories: list[str] | None = None,
        language: str = "",
        time_range: str = "",
        max_results: int | None = None,
    ) -> dict[str, Any]:
        query = " ".join(query.split())
        if not query:
            raise SearchRuntimeError("搜索 query 不能为空", error_code="invalid_query")
        if len(query) > self.config.max_query_chars:
            raise SearchRuntimeError(
                f"搜索 query 不能超过 {self.config.max_query_chars} 个字符",
                error_code="invalid_query",
            )
        available = self.availability()
        if not available.enabled:
            raise SearchRuntimeError(available.reason, error_code="search_unavailable")
        limit = max(1, min(max_results or self.config.max_results, self.config.max_results))
        params = {
            "q": query,
            "format": "json",
            "language": language.strip() or self.config.language,
            "safesearch": str(self.config.safesearch),
        }
        if categories:
            params["categories"] = ",".join(sorted({item.strip() for item in categories if item.strip()}))
        if time_range.strip():
            params["time_range"] = time_range.strip()
        payload = await self._request_json("GET", self.endpoint, params=params)
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise SearchRuntimeError("SearXNG 响应缺少 results 数组", error_code="invalid_search_response")
        unresponsive = payload.get("unresponsive_engines")
        if not raw_results and isinstance(unresponsive, list) and unresponsive:
            details = ", ".join(
                ": ".join(str(part) for part in item[:2])
                for item in unresponsive[:8]
                if isinstance(item, list) and item
            )
            raise SearchRuntimeError(
                f"SearXNG 上游搜索引擎不可用：{details or 'unknown error'}",
                error_code="search_engines_unavailable",
                retryable=True,
                suggested_action="稍后重试一次；仍失败时向用户说明搜索引擎上游不可用。",
            )
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in raw_results:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            if not url or url in seen or urlsplit(url).scheme not in {"http", "https"}:
                continue
            seen.add(url)
            engines = raw.get("engines")
            results.append(
                {
                    "title": _compact(str(raw.get("title") or ""), 500),
                    "url": url,
                    "snippet": _compact(str(raw.get("content") or raw.get("snippet") or ""), 1200),
                    "engines": [str(item) for item in engines] if isinstance(engines, list) else [],
                    "score": raw.get("score"),
                }
            )
            if len(results) >= limit:
                break
        payload = {
            "provider": "searxng",
            "query": query,
            "results": results,
            "result_count": len(results),
        }
        if isinstance(unresponsive, list) and unresponsive:
            payload["unresponsive_engines"] = unresponsive
        return payload

    async def fetch_url(self, url: str, *, max_chars: int | None = None) -> dict[str, Any]:
        value = url.strip()
        if not value:
            raise SearchRuntimeError("URL 不能为空", error_code="invalid_url")
        limit = max(1, min(max_chars or self.config.fetch_max_chars, self.config.fetch_max_chars))
        current = value
        for _ in range(self.config.max_redirects + 1):
            await self._validate_fetch_url(current)
            status_code, headers, data = await self._stream_response(current)
            if status_code in {301, 302, 303, 307, 308}:
                location = headers.get("location", "").strip()
                if not location:
                    raise SearchRuntimeError("网页重定向缺少 Location", error_code="invalid_redirect")
                current = urljoin(current, location)
                continue
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            text, title = _extract_text(bytes(data), content_type)
            return {
                "url": current,
                "content_type": content_type,
                "title": title,
                "text": _compact(text, limit),
                "truncated": len(text) > limit,
            }
        raise SearchRuntimeError(
            f"网页重定向次数超过 {self.config.max_redirects} 次",
            error_code="too_many_redirects",
        )

    async def _validate_fetch_url(self, url: str) -> None:
        if is_local_http_url(url):
            return
        if not self.network_access.enabled:
            raise SearchRuntimeError(
                "智能搜索已关闭；仅允许访问 localhost:port",
                error_code="network_disabled",
            )
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise SearchRuntimeError("URL 必须是完整的 http/https 地址", error_code="invalid_url")
        if parsed.username is not None or parsed.password is not None:
            raise SearchRuntimeError("URL 不允许包含用户名或密码", error_code="invalid_url")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            return
        if not address.is_global:
            raise SearchRuntimeError(
                "URL 不允许访问本机、私网、链路本地、保留或元数据地址",
                error_code="private_target_denied",
            )

    async def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._request(
            method,
            url,
            use_proxy=self._endpoint_route == "public" and not is_local_http_url(url),
            **kwargs,
        )
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise SearchRuntimeError("SearXNG 返回了无效 JSON", error_code="invalid_search_response") from exc
        if not isinstance(payload, dict):
            raise SearchRuntimeError("SearXNG 响应必须是 JSON 对象", error_code="invalid_search_response")
        return payload

    async def _request(self, method: str, url: str, *, use_proxy: bool, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(CONFIG.client.api_max_retries + 1):
            try:
                response = await self._http_client(use_proxy=use_proxy).request(
                    method,
                    url,
                    timeout=self.config.timeout,
                    **kwargs,
                )
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if not _http_error_retryable(exc) or attempt >= CONFIG.client.api_max_retries:
                    break
                await asyncio.sleep(CONFIG.client.api_retry_base_delay * (2**attempt))
            except httpx.TransportError as exc:
                last_error = exc
                if not _retryable_transport_error(exc) or attempt >= CONFIG.client.api_max_retries:
                    break
                await asyncio.sleep(CONFIG.client.api_retry_base_delay * (2**attempt))
        raise _request_failure("搜索请求失败", last_error)

    async def _stream_response(self, url: str) -> tuple[int, httpx.Headers, bytes]:
        last_error: Exception | None = None
        for attempt in range(CONFIG.client.api_max_retries + 1):
            try:
                async with self._http_client(use_proxy=True).stream(
                    "GET",
                    url,
                    timeout=self.config.timeout,
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        return response.status_code, response.headers, b""
                    if response.is_error:
                        await response.aread()
                    response.raise_for_status()
                    content_length = response.headers.get("content-length", "")
                    if content_length.isdigit() and int(content_length) > self.config.fetch_max_bytes:
                        raise SearchRuntimeError("网页响应超过大小限制", error_code="response_too_large")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > self.config.fetch_max_bytes:
                            raise SearchRuntimeError("网页响应超过大小限制", error_code="response_too_large")
                    return response.status_code, response.headers, bytes(data)
            except SearchRuntimeError:
                raise
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if not _http_error_retryable(exc) or attempt >= CONFIG.client.api_max_retries:
                    break
                await asyncio.sleep(CONFIG.client.api_retry_base_delay * (2**attempt))
            except httpx.TransportError as exc:
                last_error = exc
                if not _retryable_transport_error(exc) or attempt >= CONFIG.client.api_max_retries:
                    break
                await asyncio.sleep(CONFIG.client.api_retry_base_delay * (2**attempt))
        raise _request_failure("网页读取失败", last_error)

    def _http_client(self, *, use_proxy: bool = False) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        attribute = "_proxy_client" if use_proxy else "_direct_client"
        client = getattr(self, attribute)
        if client is None:
            client = httpx.AsyncClient(
                trust_env=False,
                proxy=self.proxy_url if use_proxy and self.proxy_url else None,
                headers={"User-Agent": SEARCH_USER_AGENT},
            )
            setattr(self, attribute, client)
        return client

    @property
    def endpoint(self) -> str:
        return getattr(self, "_endpoint", "") or self.config.endpoint.strip()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in {"script", "style", "noscript", "template"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        target = self.title_parts if self._in_title else self.text_parts
        target.append(data)


def _extract_text(data: bytes, content_type: str) -> tuple[str, str]:
    if "json" in content_type:
        try:
            return json.dumps(json.loads(data), ensure_ascii=False, indent=2), ""
        except (ValueError, json.JSONDecodeError):
            pass
    decoded = data.decode("utf-8", errors="replace")
    if "html" in content_type or "xhtml" in content_type or "<html" in decoded[:1000].lower():
        parser = _TextExtractor()
        parser.feed(decoded)
        title = _compact(" ".join(parser.title_parts), 500)
        return _compact(" ".join(parser.text_parts), 10_000_000), title
    return decoded, ""


def _compact(value: str, limit: int) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else text[:limit]


def _retryable_status(status_code: int) -> bool:
    return status_code in {408, 429} or status_code >= 500


def _retryable_transport_error(exc: httpx.TransportError) -> bool:
    text = str(exc).lower()
    if isinstance(exc, httpx.ProxyError) and any(code in text for code in ("400", "401", "403", "407")):
        return False
    return True


def _http_error_retryable(exc: httpx.HTTPStatusError) -> bool:
    try:
        payload = exc.response.json()
    except (ValueError, httpx.ResponseNotRead):
        payload = {}
    value = payload.get("retryable") if isinstance(payload, dict) else None
    return value if isinstance(value, bool) else _retryable_status(exc.response.status_code)


def _request_failure(prefix: str, error: Exception | None) -> SearchRuntimeError:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        try:
            detail = error.response.text.strip()
        except httpx.ResponseNotRead:
            detail = ""
        try:
            payload = error.response.json()
        except (ValueError, httpx.ResponseNotRead):
            payload = {}
        error_code = str(payload.get("error_code") or f"http_{status}")
        message = str(payload.get("message") or detail or f"HTTP {status}")
        retryable_value = payload.get("retryable") if isinstance(payload, dict) else None
        retryable = retryable_value if isinstance(retryable_value, bool) else _retryable_status(status)
        return SearchRuntimeError(
            f"{prefix}：{message}",
            error_code=error_code,
            retryable=retryable,
            suggested_action=(
                "稍后重试一次。" if retryable else "不要用其他网络工具重复请求同一目标。"
            ),
        )
    retryable = isinstance(error, httpx.TransportError) and _retryable_transport_error(error)
    return SearchRuntimeError(
        f"{prefix}：{error or 'unknown error'}",
        error_code="network_transport_error",
        retryable=retryable,
        suggested_action=(
            "稍后重试一次。" if retryable else "不要用其他网络工具重复请求同一目标。"
        ),
    )
