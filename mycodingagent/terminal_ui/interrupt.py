from __future__ import annotations

import asyncio
import codecs
import os
import sys
import termios
import tty
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import TextIO

ESCAPE_TIMEOUT_SECONDS = 0.15


class PromptCancelled(Exception):
    pass


_CURRENT_COORDINATOR: ContextVar[TerminalInputCoordinator | None] = ContextVar(
    "terminal_input_coordinator", default=None
)


class TerminalInputCoordinator:
    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdin
        self._fd: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._old_settings: list | None = None
        self._cancel_event: asyncio.Event | None = None
        self._reason = ""
        self._active = False
        self._escape_timer: asyncio.TimerHandle | None = None
        self._context_token: Token | None = None

    @property
    def is_tty(self) -> bool:
        try:
            return bool(self.stream.isatty())
        except Exception:
            return False

    @property
    def reason(self) -> str:
        return self._reason

    def start_interrupt_watch(self, cancel_event: asyncio.Event) -> None:
        self._cancel_event = cancel_event
        self._reason = ""
        if not self.is_tty:
            return
        self._loop = asyncio.get_running_loop()
        self._fd = self.stream.fileno()
        self._activate_reader()
        self._context_token = _CURRENT_COORDINATOR.set(self)

    def stop_interrupt_watch(self) -> None:
        self._cancel_escape_timer()
        self._deactivate_reader()
        self._cancel_event = None
        if self._context_token is not None:
            _CURRENT_COORDINATOR.reset(self._context_token)
            self._context_token = None

    def _on_interrupt_input(self) -> None:
        if self._fd is None or self._cancel_event is None:
            return
        data = os.read(self._fd, 64)
        if not data:
            return
        # A lone ESC is ambiguous until the short timeout expires. Any bytes that
        # follow it belong to a terminal escape sequence (for example an arrow key).
        if self._escape_timer is not None:
            self._cancel_escape_timer()
        if b"\x03" in data:
            self._trigger("sigint")
            return
        escape_index = data.find(b"\x1b")
        if escape_index < 0:
            return
        if len(data) > escape_index + 1:
            return
        assert self._loop is not None
        self._escape_timer = self._loop.call_later(
            ESCAPE_TIMEOUT_SECONDS, lambda: self._trigger("esc")
        )

    def _trigger(self, reason: str) -> None:
        self._cancel_escape_timer()
        self._reason = reason
        if self._cancel_event is not None:
            self._cancel_event.set()

    def _cancel_escape_timer(self) -> None:
        if self._escape_timer is not None:
            self._escape_timer.cancel()
            self._escape_timer = None

    def _deactivate_reader(self) -> None:
        try:
            if self._active and self._loop is not None and self._fd is not None:
                self._loop.remove_reader(self._fd)
        finally:
            self._active = False
            if self._old_settings is not None and self._fd is not None:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)
            self._old_settings = None

    def _pause_interrupt_watch(self) -> bool:
        was_active = self._active
        self._deactivate_reader()
        return was_active

    def _resume_interrupt_watch(self, should_resume: bool) -> None:
        if not should_resume or not self.is_tty or self._cancel_event is None:
            return
        assert self._loop is not None and self._fd is not None
        self._activate_reader()

    def _activate_reader(self) -> None:
        assert self._loop is not None and self._fd is not None
        old_settings = termios.tcgetattr(self._fd)
        try:
            enable_cbreak_interrupt_mode(self._fd)
            self._loop.add_reader(self._fd, self._on_interrupt_input)
        except BaseException:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, old_settings)
            self._old_settings = None
            self._active = False
            raise
        self._old_settings = old_settings
        self._active = True

    async def read_text(self, prompt: str) -> str:
        if not self.is_tty:
            return await asyncio.to_thread(input, prompt)
        was_active = self._pause_interrupt_watch()
        try:
            return await self._read_raw_line(prompt)
        finally:
            self._resume_interrupt_watch(was_active)

    async def read_choice(self, prompt: str, *, allowed: set[str]) -> str:
        answer = (await self.read_text(prompt)).strip().lower()
        return answer if answer in allowed else ""

    async def _read_raw_line(self, prompt: str) -> str:
        loop = asyncio.get_running_loop()
        fd = self.stream.fileno()
        old_settings = termios.tcgetattr(self.stream)
        decoder = codecs.getincrementaldecoder(self.stream.encoding or "utf-8")()
        future: asyncio.Future[str] = loop.create_future()
        buffer: list[str] = []
        sys.stdout.write(prompt)
        sys.stdout.flush()

        def on_input() -> None:
            data = os.read(fd, 64)
            for char in decoder.decode(data):
                if char == "\x1b":
                    if not future.done():
                        future.set_exception(PromptCancelled())
                    return
                if char == "\x03":
                    if not future.done():
                        future.set_exception(PromptCancelled())
                    return
                if char in {"\r", "\n"}:
                    if not future.done():
                        future.set_result("".join(buffer))
                    return
                if char in {"\x7f", "\b"}:
                    if buffer:
                        buffer.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                    continue
                if char.isprintable() or char == "\t":
                    buffer.append(char)
                    sys.stdout.write(char)
                    sys.stdout.flush()

        reader_added = False
        try:
            enable_cbreak_interrupt_mode(fd)
            loop.add_reader(fd, on_input)
            reader_added = True
            return await future
        finally:
            if reader_added:
                loop.remove_reader(fd)
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            sys.stdout.write("\n")
            sys.stdout.flush()

    @contextmanager
    def paused_for_blocking_input(self):
        was_active = self._pause_interrupt_watch()
        try:
            yield
        finally:
            self._resume_interrupt_watch(was_active)


class InterruptWatcher:
    def __init__(self, coordinator: TerminalInputCoordinator | None = None) -> None:
        self.coordinator = coordinator or TerminalInputCoordinator()
        self.triggered = asyncio.Event()

    @property
    def reason(self) -> str:
        return self.coordinator.reason

    async def __aenter__(self) -> InterruptWatcher:
        self.coordinator.start_interrupt_watch(self.triggered)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.coordinator.stop_interrupt_watch()


def coordinated_input(prompt: str) -> str:
    coordinator = _CURRENT_COORDINATOR.get()
    if coordinator is None:
        return input(prompt)
    with coordinator.paused_for_blocking_input():
        return input(prompt)


def enable_cbreak_interrupt_mode(fd: int) -> None:
    tty.setcbreak(fd)
    attrs = termios.tcgetattr(fd)
    attrs[3] &= ~termios.ISIG
    termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
