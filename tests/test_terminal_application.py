from __future__ import annotations

import asyncio
import os
import pty

from mycodingagent.terminal_ui.application import TerminalApplication


def test_background_output_does_not_corrupt_active_prompt() -> None:
    async def scenario() -> None:
        master_fd, slave_fd = pty.openpty()
        input_stream = os.fdopen(os.dup(slave_fd), "r", encoding="utf-8", buffering=1)
        output_stream = os.fdopen(os.dup(slave_fd), "w", encoding="utf-8", buffering=1)
        terminal = TerminalApplication(stdin=input_stream, stdout=output_stream)
        try:
            await terminal.start()
            prompt_task = asyncio.create_task(terminal.read_prompt(prompt_header="User"))
            await asyncio.sleep(0.05)
            os.write(master_fd, b"hel")
            await asyncio.sleep(0.05)
            terminal.emit("[project graph] background refresh\n")
            await asyncio.sleep(0.05)
            os.write(master_fd, b"lo\r")

            assert await asyncio.wait_for(prompt_task, timeout=2.0) == "hello"
            assert "[project graph] background refresh" in terminal._output
            assert "User:\nhello" in terminal._output
        finally:
            await terminal.close()
            input_stream.close()
            output_stream.close()
            os.close(master_fd)
            os.close(slave_fd)

    asyncio.run(scenario())


def test_general_terminal_output_adapter_is_line_based() -> None:
    class _Stream:
        def __init__(self) -> None:
            self.value = ""
            self.input_lines = ["typed value\n"]

        def isatty(self) -> bool:
            return False

        def write(self, text: str) -> int:
            self.value += text
            return len(text)

        def flush(self) -> None:
            return None

        def readline(self) -> str:
            return self.input_lines.pop(0) if self.input_lines else ""

    stream = _Stream()
    terminal = TerminalApplication(stdin=stream, stdout=stream)  # type: ignore[arg-type]

    terminal.print("hello")

    assert stream.value == "hello\n"

    async def read_line() -> str:
        await terminal.start()
        try:
            return await terminal.read_prompt(prompt_header="User")
        finally:
            await terminal.close()

    assert asyncio.run(read_line()) == "typed value"
    assert stream.value.endswith("User: ")
