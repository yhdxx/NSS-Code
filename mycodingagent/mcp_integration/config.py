from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MCPPermissionConfig:
    read_tools: tuple[str, ...] = ()
    write_tools: tuple[str, ...] = ()
    dangerous_tools: tuple[str, ...] = ()
    readonly_by_default: bool = False


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    startup_timeout: float = 20.0
    call_timeout: float = 60.0
    sandbox: bool = False
    image: str = ""
    workspace_access: str = "none"
    network: bool = False
    description: str = ""
    tags: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    abbreviations: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    permissions: MCPPermissionConfig = field(default_factory=MCPPermissionConfig)
    disabled: bool = False

    @property
    def searchable_terms(self) -> tuple[str, ...]:
        terms = (
            self.name,
            self.description,
            *self.tags,
            *self.aliases,
            *self.abbreviations,
            *self.synonyms,
            *self.keywords,
        )
        return tuple(term for term in terms if term)


class MCPConfigLoader:
    """Load project, user, and explicit MCP server configuration files."""

    def __init__(
        self,
        *,
        project_path: Path | None = None,
        user_path: Path | None = None,
        env_path_var: str = "MYCODINGAGENT_MCP_CONFIG",
    ) -> None:
        self.project_path = project_path or Path.cwd() / ".mycodingagent" / "mcp.json"
        self.user_path = user_path or Path.home() / ".mycodingagent" / "mcp.json"
        self.env_path_var = env_path_var

    def load(self) -> dict[str, MCPServerConfig]:
        merged: dict[str, MCPServerConfig] = {}
        for path in self.config_paths():
            loaded = self._load_path(path)
            merged.update(loaded)
        return {name: config for name, config in merged.items() if not config.disabled}

    def config_paths(self) -> list[Path]:
        paths = [self.user_path, self.project_path]
        explicit = os.getenv(self.env_path_var)
        if explicit:
            paths.append(Path(explicit).expanduser())
        return paths

    def _load_path(self, path: Path) -> dict[str, MCPServerConfig]:
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"MCP 配置无效 {path}：{exc}") from exc
        servers = raw.get("servers", raw)
        if not isinstance(servers, dict):
            raise ValueError(f"MCP 配置无效 {path}：'servers' 必须是对象")
        result: dict[str, MCPServerConfig] = {}
        for name, item in servers.items():
            if not isinstance(item, dict):
                continue
            config = _server_config_from_dict(str(name), item)
            if config is not None:
                result[config.name] = config
        return result


def _server_config_from_dict(name: str, data: dict[str, Any]) -> MCPServerConfig | None:
    command = str(data.get("command", "")).strip()
    transport = str(data.get("transport", "stdio") or "stdio").strip().lower()
    url = str(data.get("url", "") or "").strip()
    disabled = bool(data.get("disabled", False))
    if transport not in {"stdio", "streamable_http"}:
        raise ValueError(f"MCP Server {name!r} 使用了不支持的传输方式：{transport}")
    if transport == "stdio" and not command and not disabled:
        raise ValueError(f"MCP Server {name!r} 缺少必填字段：command")
    if transport == "streamable_http" and not url and not disabled:
        raise ValueError(f"MCP Server {name!r} 缺少必填字段：url")
    workspace_access = str(data.get("workspace_access", "none") or "none").strip().lower()
    if workspace_access not in {"none", "read", "write"}:
        raise ValueError(f"MCP Server {name!r} 的 workspace_access 无效：{workspace_access}")
    return MCPServerConfig(
        name=name,
        command=command,
        args=_string_tuple(data.get("args", ())),
        env={str(key): str(value) for key, value in dict(data.get("env", {})).items()},
        transport=transport,
        url=url,
        headers={str(key): str(value) for key, value in dict(data.get("headers", {})).items()},
        startup_timeout=max(0.1, float(data.get("startup_timeout", 20.0))),
        call_timeout=max(0.1, float(data.get("call_timeout", 60.0))),
        sandbox=bool(data.get("sandbox", False)),
        image=str(data.get("image", "") or ""),
        workspace_access=workspace_access,
        network=bool(data.get("network", False)),
        description=str(data.get("description", "") or ""),
        tags=_string_tuple(data.get("tags", ())),
        aliases=_string_tuple(data.get("aliases", ())),
        abbreviations=_string_tuple(data.get("abbreviations", ())),
        synonyms=_string_tuple(data.get("synonyms", ())),
        keywords=_string_tuple(data.get("keywords", ())),
        permissions=_permission_config(data.get("permissions", {})),
        disabled=disabled,
    )


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _permission_config(value: Any) -> MCPPermissionConfig:
    if not isinstance(value, dict):
        return MCPPermissionConfig()
    return MCPPermissionConfig(
        read_tools=_string_tuple(value.get("read_tools", ())),
        write_tools=_string_tuple(value.get("write_tools", ())),
        dangerous_tools=_string_tuple(value.get("dangerous_tools", ())),
        readonly_by_default=bool(value.get("readonly_by_default", False)),
    )
