from __future__ import annotations

import asyncio
import os
import pty
import select
import termios
import time

from mycodingagent.llm_runtime import client as agent_client
from mycodingagent.llm_runtime.streaming import PendingToolCall, StreamRoundResult
from mycodingagent.terminal_ui.interrupt import InterruptWatcher, TerminalInputCoordinator
from mycodingagent.tool_runtime.execution import ToolExecution


class _TtyStream:
    encoding = "utf-8"

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def fileno(self) -> int:
        return self._fd

    def isatty(self) -> bool:
        return os.isatty(self._fd)


def _open_configured_pty() -> tuple[int, int]:
    master_fd, slave_fd = pty.openpty()
    attrs = termios.tcgetattr(slave_fd)
    attrs[1] |= termios.OPOST
    if hasattr(termios, "ONLCR"):
        attrs[1] |= termios.ONLCR
    termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
    return master_fd, slave_fd


def _read_pty_until(master_fd: int, expected: bytes, timeout: float = 1.0) -> bytes:
    deadline = time.monotonic() + timeout
    chunks: list[bytes] = []
    while time.monotonic() < deadline:
        ready, _, _ = select.select([master_fd], [], [], max(0.0, deadline - time.monotonic()))
        if not ready:
            break
        chunks.append(os.read(master_fd, 4096))
        data = b"".join(chunks)
        if expected in data:
            return data
    return b"".join(chunks)


def test_interrupt_watcher_keeps_output_processing_and_restores_terminal():
    async def scenario():
        master_fd, slave_fd = _open_configured_pty()
        original_attrs = termios.tcgetattr(slave_fd)
        coordinator = TerminalInputCoordinator(_TtyStream(slave_fd))
        cancel_event = asyncio.Event()
        try:
            coordinator.start_interrupt_watch(cancel_event)
            active_attrs = termios.tcgetattr(slave_fd)

            assert active_attrs[1] & termios.OPOST
            assert active_attrs[1] == original_attrs[1]

            expected = b"hello\r\nworld\r\n" if hasattr(termios, "ONLCR") else b"hello\nworld\n"
            output_fd = os.dup(slave_fd)
            with os.fdopen(output_fd, "w", encoding="utf-8", buffering=1) as output:
                print("hello", file=output)
                print("world", file=output)
                output.flush()

            assert expected in _read_pty_until(master_fd, expected)
        finally:
            coordinator.stop_interrupt_watch()
            restored_attrs = termios.tcgetattr(slave_fd)
            os.close(master_fd)
            os.close(slave_fd)

        assert restored_attrs == original_attrs

    asyncio.run(scenario())


def test_interrupt_watcher_restores_terminal_after_exception():
    async def scenario():
        master_fd, slave_fd = _open_configured_pty()
        original_attrs = termios.tcgetattr(slave_fd)
        coordinator = TerminalInputCoordinator(_TtyStream(slave_fd))
        try:
            try:
                async with InterruptWatcher(coordinator):
                    raise RuntimeError("boom")
            except RuntimeError:
                pass

            assert termios.tcgetattr(slave_fd) == original_attrs
        finally:
            coordinator.stop_interrupt_watch()
            os.close(master_fd)
            os.close(slave_fd)

    asyncio.run(scenario())


def test_interrupt_watcher_cbreak_mode_still_reads_ctrl_c_and_escape():
    async def scenario(data: bytes, reason: str):
        master_fd, slave_fd = _open_configured_pty()
        coordinator = TerminalInputCoordinator(_TtyStream(slave_fd))
        cancel_event = asyncio.Event()
        try:
            coordinator.start_interrupt_watch(cancel_event)
            os.write(master_fd, data)
            await asyncio.wait_for(cancel_event.wait(), timeout=1.0)
            assert coordinator.reason == reason
        finally:
            coordinator.stop_interrupt_watch()
            os.close(master_fd)
            os.close(slave_fd)

    asyncio.run(scenario(b"\x03", "sigint"))
    asyncio.run(scenario(b"\x1b", "esc"))


def test_interruption_between_tools_keeps_protocol_pairs(monkeypatch):
    async def scenario():
        cancel_event = asyncio.Event()
        calls = [
            PendingToolCall("call_1", "FakeTool", "{}"),
            PendingToolCall("call_2", "FakeTool", "{}"),
        ]

        async def fake_stream(*args, **kwargs):
            return StreamRoundResult("", calls)

        executed: list[str] = []

        async def fake_execute(registry, tool_name, raw_args, skill_runtime, **kwargs):
            executed.append(tool_name)
            cancel_event.set()
            return ToolExecution("first completed")

        monkeypatch.setattr(agent_client, "stream_one_round", fake_stream)
        monkeypatch.setattr(agent_client, "execute_local_tool", fake_execute)

        text, messages = await agent_client.ask_deepseek(
            client=object(),
            prompt="do two things",
            registry=object(),
            tools=[],
            messages=[{"role": "system", "content": "fixed"}],
            cancel_event=cancel_event,
        )

        assistant_calls = next(message["tool_calls"] for message in messages if message.get("tool_calls"))
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert {call["id"] for call in assistant_calls} == {
            message["tool_call_id"] for message in tool_messages
        }
        assert executed == ["FakeTool"]
        assert tool_messages[0]["content"] == "first completed"
        assert "未执行" in tool_messages[1]["content"]
        assert "Error: API" not in text
        assert messages[-1]["metadata"]["interrupted"] is True

    asyncio.run(scenario())


def test_stream_interruption_is_not_an_api_error(monkeypatch):
    async def scenario():
        cancel_event = asyncio.Event()
        cancel_event.set()

        class _Completions:
            async def create(self, **kwargs):
                raise AssertionError("request should be cancelled before it starts")

        class _Client:
            class _Chat:
                completions = _Completions()

            chat = _Chat()

        result = await agent_client.stream_one_round(
            _Client(), "model", [], [], display=False, cancel_event=cancel_event
        )
        assert result.interrupted is True
        assert not result.text.startswith("Error: API")

    asyncio.run(scenario())
