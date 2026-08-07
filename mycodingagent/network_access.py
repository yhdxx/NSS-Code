from __future__ import annotations

import ipaddress
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit


@dataclass
class NetworkAccessRuntime:
    """Own the process-level permission for external tool network access."""

    enabled: bool = True
    _change_hook: Callable[[bool], Awaitable[None] | None] | None = None
    _mcp_overrides: dict[str, bool] = field(default_factory=dict)

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
        if not requires_external_network(config):
            return True
        name = str(getattr(config, "name", "")).strip()
        if name in self._mcp_overrides:
            return self._mcp_overrides[name]
        return self.enabled

    def set_mcp_enabled(self, server: str, enabled: bool) -> None:
        name = server.strip()
        if name:
            self._mcp_overrides[name] = bool(enabled)

    def mcp_enabled(self, config: Any) -> bool:
        return self.allows_mcp(config)

    def allows_external_client(self, server: str = "") -> bool:
        name = server.strip()
        if name and name in self._mcp_overrides:
            return self._mcp_overrides[name]
        return self.enabled

    def runtime_payload(self) -> dict[str, Any]:
        return {
            "external_network": "allowed" if self.enabled else "denied",
            "localhost": "allowed",
            "mcp_overrides": dict(sorted(self._mcp_overrides.items())),
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


def requires_external_network(config: Any) -> bool:
    if str(getattr(config, "transport", "stdio")) == "streamable_http":
        return not is_local_http_url(str(getattr(config, "url", "")))
    return bool(getattr(config, "network", False))
