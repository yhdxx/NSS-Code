from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from mycodingagent.configuration.settings import SearchConfig
from mycodingagent.search_runtime.service import ProcessResult, SearXNGServiceRuntime


def _config(**overrides) -> SearchConfig:
    values = {
        "enabled": True,
        "endpoint": "",
        "image": "searxng:test",
        "timeout": 2.0,
        "max_results": 10,
        "max_query_chars": 500,
        "language": "zh-CN",
        "safesearch": 0,
        "fetch_max_bytes": 100_000,
        "fetch_max_chars": 50_000,
        "max_redirects": 5,
    }
    values.update(overrides)
    return SearchConfig(**values)


def _service(tmp_path: Path, **config_overrides) -> SearXNGServiceRuntime:
    repo = tmp_path / "repo"
    (repo / "infra" / "searxng").mkdir(parents=True)
    (repo / "infra" / "searxng" / "settings.yml").write_text(
        'server:\n  secret_key: "__SEARXNG_SECRET__"\noutgoing:\n  proxies:\n    "all://": ["__RUNTIME_PROXY__"]\n',
        encoding="utf-8",
    )
    network = SimpleNamespace(
        runtime_id="runtime-a",
        network_name="managed-runtime-a",
        proxy_url="http://172.30.0.1:3128",
        proxy_environment={"HTTP_PROXY": "http://172.30.0.1:3128"},
    )
    return SearXNGServiceRuntime(
        _config(**config_overrides),
        network,
        workspace_root=tmp_path / "workspace",
        repo_root=repo,
        startup_timeout=1,
    )


def test_private_service_starts_in_runtime_network_and_returns_random_endpoint(tmp_path, monkeypatch):
    service = _service(tmp_path)
    calls: list[tuple[str, ...]] = []

    async def docker(*args: str):
        calls.append(args)
        if args[0] == "inspect":
            return ProcessResult(0, "172.30.0.3\n", "")
        return ProcessResult(0, service.container_name, "")

    async def ready():
        return True

    monkeypatch.setattr(service, "_docker", docker)
    monkeypatch.setattr(service, "_wait_until_healthy", ready)

    result = asyncio.run(service.ensure_started())

    assert result.managed is True
    assert result.ready is True
    assert result.endpoint == "http://172.30.0.3:8080/search"
    run_args = calls[0]
    assert ["--network", "managed-runtime-a"] == list(
        run_args[run_args.index("--network"):run_args.index("--network") + 2]
    )
    assert "--publish" not in run_args
    assert "HTTP_PROXY=http://172.30.0.1:3128" in run_args
    assert service.settings_path.is_relative_to(tmp_path / "workspace")
    assert "__SEARXNG_SECRET__" not in service.settings_path.read_text(encoding="utf-8")
    assert "http://172.30.0.1:3128" in service.settings_path.read_text(encoding="utf-8")


def test_custom_endpoint_is_not_managed(tmp_path, monkeypatch):
    endpoint = "https://search.example.com/search"
    service = _service(tmp_path, endpoint=endpoint)

    async def unexpected(*_args):
        raise AssertionError("custom endpoint must not start Docker")

    monkeypatch.setattr(service, "_docker", unexpected)

    result = asyncio.run(service.ensure_started())

    assert result == type(result)(False, True, endpoint=endpoint)
    assert not service.state_dir.exists()


def test_container_failure_is_reported(tmp_path, monkeypatch):
    service = _service(tmp_path)

    async def docker(*_args):
        return ProcessResult(1, "", "daemon unavailable")

    monkeypatch.setattr(service, "_docker", docker)

    result = asyncio.run(service.ensure_started())

    assert result.ready is False
    assert "daemon unavailable" in result.reason


def test_close_removes_only_current_runtime_container(tmp_path, monkeypatch):
    service = _service(tmp_path)
    calls: list[tuple[str, ...]] = []

    async def docker(*args):
        calls.append(args)
        return ProcessResult(0, "", "")

    monkeypatch.setattr(service, "_docker", docker)
    asyncio.run(service.close())

    assert calls == [("rm", "-f", "mycodingagent-searxng-runtime-a")]


def test_disabled_search_does_not_start_container(tmp_path):
    service = _service(tmp_path, enabled=False)

    result = asyncio.run(service.ensure_started())

    assert result.ready is False
    assert result.reason == "search.enabled=false"
