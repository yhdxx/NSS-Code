from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from mycodingagent.configuration.bootstrap import bootstrap_user_config


ROOT = Path(__file__).resolve().parents[1]


MODEL_API_ENV_NAMES = (
    "MYCODINGAGENT_MODEL_PROVIDER_DEEPSEEK_API",
    "MYCODINGAGENT_MODEL_PROVIDER_OPENAI_API",
    "MYCODINGAGENT_MODEL_PROVIDER_QWEN_API",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "QWEN_API_KEY",
    "DASHSCOPE_API_KEY",
)


def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".mycodingagent").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / ".mycodingagent" / "config.example.json").write_text(
        json.dumps(
            {
                "model": {
                    "active": "main",
                    "providers": {
                        "deepseek": {"api": ""},
                    },
                    "profiles": {
                        "main": {
                            "provider": "deepseek",
                            "model": "demo-model",
                        }
                    },
                    "long_term_memory": {"storage": "main", "search": "main"},
                },
                "client": {"max_tool_rounds": 100},
                "search": {"tavily_api_key": ""},
                "web_fetch": {
                    "enabled": True,
                    "timeout": 20,
                    "max_bytes": 2000000,
                    "max_chars": 50000,
                    "max_redirects": 5,
                },
            }
        ),
        encoding="utf-8",
    )
    (repo / ".mycodingagent" / "mcp.example.json").write_text(
        json.dumps(
            {
                "servers": {
                    "github": {"disabled": True},
                    "playwright": {"disabled": False, "image": "playwright-mcp"},
                    "tavily": {"disabled": False, "required_env": ["TAVILY_API_KEY"]},
                }
            }
        ),
        encoding="utf-8",
    )
    (repo / "docs" / "configuration.md").write_text("# 配置教程\n", encoding="utf-8")
    (repo / "docs" / "mcp.md").write_text("# MCP 配置说明\n", encoding="utf-8")
    return repo


def test_bootstrap_creates_user_config_and_readme(tmp_path):
    home = tmp_path / "home"
    repo = _fake_repo(tmp_path)

    result = bootstrap_user_config(home=home, repo_root=repo)

    config_path = home / ".mycodingagent" / "config.json"
    readme_path = home / ".mycodingagent" / "README.md"
    mcp_config_path = home / ".mycodingagent" / "mcp.json"
    mcp_readme_path = home / ".mycodingagent" / "MCP.md"
    assert result.created_config is True
    assert result.synced_readme is True
    assert result.created_mcp_config is True
    assert result.synced_mcp_readme is True
    assert json.loads(config_path.read_text(encoding="utf-8"))["model"]["profiles"]["main"]["model"] == "demo-model"
    assert readme_path.read_text(encoding="utf-8") == "# 配置教程\n"
    assert json.loads(mcp_config_path.read_text(encoding="utf-8"))["servers"]["github"]["disabled"] is True
    assert json.loads(mcp_config_path.read_text(encoding="utf-8"))["servers"]["playwright"]["disabled"] is False
    assert mcp_readme_path.read_text(encoding="utf-8") == "# MCP 配置说明\n"


def test_bootstrap_preserves_existing_valid_config(tmp_path):
    home = tmp_path / "home"
    repo = _fake_repo(tmp_path)
    config_path = home / ".mycodingagent" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "model": {
                    "active": "custom",
                    "providers": {
                        "qwen": {"api": "keep"}
                    },
                    "profiles": {
                        "custom": {"provider": "qwen", "model": "qwen-plus"}
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    result = bootstrap_user_config(home=home, repo_root=repo)

    assert result.created_config is False
    assert result.recreated_invalid_config is False
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["model"]["providers"]["qwen"]["api"] == "keep"
    assert config["client"]["max_tool_rounds"] == 100
    assert config["search"]["tavily_api_key"] == ""
    assert config["web_fetch"]["enabled"] is True
    assert result.added_config_fields == [
        "client.max_tool_rounds",
        "search.tavily_api_key",
        "web_fetch.enabled",
        "web_fetch.timeout",
        "web_fetch.max_bytes",
        "web_fetch.max_chars",
        "web_fetch.max_redirects",
    ]


def test_bootstrap_preserves_user_max_tool_rounds(tmp_path):
    home = tmp_path / "home"
    repo = _fake_repo(tmp_path)
    config_path = home / ".mycodingagent" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"client": {"max_tool_rounds": 240, "debug": True}}),
        encoding="utf-8",
    )

    result = bootstrap_user_config(home=home, repo_root=repo)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["client"] == {"max_tool_rounds": 240, "debug": True}
    assert config["search"]["tavily_api_key"] == ""
    assert result.added_config_fields == [
        "search.tavily_api_key",
        "web_fetch.enabled",
        "web_fetch.timeout",
        "web_fetch.max_bytes",
        "web_fetch.max_chars",
        "web_fetch.max_redirects",
    ]


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
    assert json.loads(config_path.read_text(encoding="utf-8"))["model"]["profiles"]["main"]["model"] == "demo-model"


def test_bootstrap_backs_up_and_recreates_non_object_config(tmp_path):
    home = tmp_path / "home"
    repo = _fake_repo(tmp_path)
    config_path = home / ".mycodingagent" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[]", encoding="utf-8")

    result = bootstrap_user_config(home=home, repo_root=repo)

    assert result.recreated_invalid_config is True
    assert result.backup_path is not None
    assert json.loads(config_path.read_text(encoding="utf-8"))["model"]["profiles"]["main"]["model"] == "demo-model"


def test_bootstrap_appends_missing_builtin_mcp_servers_and_preserves_user_servers(tmp_path):
    home = tmp_path / "home"
    repo = _fake_repo(tmp_path)
    mcp_path = home / ".mycodingagent" / "mcp.json"
    mcp_path.parent.mkdir(parents=True)
    mcp_path.write_text(
        json.dumps({"servers": {"custom": {"command": "custom-server"}}}),
        encoding="utf-8",
    )

    result = bootstrap_user_config(home=home, repo_root=repo)

    assert result.created_mcp_config is False
    assert result.recreated_invalid_mcp_config is False
    config = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert config["servers"]["custom"] == {"command": "custom-server"}
    assert config["servers"]["github"]["disabled"] is True
    assert config["servers"]["playwright"] == {
        "disabled": False,
        "image": "playwright-mcp",
    }
    assert config["servers"]["tavily"]["required_env"] == ["TAVILY_API_KEY"]
    assert result.added_mcp_servers == ["github", "playwright", "tavily"]


def test_bootstrap_never_overwrites_same_name_user_mcp_server(tmp_path):
    home = tmp_path / "home"
    repo = _fake_repo(tmp_path)
    mcp_path = home / ".mycodingagent" / "mcp.json"
    mcp_path.parent.mkdir(parents=True)
    mcp_path.write_text(
        json.dumps(
            {
                "servers": {
                    "github": {
                        "disabled": False,
                        "command": "user-github-server",
                        "env": {"CUSTOM": "keep"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = bootstrap_user_config(home=home, repo_root=repo)

    config = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert config["servers"]["github"] == {
        "disabled": False,
        "command": "user-github-server",
        "env": {"CUSTOM": "keep"},
    }
    assert result.added_mcp_servers == ["playwright", "tavily"]


def test_bootstrap_mcp_merge_is_idempotent(tmp_path):
    home = tmp_path / "home"
    repo = _fake_repo(tmp_path)

    first = bootstrap_user_config(home=home, repo_root=repo)
    mcp_path = home / ".mycodingagent" / "mcp.json"
    first_content = mcp_path.read_text(encoding="utf-8")
    second = bootstrap_user_config(home=home, repo_root=repo)

    assert first.added_mcp_servers == []
    assert second.added_mcp_servers == []
    assert mcp_path.read_text(encoding="utf-8") == first_content


def test_bootstrap_backs_up_invalid_mcp_config(tmp_path):
    home = tmp_path / "home"
    repo = _fake_repo(tmp_path)
    mcp_path = home / ".mycodingagent" / "mcp.json"
    mcp_path.parent.mkdir(parents=True)
    mcp_path.write_text("{", encoding="utf-8")

    result = bootstrap_user_config(home=home, repo_root=repo)

    assert result.recreated_invalid_mcp_config is True
    assert result.mcp_backup_path is not None
    assert result.mcp_backup_path.read_text(encoding="utf-8") == "{"
    assert json.loads(mcp_path.read_text(encoding="utf-8"))["servers"]["github"]["disabled"] is True


def test_repository_config_template_exposes_external_configuration_fields():
    template = json.loads((ROOT / ".mycodingagent" / "config.example.json").read_text(encoding="utf-8"))
    required_paths = [
        ("model", "active"),
        ("model", "providers"),
        ("model", "profiles"),
        ("model", "long_term_memory"),
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
        ("search", "tavily_api_key"),
        ("web_fetch", "enabled"),
        ("web_fetch", "timeout"),
        ("web_fetch", "max_bytes"),
        ("web_fetch", "max_chars"),
        ("network", "enabled"),
        ("network", "upstream_proxy"),
        ("network", "allow_domains"),
    ]
    for section, key in required_paths:
        assert key in template[section], f"missing {section}.{key}"
    assert template["model"]["profiles"]["main"] == {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
    }
    assert template["model"]["profiles"]["memory_search"] == {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "reasoning": {"thinking": "disabled"},
    }
    assert template["model"]["long_term_memory"] == {
        "storage": "main",
        "search": "memory_search",
    }
    assert "api" not in template["model"]["profiles"]["main"]
    assert "network" not in template["docker"]
    assert template["search"]["tavily_api_key"] == ""
    assert template["network"]["allow_domains"] == ["*"]
    assert template["client"]["max_tool_rounds"] == 100
    assert template["web_fetch"]["max_redirects"] == 5


def test_repository_mcp_template_exposes_lazy_readonly_tavily_server():
    template = json.loads(
        (ROOT / ".mycodingagent" / "mcp.example.json").read_text(encoding="utf-8")
    )
    tavily = template["servers"]["tavily"]

    assert tavily["url"] == "https://mcp.tavily.com/mcp/"
    assert tavily["headers"]["Authorization"] == "Bearer ${TAVILY_API_KEY}"
    assert tavily["required_env"] == ["TAVILY_API_KEY"]
    assert tavily["auto_start"] is True
    assert tavily["permissions"]["read_tools"] == ["tavily-search", "tavily-extract"]
    assert tavily["permissions"]["readonly_by_default"] is True


def test_main_bootstrap_creates_config_before_runtime_config_import(tmp_path):
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PYTHONPATH": str(ROOT),
    }
    for name in MODEL_API_ENV_NAMES:
        env.pop(name, None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "__main__.py")],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )

    assert result.returncode == 1
    assert (tmp_path / "home" / ".mycodingagent" / "config.json").exists()
    assert (tmp_path / "home" / ".mycodingagent" / "README.md").exists()
    assert (tmp_path / "home" / ".mycodingagent" / "mcp.json").exists()
    assert (tmp_path / "home" / ".mycodingagent" / "MCP.md").exists()
    assert "已创建配置文件" in result.stdout
    assert "已创建 MCP 配置文件" in result.stdout
    assert "启动配置无效" in result.stderr
