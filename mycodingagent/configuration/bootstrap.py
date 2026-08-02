from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path


USER_CONFIG_DIR = Path.home() / ".mycodingagent"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.json"
USER_CONFIG_README_PATH = USER_CONFIG_DIR / "README.md"


@dataclass
class ConfigBootstrapResult:
    config_path: Path
    readme_path: Path
    created_config: bool = False
    recreated_invalid_config: bool = False
    backup_path: Path | None = None
    synced_readme: bool = False
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
    template_path = repo_root / ".mycodingagent" / "config.example.json"
    docs_path = repo_root / "docs" / "configuration.md"
    result = ConfigBootstrapResult(config_path=config_path, readme_path=readme_path)

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.fatal_error = f"无法创建配置目录 {config_dir}: {exc}"
        return result

    _migrate_legacy_resources(home=home, config_dir=config_dir, result=result)
    _sync_readme(docs_path=docs_path, readme_path=readme_path, result=result)
    _ensure_config_file(template_path=template_path, config_path=config_path, result=result)
    return result


def _migrate_legacy_resources(*, home: Path, config_dir: Path, result: ConfigBootstrapResult) -> None:
    _migrate_legacy_state_dir(
        legacy_state_dir=home / ".local" / "state" / "myCodingAgent",
        state_dir=config_dir / "state",
        result=result,
    )
    _move_legacy_file(
        source=home / ".config" / "myCodingAgent" / "mcp.json",
        destination=config_dir / "mcp.json",
        label="用户级 MCP 配置",
        result=result,
    )


def _migrate_legacy_state_dir(
    *,
    legacy_state_dir: Path,
    state_dir: Path,
    result: ConfigBootstrapResult,
) -> None:
    if not legacy_state_dir.exists():
        return
    if not legacy_state_dir.is_dir():
        result.warnings.append(f"旧 state 路径不是目录，已跳过：{legacy_state_dir}")
        return
    try:
        entries = list(legacy_state_dir.iterdir())
    except OSError as exc:
        result.warnings.append(f"无法读取旧 state 目录 {legacy_state_dir}: {exc}")
        return
    if not entries:
        return
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.warnings.append(f"无法创建新 state 目录 {state_dir}: {exc}")
        return

    moved = 0
    for entry in entries:
        destination = state_dir / entry.name
        if destination.exists():
            result.warnings.append(f"新 state 已存在同名资源，保留旧文件未迁移：{entry}")
            continue
        try:
            shutil.move(str(entry), str(destination))
        except OSError as exc:
            result.warnings.append(f"无法迁移旧 state 资源 {entry} -> {destination}: {exc}")
            continue
        moved += 1

    if moved:
        result.messages.append(f"已迁移旧 state 资源：{legacy_state_dir} -> {state_dir}")
    _remove_empty_dir(legacy_state_dir)


def _move_legacy_file(
    *,
    source: Path,
    destination: Path,
    label: str,
    result: ConfigBootstrapResult,
) -> None:
    if not source.exists():
        return
    if destination.exists():
        result.warnings.append(f"新{label}已存在，保留旧文件未迁移：{source}")
        return
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    except OSError as exc:
        result.warnings.append(f"无法迁移旧{label} {source} -> {destination}: {exc}")
        return
    result.messages.append(f"已迁移旧{label}：{source} -> {destination}")
    _remove_empty_dir(source.parent)


def _remove_empty_dir(path: Path) -> None:
    try:
        path.rmdir()
    except FileNotFoundError:
        return
    except OSError:
        return


def _sync_readme(*, docs_path: Path, readme_path: Path, result: ConfigBootstrapResult) -> None:
    if not docs_path.exists():
        result.warnings.append(f"未找到配置教程源文件：{docs_path}")
        return
    try:
        shutil.copy2(docs_path, readme_path)
    except OSError as exc:
        result.warnings.append(f"无法同步配置教程到 {readme_path}: {exc}")
        return
    result.synced_readme = True


def _ensure_config_file(*, template_path: Path, config_path: Path, result: ConfigBootstrapResult) -> None:
    if not template_path.exists():
        result.fatal_error = f"未找到配置模板：{template_path}"
        return

    if not config_path.exists():
        if _copy_template(template_path=template_path, config_path=config_path, result=result):
            result.created_config = True
            result.messages.append(f"已创建配置文件：{config_path}")
        return

    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        result.fatal_error = f"无法读取配置文件 {config_path}: {exc}"
        return

    parsed = _parse_config_json(raw)
    if parsed is not None:
        _merge_template_defaults(template_path=template_path, config_path=config_path, config=parsed, result=result)
        return

    backup_path = _backup_path(config_path)
    try:
        config_path.replace(backup_path)
    except OSError as exc:
        result.fatal_error = f"配置文件无效且备份失败 {config_path}: {exc}"
        return

    result.backup_path = backup_path
    if _copy_template(template_path=template_path, config_path=config_path, result=result):
        result.recreated_invalid_config = True
        result.messages.append(f"配置文件无效，已备份到：{backup_path}")
        result.messages.append(f"已重建配置模板：{config_path}")


def _copy_template(*, template_path: Path, config_path: Path, result: ConfigBootstrapResult) -> bool:
    try:
        shutil.copy2(template_path, config_path)
    except OSError as exc:
        result.fatal_error = f"无法创建配置文件 {config_path}: {exc}"
        return False
    return True


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


def _merge_template_defaults(
    *,
    template_path: Path,
    config_path: Path,
    config: dict,
    result: ConfigBootstrapResult,
) -> None:
    try:
        template = json.loads(template_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.warnings.append(f"无法读取配置模板默认值：{exc}")
        return
    if not isinstance(template, dict):
        result.warnings.append(f"配置模板必须是 JSON 对象：{template_path}")
        return
    merged = _recursive_fill_missing(config, template)
    if not merged:
        return
    try:
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        result.warnings.append(f"无法补齐配置默认字段 {config_path}: {exc}")
        return
    result.messages.append(f"已补齐配置默认字段：{config_path}")


def _recursive_fill_missing(target: dict, defaults: dict) -> bool:
    changed = False
    for key, default_value in defaults.items():
        if key not in target:
            target[key] = default_value
            changed = True
            continue
        if isinstance(target[key], dict) and isinstance(default_value, dict):
            changed = _recursive_fill_missing(target[key], default_value) or changed
    return changed


def _backup_path(config_path: Path) -> Path:
    timestamp = time.strftime("%Y%m%d%H%M%S")
    candidate = config_path.with_name(f"{config_path.name}.broken.{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = config_path.with_name(f"{config_path.name}.broken.{timestamp}.{counter}")
        counter += 1
    return candidate
