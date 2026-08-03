from __future__ import annotations

import asyncio

from mycodingagent.app import main as app_main
from mycodingagent.workspace.lease import WorkspaceLeaseError


def test_startup_error_is_printed_after_terminal_closes(monkeypatch, capsys):
    events: list[str] = []

    class FakeTerminal:
        async def start(self) -> None:
            events.append("start")

        async def close(self) -> None:
            events.append("close")

    async def fail_startup(_terminal) -> None:
        raise WorkspaceLeaseError("state directory is read-only")

    monkeypatch.setattr(app_main, "TerminalApplication", FakeTerminal)
    monkeypatch.setattr(app_main, "_run", fail_startup)

    exit_code = asyncio.run(app_main.main())

    assert events == ["start", "close"]
    assert exit_code == 1
    assert capsys.readouterr().err == "无法启动：state directory is read-only\n"
