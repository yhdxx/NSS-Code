from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import struct
import termios

from mycodingagent.terminal_ui.application import TerminalApplication
from mycodingagent.terminal_ui.theme import ACTIVE_USER_ANSI


def test_background_output_does_not_corrupt_active_prompt() -> None:
    async def scenario() -> None:
        master_fd, slave_fd = pty.openpty()
        input_stream = os.fdopen(os.dup(slave_fd), "r", encoding="utf-8", buffering=1)
        output_stream = os.fdopen(os.dup(slave_fd), "w", encoding="utf-8", buffering=1)
        terminal = TerminalApplication(stdin=input_stream, stdout=output_stream)
        try:
            await terminal.start()
            terminal.mark_ready()
            prompt_task = asyncio.create_task(terminal.read_message(prompt_header="User"))
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


def test_busy_terminal_queues_messages_in_order_and_escape_interrupts() -> None:
    async def scenario() -> None:
        master_fd, slave_fd = pty.openpty()
        input_stream = os.fdopen(os.dup(slave_fd), "r", encoding="utf-8", buffering=1)
        output_stream = os.fdopen(os.dup(slave_fd), "w", encoding="utf-8", buffering=1)
        terminal = TerminalApplication(stdin=input_stream, stdout=output_stream)
        cancel_event = asyncio.Event()
        try:
            await terminal.start()
            terminal.mark_ready()
            assert terminal._application is not None
            assert terminal._application.full_screen is False
            terminal.bind_cancel_event(cancel_event)

            os.write(master_fd, b"first\r")
            await asyncio.sleep(0.05)
            os.write(master_fd, b"second\r")
            await asyncio.sleep(0.05)

            assert await terminal.read_message() == "first"
            assert terminal.follow_up_signal.is_set()
            assert await terminal.read_message() == "second"
            assert not terminal.follow_up_signal.is_set()

            os.write(master_fd, b"queued\r")
            await asyncio.sleep(0.05)
            os.write(master_fd, b"\x1b")
            await asyncio.sleep(0.75)
            assert cancel_event.is_set()
            assert await terminal.read_message() == "queued"
        finally:
            terminal.bind_cancel_event(None)
            await terminal.close()
            input_stream.close()
            output_stream.close()
            os.close(master_fd)
            os.close(slave_fd)

    asyncio.run(scenario())


def test_active_user_message_uses_composer_background() -> None:
    master_fd, slave_fd = pty.openpty()
    input_stream = os.fdopen(os.dup(slave_fd), "r", encoding="utf-8", buffering=1)
    output_stream = os.fdopen(os.dup(slave_fd), "w", encoding="utf-8", buffering=1)
    terminal = TerminalApplication(stdin=input_stream, stdout=output_stream)
    try:
        terminal._commit_user_message("hello\nworld")
        rendered = terminal._render_queue.get_nowait()

        assert ACTIVE_USER_ANSI in rendered
        assert "hello" in rendered
        assert "world" in rendered
        assert terminal._output == "User:\nhello\nworld\n"
    finally:
        input_stream.close()
        output_stream.close()
        os.close(master_fd)
        os.close(slave_fd)


def test_loading_hides_composer_and_discards_early_input() -> None:
    async def scenario() -> None:
        master_fd, slave_fd = pty.openpty()
        input_stream = os.fdopen(os.dup(slave_fd), "r", encoding="utf-8", buffering=1)
        output_stream = os.fdopen(os.dup(slave_fd), "w", encoding="utf-8", buffering=1)
        terminal = TerminalApplication(stdin=input_stream, stdout=output_stream)
        try:
            await terminal.start()
            assert terminal._ready is False
            os.write(master_fd, b"ignored\r")
            await asyncio.sleep(0.05)

            terminal.mark_ready()
            task = asyncio.create_task(terminal.read_message())
            os.write(master_fd, b"accepted\r")

            assert await asyncio.wait_for(task, timeout=2.0) == "accepted"
        finally:
            await terminal.close()
            input_stream.close()
            output_stream.close()
            os.close(master_fd)
            os.close(slave_fd)

    asyncio.run(scenario())


def test_queued_message_preview_uses_required_title_and_one_line_truncation() -> None:
    master_fd, slave_fd = pty.openpty()
    input_stream = os.fdopen(os.dup(slave_fd), "r", encoding="utf-8", buffering=1)
    output_stream = os.fdopen(os.dup(slave_fd), "w", encoding="utf-8", buffering=1)
    terminal = TerminalApplication(stdin=input_stream, stdout=output_stream)
    try:
        terminal._message_queue.submit("a very long follow up " * 20, waiting=True)
        assert terminal._message_queue.visible_messages == ()

        terminal.notify_agent_output()
        preview = terminal._formatted_queue_preview()
        rendered = "".join(text for _style, text in preview)

        assert rendered.startswith(
            "Messages to be submitted after next tool call (press esc to interrupt and send immediately)\n"
        )
        assert rendered.splitlines()[1].startswith("└ ")
        assert rendered.splitlines()[1].endswith("...")
        assert len(rendered.splitlines()) == 2
    finally:
        input_stream.close()
        output_stream.close()
        os.close(master_fd)
        os.close(slave_fd)


def test_terminal_resize_redraws_compact_composer_without_committing_separator_lines() -> None:
    async def scenario() -> None:
        master_fd, slave_fd = pty.openpty()
        input_stream = os.fdopen(os.dup(slave_fd), "r", encoding="utf-8", buffering=1)
        output_stream = os.fdopen(os.dup(slave_fd), "w", encoding="utf-8", buffering=1)
        terminal = TerminalApplication(stdin=input_stream, stdout=output_stream)

        def resize(columns: int) -> None:
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, columns, 0, 0))
            assert terminal._application is not None
            terminal._application._on_resize()

        try:
            resize(80)
            await terminal.start()
            terminal.mark_ready()
            assert terminal._input_buffer is not None
            terminal._input_buffer.text = "x" * 120

            resize(40)
            await asyncio.sleep(0.05)
            narrow_height = terminal._input_height().preferred
            resize(120)
            await asyncio.sleep(0.05)
            wide_height = terminal._input_height().preferred
            assert narrow_height > wide_height

            terminal._input_buffer.reset()
            prompt_task = asyncio.create_task(terminal.read_message())
            os.write(master_fd, b"still works\r")
            assert await asyncio.wait_for(prompt_task, timeout=2.0) == "still works"
        finally:
            await terminal.close()
            os.set_blocking(master_fd, False)
            chunks: list[bytes] = []
            while True:
                try:
                    chunks.append(os.read(master_fd, 65536))
                except BlockingIOError:
                    break
            rendered = b"".join(chunks).decode("utf-8", errors="ignore")
            assert "────────" not in rendered
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
