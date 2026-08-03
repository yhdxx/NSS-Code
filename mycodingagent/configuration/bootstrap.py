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

    _sync_readme(docs_path=docs_path, readme_path=readme_path, result=result)
    _ensure_config_file(template_path=template_path, config_path=config_path, result=result)
    return result


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


def _backup_path(config_path: Path) -> Path:
    timestamp = time.strftime("%Y%m%d%H%M%S")
    candidate = config_path.with_name(f"{config_path.name}.broken.{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = config_path.with_name(f"{config_path.name}.broken.{timestamp}.{counter}")
        counter += 1
    return candidate
