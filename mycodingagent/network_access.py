from __future__ import annotations

import ipaddress
import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit


@dataclass
class NetworkAccessRuntime:
    """Own the process-level permission for external search and network MCP access."""

    enabled: bool = True
    _change_hook: Callable[[bool], Awaitable[None] | None] | None = None

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def bind_change_hook(self, hook: Callable[[bool], Awaitable[None] | None] | None) -> None:
        self._change_hook = hook

    async def set_enabled_async(self, enabled: bool) -> None:
        self.set_enabled(enabled)
        if self._change_hook is None:
            return
        result = self._change_hook(self.enabled)
        if inspect.isawaitable(result):
            await result

    def allows_url(self, url: str) -> bool:
        return self.enabled or is_local_http_url(url)

    def allows_mcp(self, config: Any) -> bool:
        if self.enabled:
            return True
        if str(getattr(config, "name", "")).strip().lower() == "playwright":
            return True
        if _is_github_server(config):
            return False
        if str(getattr(config, "transport", "stdio")) == "streamable_http":
            return is_local_http_url(str(getattr(config, "url", "")))
        return not bool(getattr(config, "network", False))

    def runtime_payload(self) -> dict[str, Any]:
        return {
            "smart_search": "enabled" if self.enabled else "disabled",
            "external_network": "allowed" if self.enabled else "denied",
            "localhost": "allowed",
        }


def is_local_http_url(url: str) -> bool:
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_github_server(config: Any) -> bool:
    values = {
        str(getattr(config, "name", "")),
        *[str(item) for item in getattr(config, "tags", ())],
        *[str(item) for item in getattr(config, "aliases", ())],
    }
    return any(value.strip().lower() in {"github", "gh"} for value in values)
