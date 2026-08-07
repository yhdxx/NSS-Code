from __future__ import annotations

import asyncio
import ipaddress
import json
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from mycodingagent.configuration.settings import CONFIG, WebFetchConfig
from mycodingagent.network_access import NetworkAccessRuntime, is_local_http_url

WEB_FETCH_USER_AGENT = "myCodingAgent/1.0 (+https://github.com/yhdxx/myAgent)"


class WebFetchRuntimeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "web_fetch_error",
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


class WebFetchRuntime:
    def __init__(
        self,
        config: WebFetchConfig | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        network_access: NetworkAccessRuntime | None = None,
        proxy_url: str = "",
    ) -> None:
        self.config = config or CONFIG.web_fetch
        self.network_access = network_access or NetworkAccessRuntime()
        self.proxy_url = proxy_url.strip()
        self._client = http_client
        self._owns_client = http_client is None
        self._proxy_client: httpx.AsyncClient | None = None

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
        if self._owns_client and self._proxy_client is not None:
            await self._proxy_client.aclose()
        self._client = None
        self._proxy_client = None

    async def fetch_url(self, url: str, *, max_chars: int | None = None) -> dict[str, Any]:
        value = url.strip()
        if not value:
            raise WebFetchRuntimeError("URL 不能为空", error_code="invalid_url")
        if not self.config.enabled:
            raise WebFetchRuntimeError("web_fetch.enabled=false", error_code="web_fetch_disabled")
        limit = max(1, min(max_chars or self.config.max_chars, self.config.max_chars))
        current = value
        for _ in range(self.config.max_redirects + 1):
            self._validate_fetch_url(current)
            status_code, headers, data = await self._stream_response(current)
            if status_code in {301, 302, 303, 307, 308}:
                location = headers.get("location", "").strip()
                if not location:
                    raise WebFetchRuntimeError(
                        "网页重定向缺少 Location", error_code="invalid_redirect"
                    )
                current = urljoin(current, location)
                continue
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            text, title = _extract_text(data, content_type)
            return {
                "url": current,
                "content_type": content_type,
                "title": title,
                "text": _compact(text, limit),
                "truncated": len(text) > limit,
            }
        raise WebFetchRuntimeError(
            f"网页重定向次数超过 {self.config.max_redirects} 次",
            error_code="too_many_redirects",
        )

    def _validate_fetch_url(self, url: str) -> None:
        if is_local_http_url(url):
            return
        if not self.network_access.enabled:
            raise WebFetchRuntimeError(
                "网络访问已关闭；仅允许访问 localhost:port",
                error_code="network_disabled",
            )
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise WebFetchRuntimeError(
                "URL 必须是完整的 http/https 地址", error_code="invalid_url"
            )
        if parsed.username is not None or parsed.password is not None:
            raise WebFetchRuntimeError("URL 不允许包含用户名或密码", error_code="invalid_url")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            return
        if not address.is_global:
            raise WebFetchRuntimeError(
                "URL 不允许访问本机、私网、链路本地、保留或元数据地址",
                error_code="private_target_denied",
            )

    async def _stream_response(self, url: str) -> tuple[int, httpx.Headers, bytes]:
        last_error: Exception | None = None
        for attempt in range(CONFIG.client.api_max_retries + 1):
            try:
                async with self._http_client().stream(
                    "GET",
                    url,
                    headers={"User-Agent": WEB_FETCH_USER_AGENT},
                    timeout=self.config.timeout,
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        return response.status_code, response.headers, b""
                    if response.is_error:
                        await response.aread()
                    response.raise_for_status()
                    content_length = response.headers.get("content-length", "")
                    if content_length.isdigit() and int(content_length) > self.config.max_bytes:
                        raise WebFetchRuntimeError(
                            "网页响应超过大小限制", error_code="response_too_large"
                        )
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > self.config.max_bytes:
                            raise WebFetchRuntimeError(
                                "网页响应超过大小限制", error_code="response_too_large"
                            )
                    return response.status_code, response.headers, bytes(data)
            except WebFetchRuntimeError:
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

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        if self._proxy_client is None:
            self._proxy_client = httpx.AsyncClient(
                trust_env=False,
                proxy=self.proxy_url or None,
                headers={"User-Agent": WEB_FETCH_USER_AGENT},
            )
        return self._proxy_client


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
    if isinstance(exc, httpx.ProxyError) and any(
        code in text for code in ("400", "401", "403", "407")
    ):
        return False
    return True


def _http_error_retryable(exc: httpx.HTTPStatusError) -> bool:
    try:
        payload = exc.response.json()
    except (ValueError, httpx.ResponseNotRead):
        payload = {}
    value = payload.get("retryable") if isinstance(payload, dict) else None
    return value if isinstance(value, bool) else _retryable_status(exc.response.status_code)


def _request_failure(prefix: str, error: Exception | None) -> WebFetchRuntimeError:
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
        return WebFetchRuntimeError(
            f"{prefix}：{message}",
            error_code=error_code,
            retryable=retryable,
            suggested_action="稍后重试一次。" if retryable else "不要重复请求同一目标。",
        )
    retryable = isinstance(error, httpx.TransportError) and _retryable_transport_error(error)
    return WebFetchRuntimeError(
        f"{prefix}：{error or 'unknown error'}",
        error_code="network_transport_error",
        retryable=retryable,
        suggested_action="稍后重试一次。" if retryable else "不要重复请求同一目标。",
    )
