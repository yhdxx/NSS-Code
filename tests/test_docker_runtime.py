from __future__ import annotations

import asyncio

from mycodingagent.tool_runtime import bash


def test_check_docker_swap_limit_support_reports_host_capability(monkeypatch):
    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"false\n[]", b""

    async def create_process(*_args, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr(bash.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(bash, "docker_subprocess_env", lambda: {})
    monkeypatch.setattr(bash.asyncio, "create_subprocess_exec", create_process)

    notice = asyncio.run(bash.check_docker_swap_limit_support())

    assert notice is not None
    assert "物理内存限制仍然生效" in notice


def test_check_docker_swap_limit_support_is_advisory_on_clean_host(monkeypatch):
    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"true\n[]", b""

    async def create_process(*_args, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr(bash.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(bash, "docker_subprocess_env", lambda: {})
    monkeypatch.setattr(bash.asyncio, "create_subprocess_exec", create_process)

    assert asyncio.run(bash.check_docker_swap_limit_support()) is None
