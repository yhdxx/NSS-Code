from __future__ import annotations

import json
import shutil
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path


USER_CONFIG_DIR = Path.home() / ".mycodingagent"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.json"
USER_CONFIG_README_PATH = USER_CONFIG_DIR / "README.md"
USER_MCP_CONFIG_PATH = USER_CONFIG_DIR / "mcp.json"
USER_MCP_README_PATH = USER_CONFIG_DIR / "MCP.md"


@dataclass
class ConfigBootstrapResult:
    config_path: Path
    readme_path: Path
    mcp_config_path: Path
    mcp_readme_path: Path
    created_config: bool = False
    recreated_invalid_config: bool = False
    backup_path: Path | None = None
    synced_readme: bool = False
    created_mcp_config: bool = False
    recreated_invalid_mcp_config: bool = False
    mcp_backup_path: Path | None = None
    synced_mcp_readme: bool = False
    added_mcp_servers: list[str] = field(default_factory=list)
    added_config_fields: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fatal_error: str = ""


def bootstrap_user_config(*, home: Path | None = None, repo_root: Path | None = None) -> ConfigBootstrapResult:
    """Ensure the user config directory, config template, and local README exist.

    This module intentionally does not import settings.CONFIG; it runs before
    runtime configuration is loaded.
    """

    home = home.expanduser() if home is not None else Path.home()
    repo_root = repo_root or Path(__file__).resolve().parents[2]
    config_dir = home / ".mycodingagent"
    config_path = config_dir / "config.json"
    readme_path = config_dir / "README.md"
    mcp_config_path = config_dir / "mcp.json"
    mcp_readme_path = config_dir / "MCP.md"
    template_path = repo_root / ".mycodingagent" / "config.example.json"
    mcp_template_path = repo_root / ".mycodingagent" / "mcp.example.json"
    docs_path = repo_root / "docs" / "configuration.md"
    mcp_docs_path = repo_root / "docs" / "mcp.md"
    result = ConfigBootstrapResult(
        config_path=config_path,
        readme_path=readme_path,
        mcp_config_path=mcp_config_path,
        mcp_readme_path=mcp_readme_path,
    )

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.fatal_error = f"无法创建配置目录 {config_dir}: {exc}"
        return result

    result.synced_readme = _sync_document(
        source_path=docs_path,
        target_path=readme_path,
        label="配置教程",
        result=result,
    )
    result.synced_mcp_readme = _sync_document(
        source_path=mcp_docs_path,
        target_path=mcp_readme_path,
        label="MCP 配置说明",
        result=result,
    )
    (
        result.created_config,
        result.recreated_invalid_config,
        result.backup_path,
    ) = _ensure_json_file(
        template_path=template_path,
        target_path=config_path,
        label="配置文件",
        required=True,
        result=result,
    )
    if not result.fatal_error:
        result.added_config_fields = _merge_missing_config_fields(
            template_path=template_path,
            target_path=config_path,
            fields=(
                "client.max_tool_rounds",
                "network.enabled",
                "network.upstream_proxy",
                "network.allow_domains",
                "network.deny_domains",
                "network.connect_timeout",
                "network.idle_timeout",
                "network.ca_bundle",
                "search.image",
                "model.research",
                "research.enabled",
                "research.max_tool_rounds",
                "research.max_sources",
                "research.max_findings",
                "research.max_summary_chars",
                "research.fetch_max_chars_per_source",
            ),
            result=result,
        )
    if not result.fatal_error:
        (
            result.created_mcp_config,
            result.recreated_invalid_mcp_config,
            result.mcp_backup_path,
        ) = _ensure_json_file(
            template_path=mcp_template_path,
            target_path=mcp_config_path,
            label="MCP 配置文件",
            required=False,
            result=result,
        )
        if not result.fatal_error:
            result.added_mcp_servers = _merge_missing_mcp_servers(
                template_path=mcp_template_path,
                target_path=mcp_config_path,
                result=result,
            )
    return result


def _merge_missing_config_fields(
    *,
    template_path: Path,
    target_path: Path,
    fields: tuple[str, ...],
    result: ConfigBootstrapResult,
) -> list[str]:
    try:
        template = _parse_config_json(template_path.read_text(encoding="utf-8"))
        target = _parse_config_json(target_path.read_text(encoding="utf-8"))
    except OSError as exc:
        result.warnings.append(f"无法增量同步配置字段：{exc}")
        return []
    if template is None or target is None:
        return []
    added: list[str] = []
    for path in fields:
        parts = path.split(".")
        template_parent: object = template
        target_parent: object = target
        for part in parts[:-1]:
            if not isinstance(template_parent, dict) or part not in template_parent:
                template_parent = None
                break
            template_parent = template_parent[part]
            if isinstance(target_parent, dict):
                child = target_parent.get(part)
                if child is None:
                    child = {}
                    target_parent[part] = child
                target_parent = child
        leaf = parts[-1]
        if (
            not isinstance(template_parent, dict)
            or leaf not in template_parent
            or not isinstance(target_parent, dict)
            or leaf in target_parent
        ):
            continue
        value = deepcopy(template_parent[leaf])
        if path == "model.research":
            model = target.get("model")
            if isinstance(model, dict):
                value = str(model.get("active") or value)
        target_parent[leaf] = value
        added.append(path)
    if not added:
        return []
    temporary = target_path.with_suffix(target_path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(target, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target_path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        result.warnings.append(f"无法追加配置字段到 {target_path}: {exc}")
        return []
    result.messages.append(f"已追加配置字段：{', '.join(added)}")
    return added


def _merge_missing_mcp_servers(
    *,
    template_path: Path,
    target_path: Path,
    result: ConfigBootstrapResult,
) -> list[str]:
    try:
        template = _parse_config_json(template_path.read_text(encoding="utf-8"))
        target = _parse_config_json(target_path.read_text(encoding="utf-8"))
    except OSError as exc:
        result.warnings.append(f"无法增量同步 MCP Server 配置：{exc}")
        return []
    if template is None or target is None:
        return []
    template_servers = template.get("servers")
    target_servers = target.get("servers")
    if not isinstance(template_servers, dict):
        result.warnings.append(f"MCP 配置模板缺少 servers 对象：{template_path}")
        return []
    if not isinstance(target_servers, dict):
        result.warnings.append(
            f"现有 MCP 配置缺少 servers 对象，已保留原文件且未自动补全：{target_path}"
        )
        return []
    added: list[str] = []
    for name, server_config in template_servers.items():
        if name.startswith("_") or name in target_servers or not isinstance(server_config, dict):
            continue
        target_servers[name] = deepcopy(server_config)
        added.append(name)
    if not added:
        return []
    temporary = target_path.with_suffix(target_path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(target, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target_path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        result.warnings.append(f"无法追加内置 MCP Server 到 {target_path}: {exc}")
        return []
    result.messages.append(f"已追加内置 MCP Server：{', '.join(added)}")
    return added


def _sync_document(
    *,
    source_path: Path,
    target_path: Path,
    label: str,
    result: ConfigBootstrapResult,
) -> bool:
    if not source_path.exists():
        result.warnings.append(f"未找到{_after_chinese(label)}源文件：{source_path}")
        return False
    try:
        shutil.copy2(source_path, target_path)
    except OSError as exc:
        result.warnings.append(f"无法同步{_after_chinese(label)}到 {target_path}: {exc}")
        return False
    return True


def _ensure_json_file(
    *,
    template_path: Path,
    target_path: Path,
    label: str,
    required: bool,
    result: ConfigBootstrapResult,
) -> tuple[bool, bool, Path | None]:
    if not template_path.exists():
        _report_bootstrap_error(
            f"未找到{_after_chinese(label)}模板：{template_path}",
            required=required,
            result=result,
        )
        return False, False, None

    if not target_path.exists():
        if _copy_template(
            template_path=template_path,
            target_path=target_path,
            label=label,
            required=required,
            result=result,
        ):
            result.messages.append(f"已创建{_after_chinese(label)}：{target_path}")
            return True, False, None
        return False, False, None

    try:
        raw = target_path.read_text(encoding="utf-8")
    except OSError as exc:
        _report_bootstrap_error(
            f"无法读取{_after_chinese(label)} {target_path}: {exc}",
            required=required,
            result=result,
        )
        return False, False, None

    parsed = _parse_config_json(raw)
    if parsed is not None:
        return False, False, None

    backup_path = _backup_path(target_path)
    try:
        target_path.replace(backup_path)
    except OSError as exc:
        _report_bootstrap_error(
            f"{label}无效且备份失败 {target_path}: {exc}",
            required=required,
            result=result,
        )
        return False, False, None

    if _copy_template(
        template_path=template_path,
        target_path=target_path,
        label=label,
        required=required,
        result=result,
    ):
        result.messages.append(f"{label}无效，已备份到：{backup_path}")
        result.messages.append(f"已重建{_after_chinese(label)}模板：{target_path}")
        return False, True, backup_path
    return False, False, backup_path


def _copy_template(
    *,
    template_path: Path,
    target_path: Path,
    label: str,
    required: bool,
    result: ConfigBootstrapResult,
) -> bool:
    try:
        shutil.copy2(template_path, target_path)
    except OSError as exc:
        _report_bootstrap_error(
            f"无法创建{_after_chinese(label)} {target_path}: {exc}",
            required=required,
            result=result,
        )
        return False
    return True


def _report_bootstrap_error(
    message: str,
    *,
    required: bool,
    result: ConfigBootstrapResult,
) -> None:
    if required:
        result.fatal_error = message
    else:
        result.warnings.append(message)


def _after_chinese(label: str) -> str:
    return f" {label}" if label[:1].isascii() else label


def _is_valid_config_json(raw: str) -> bool:
    return _parse_config_json(raw) is not None


def _parse_config_json(raw: str) -> dict | None:
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _backup_path(config_path: Path) -> Path:
    timestamp = time.strftime("%Y%m%d%H%M%S")
    candidate = config_path.with_name(f"{config_path.name}.broken.{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = config_path.with_name(f"{config_path.name}.broken.{timestamp}.{counter}")
        counter += 1
    return candidate
