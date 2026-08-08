from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
from pathlib import Path

import pytest

import mycodingagent.managed_network as managed_network
from mycodingagent.configuration.settings import NetworkConfig
from mycodingagent.managed_network import (
    ManagedNetworkRuntime,
    NetworkPolicyError,
    _domain_allowed,
    _is_public_address,
)
from mycodingagent.network_access import NetworkAccessRuntime


def _runtime(tmp_path: Path, **overrides) -> ManagedNetworkRuntime:
    values = {
        "enabled": True,
        "upstream_proxy": "direct",
        "allow_domains": ("*",),
        "deny_domains": (),
        "connect_timeout": 2.0,
        "idle_timeout": 5.0,
        "ca_bundle": "",
    }
    values.update(overrides)
    access = NetworkAccessRuntime(enabled=values.pop("enabled"))
    return ManagedNetworkRuntime(NetworkConfig(**values), access, workspace_root=tmp_path)


def test_domain_policy_is_allowlist_first_and_deny_wins():
    assert _domain_allowed("api.example.com", ("**.example.com",), ())
    assert _domain_allowed("example.com", ("**.example.com",), ())
    assert _domain_allowed("api.example.com", ("*.example.com",), ())
    assert not _domain_allowed("example.com", ("*.example.com",), ())
    assert not _domain_allowed("blocked.example.com", ("*",), ("blocked.example.com",))


@pytest.mark.parametrize(
    ("address", "allowed"),
    [
        ("8.8.8.8", True),
        ("127.0.0.1", False),
        ("10.0.0.1", False),
        ("172.16.0.1", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),
        ("::1", False),
    ],
)
def test_only_public_addresses_are_eligible(address, allowed):
    assert _is_public_address(address) is allowed


def test_auto_upstream_prefers_https_then_http_then_all_proxy(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, upstream_proxy="auto")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7880")
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7891")

    assert runtime._selected_upstream("https") == "http://127.0.0.1:7890"
    assert runtime._selected_upstream("http") == "http://127.0.0.1:7880"
    assert runtime.display_upstream() == "http://127.0.0.1:7890"


def test_proxy_environment_contains_upper_and_lower_case_without_credentials(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.gateway = "172.30.0.1"
    runtime.proxy_port = 3128

    env = runtime.proxy_environment

    assert env["HTTP_PROXY"] == "http://172.30.0.1:3128"
    assert env["http_proxy"] == env["HTTP_PROXY"]
    assert env["NO_PROXY"] == "mycodingagent-devserver"


def test_mcp_proxy_identity_allows_one_server_while_global_network_is_off(tmp_path):
    runtime = _runtime(tmp_path, enabled=False)
    runtime.gateway = "172.30.0.1"
    runtime.proxy_port = 3128
    runtime.access.set_mcp_enabled("github", True)
    proxy_url = runtime.proxy_url_for_mcp("github")
    credentials = proxy_url.split("@", 1)[0].removeprefix("http://")
    header = (
        b"CONNECT github.com:443 HTTP/1.1\r\n"
        + b"Proxy-Authorization: Basic "
        + base64.b64encode(credentials.encode("utf-8"))
        + b"\r\n\r\n"
    )

    client = runtime._network_client(header)

    assert client == "github"
    assert runtime.access.allows_external_client(client)
    assert not runtime.access.allows_external_client("tavily")


def test_managed_subnet_candidates_are_deterministic_small_and_distinct():
    first = list(managed_network._managed_subnet_candidates("runtime-a"))
    second = list(managed_network._managed_subnet_candidates("runtime-a"))

    assert first == second
    assert len(first) == managed_network.MANAGED_SUBNET_ATTEMPTS
    assert all(item.prefixlen == 28 for item in first)
    assert all(item.subnet_of(managed_network.MANAGED_SUBNET_POOL) for item in first)
    assert len(set(first)) == len(first)


def test_initialize_retries_conflicting_managed_subnet(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    runtime.runtime_id = "runtime-a"
    runtime.network_name = "mycodingagent-network-runtime-a"
    commands: list[tuple[str, ...]] = []
    create_attempts = 0

    async def fake_docker(*args):
        nonlocal create_attempts
        commands.append(args)
        if args[:2] == ("network", "create"):
            create_attempts += 1
            if create_attempts == 1:
                return managed_network._ProcessResult(
                    1, "", "could not find an available, non-overlapping IPv4 address pool"
                )
            return managed_network._ProcessResult(0, "network-id", "")
        if args[:2] == ("network", "inspect"):
            return managed_network._ProcessResult(0, "10.240.0.1", "")
        return managed_network._ProcessResult(0, "", "")

    class FakeSocket:
        def getsockname(self):
            return ("10.240.0.1", 12345)

    class FakeServer:
        sockets = [FakeSocket()]

        def close(self):
            return None

        async def wait_closed(self):
            return None

    async def fake_start_server(*_args, **_kwargs):
        return FakeServer()

    monkeypatch.setattr(managed_network, "_docker_available", lambda: True)
    monkeypatch.setattr(managed_network, "_docker", fake_docker)
    monkeypatch.setattr(asyncio, "start_server", fake_start_server)

    status = asyncio.run(runtime.initialize())

    assert status.ready is True
    assert create_attempts == 2
    create_commands = [command for command in commands if command[:2] == ("network", "create")]
    first_subnet = create_commands[0][create_commands[0].index("--subnet") + 1]
    second_subnet = create_commands[1][create_commands[1].index("--subnet") + 1]
    assert first_subnet != second_subnet
    assert runtime.subnet == second_subnet


def test_disabling_access_cancels_active_public_connections(tmp_path):
    async def run():
        runtime = _runtime(tmp_path)
        cancelled = asyncio.Event()

        async def pending():
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(pending())
        await asyncio.sleep(0)
        runtime._connections.add(task)
        await runtime.access.set_enabled_async(False)
        return task, cancelled

    task, cancelled = asyncio.run(run())
    assert task.cancelled()
    assert cancelled.is_set()


def test_close_local_forces_inflight_proxy_connections_to_finish(tmp_path):
    async def run():
        runtime = _runtime(tmp_path, connect_timeout=30.0)
        server = await asyncio.start_server(runtime._accept, "127.0.0.1", 0)
        runtime._server = server
        port = server.sockets[0].getsockname()[1]
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"CONNECT example.com:443 HTTP/1.1\r\n")
        await writer.drain()
        await asyncio.sleep(0)

        await asyncio.wait_for(runtime.close_local(), timeout=2.0)

        assert runtime._server is None
        assert not runtime._connections
        assert not runtime._writers
        writer.close()
        with contextlib.suppress(ConnectionResetError):
            await writer.wait_closed()

    asyncio.run(run())


def test_loopback_target_uses_bound_workspace_resolver(tmp_path):
    async def run():
        received = asyncio.Event()

        async def application(reader, writer):
            received.set()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(application, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        runtime = _runtime(tmp_path)

        async def resolve(requested_port):
            assert requested_port == 5173
            return "127.0.0.1", port

        runtime.bind_local_target(resolve)
        reader, writer = await runtime._open_target("localhost", 5173, "http")
        await asyncio.wait_for(received.wait(), 1)
        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()

    asyncio.run(run())


def test_upstream_proxy_mode_does_not_resolve_target_with_host_dns(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, upstream_proxy="http://127.0.0.1:7890")

    async def fail_getaddrinfo(*_args, **_kwargs):
        raise AssertionError("proxy-routed domains must be resolved by the upstream proxy")

    async def run():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fail_getaddrinfo)
        await runtime._validate_target("en.wikipedia.org", 443, resolve_dns=False)

    asyncio.run(run())


def test_direct_mode_rejects_domain_with_any_non_public_dns_result(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, upstream_proxy="direct")

    async def mixed_getaddrinfo(*_args, **_kwargs):
        return [
            (2, 1, 6, "", ("199.59.148.96", 443)),
            (10, 1, 6, "", ("2001::1", 443, 0, 0)),
        ]

    async def run():
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", mixed_getaddrinfo)
        with pytest.raises(NetworkPolicyError) as raised:
            await runtime._validate_target("en.wikipedia.org", 443, resolve_dns=True)
        return raised.value

    error = asyncio.run(run())
    assert error.error_code == "private_target_denied"
    assert error.status == 403


def test_proxy_returns_structured_403_instead_of_silent_disconnect(tmp_path):
    async def run():
        runtime = _runtime(tmp_path, enabled=False)
        server = await asyncio.start_server(runtime._accept, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(
                b"GET http://example.com/ HTTP/1.1\r\n"
                b"Host: example.com\r\nConnection: close\r\n\r\n"
            )
            await writer.drain()
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            return response
        finally:
            server.close()
            await server.wait_closed()

    response = asyncio.run(run())
    header, body = response.split(b"\r\n\r\n", 1)
    assert b"HTTP/1.1 403" in header
    assert json.loads(body) == {
        "error_code": "network_disabled",
        "message": "Agent 工具公网权限已关闭",
        "retryable": False,
    }
