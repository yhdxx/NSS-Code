from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from mycodingagent.configuration.bootstrap import bootstrap_user_config


ROOT = Path(__file__).resolve().parents[1]


def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".mycodingagent").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / ".mycodingagent" / "config.example.json").write_text(
        json.dumps({"api": {"deepseek_api_key": "", "model": "demo-model"}}),
        encoding="utf-8",
    )
    (repo / "docs" / "configuration.md").write_text("# 配置教程\n", encoding="utf-8")
    return repo


def test_bootstrap_creates_user_config_and_readme(tmp_path):
    home = tmp_path / "home"
    repo = _fake_repo(tmp_path)

    result = bootstrap_user_config(home=home, repo_root=repo)

    config_path = home / ".mycodingagent" / "config.json"
    readme_path = home / ".mycodingagent" / "README.md"
    assert result.created_config is True
    assert result.synced_readme is True
    assert json.loads(config_path.read_text(encoding="utf-8"))["api"]["model"] == "demo-model"
    assert readme_path.read_text(encoding="utf-8") == "# 配置教程\n"


def test_bootstrap_preserves_existing_valid_config(tmp_path):
    home = tmp_path / "home"
    repo = _fake_repo(tmp_path)
    config_path = home / ".mycodingagent" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps({"api": {"deepseek_api_key": "keep"}}), encoding="utf-8")

    result = bootstrap_user_config(home=home, repo_root=repo)

    assert result.created_config is False
    assert result.recreated_invalid_config is False
    assert json.loads(config_path.read_text(encoding="utf-8"))["api"]["deepseek_api_key"] == "keep"


def test_bootstrap_backs_up_and_recreates_invalid_config(tmp_path):
    home = tmp_path / "home"
    repo = _fake_repo(tmp_path)
    config_path = home / ".mycodingagent" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{", encoding="utf-8")

    result = bootstrap_user_config(home=home, repo_root=repo)

    assert result.recreated_invalid_config is True
    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert result.backup_path.read_text(encoding="utf-8") == "{"
    assert json.loads(config_path.read_text(encoding="utf-8"))["api"]["model"] == "demo-model"


def test_bootstrap_backs_up_and_recreates_non_object_config(tmp_path):
    home = tmp_path / "home"
    repo = _fake_repo(tmp_path)
    config_path = home / ".mycodingagent" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[]", encoding="utf-8")

    result = bootstrap_user_config(home=home, repo_root=repo)

    assert result.recreated_invalid_config is True
    assert result.backup_path is not None
    assert json.loads(config_path.read_text(encoding="utf-8"))["api"]["model"] == "demo-model"


def test_repository_config_template_exposes_external_configuration_fields():
    template = json.loads((ROOT / ".mycodingagent" / "config.example.json").read_text(encoding="utf-8"))
    required_paths = [
        ("api", "deepseek_api_key"),
        ("api", "model"),
        ("long_term_memory", "storage_model"),
        ("long_term_memory", "query_model"),
        ("embedding", "provider"),
        ("embedding", "model"),
        ("embedding", "endpoint"),
        ("embedding", "api_key"),
        ("milvus", "host"),
        ("milvus", "port"),
        ("milvus", "collection"),
        ("mcp", "enabled"),
        ("mcp", "project_config_path"),
        ("mcp", "user_config_path"),
    ]
    for section, key in required_paths:
        assert key in template[section], f"missing {section}.{key}"


def test_main_bootstrap_creates_config_before_runtime_config_import(tmp_path):
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PYTHONPATH": str(ROOT),
    }
    env.pop("DEEPSEEK_API_KEY", None)

    result = subprocess.run(
        [sys.executable, str(ROOT / "__main__.py")],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=True,
    )

    assert (tmp_path / "home" / ".mycodingagent" / "config.json").exists()
    assert (tmp_path / "home" / ".mycodingagent" / "README.md").exists()
    assert "已创建配置文件" in result.stdout
    assert "未检测到基础配置：api.deepseek_api_key" in result.stdout
