from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol, TextIO

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.input.defaults import create_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Float, FloatContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.styles import Style

from mycodingagent.commands import CommandRegistry


MAX_OUTPUT_CHARS = 500_000
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CURRENT_TERMINAL: ContextVar[TerminalApplication | None] = ContextVar(
    "mycodingagent_terminal_application",
    default=None,
)


class TerminalCancelled(Exception):
    pass


class TerminalInput(Protocol):
    async def read_text(self, prompt: str) -> str: ...

    async def read_choice(self, prompt: str, *, allowed: set[str]) -> str: ...


class SharedTerminalInput:
    async def read_text(self, prompt: str) -> str:
        return await request_text(prompt)

    async def read_choice(self, prompt: str, *, allowed: set[str]) -> str:
        answer = (await request_text(prompt)).strip().lower()
        return answer if answer in allowed else ""


class _CommandCompleter(Completer):
    def __init__(self) -> None:
        self.registry: CommandRegistry | None = None

    def get_completions(self, document: Document, complete_event: Any) -> Iterable[Completion]:
        registry = self.registry
        text = document.text_before_cursor
        if registry is None or not text.startswith("/") or any(char.isspace() for char in text):
            return
        for spec in registry.suggestions(text):
            yield Completion(
                spec.name,
                start_position=-len(text),
                display_meta=spec.description,
            )


@dataclass(frozen=True)
class _InputResult:
    text: str = ""
    cancelled: bool = False
    eof: bool = False


class _TerminalStream:
    def __init__(self, terminal: TerminalApplication, fallback: TextIO) -> None:
        self.terminal = terminal
        self.fallback = fallback
        self.encoding = getattr(fallback, "encoding", None) or "utf-8"

    def write(self, text: str) -> int:
        if text:
            self.terminal.emit(text)
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return self.fallback.fileno()


class TerminalApplication:
    """Single owner of terminal rendering and interactive input."""

    def __init__(self, *, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.is_tty = bool(self.stdin.isatty() and self.stdout.isatty())
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app_task: asyncio.Task[Any] | None = None
        self._context_token: Any = None
        self._original_stdout: TextIO | None = None
        self._original_stderr: TextIO | None = None
        self._output = ""
        self._output_lock = RLock()
        self._input_queue: asyncio.Queue[_InputResult] = asyncio.Queue()
        self._input_enabled = False
        self._prompt_header = "User"
        self._status = ""
        self._cancel_event: asyncio.Event | None = None
        self._selection_options: list[str] = []
        self._selection_index = 0
        self._completer = _CommandCompleter()
        self._application: Application[Any] | None = None
        self._input_buffer: Buffer | None = None
        self._output_window: Window | None = None
        if self.is_tty:
            self._build_application()

    async def start(self) -> None:
        self._context_token = _CURRENT_TERMINAL.set(self)
        if not self.is_tty:
            return
        self._loop = asyncio.get_running_loop()
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        if self._application is None:
            raise RuntimeError("terminal application was not initialized")
        self._app_task = asyncio.create_task(self._application.run_async())
        await asyncio.sleep(0)
        sys.stdout = _TerminalStream(self, self.stdout)  # type: ignore[assignment]
        sys.stderr = _TerminalStream(self, self.stdout)  # type: ignore[assignment]

    async def close(self) -> None:
        if self._original_stdout is not None:
            sys.stdout = self._original_stdout
        if self._original_stderr is not None:
            sys.stderr = self._original_stderr
        if self._application is not None and self._application.is_running:
            self._application.exit()
        if self._app_task is not None:
            await asyncio.gather(self._app_task, return_exceptions=True)
        if self._context_token is not None:
            _CURRENT_TERMINAL.reset(self._context_token)
            self._context_token = None

    def emit(self, text: str) -> None:
        if not text:
            return
        if not self.is_tty:
            self.stdout.write(text)
            self.stdout.flush()
            return
        loop = self._loop
        if loop is None:
            with self._output_lock:
                self._append_output(text)
            return
        loop.call_soon_threadsafe(self._apply_output, text)

    def print(self, text: str = "", *, end: str = "\n") -> None:
        self.emit(text + end)

    def clear_output(self) -> None:
        if not self.is_tty:
            return
        loop = self._loop
        if loop is None:
            with self._output_lock:
                self._output = ""
            return
        loop.call_soon_threadsafe(self._apply_clear)

    def set_status(self, text: str) -> None:
        self._status = text
        self._invalidate()

    def bind_cancel_event(self, event: asyncio.Event | None) -> None:
        self._cancel_event = event

    async def read_prompt(
        self,
        command_registry: CommandRegistry | None = None,
        *,
        prompt_header: str = "User",
        preserve_selection: bool = False,
    ) -> str:
        if not self.is_tty:
            if prompt_header:
                self.stdout.write(f"{prompt_header}: ")
                self.stdout.flush()
            line = await asyncio.to_thread(self.stdin.readline)
            if line == "":
                raise EOFError
            return line.rstrip("\r\n")
        self._completer.registry = command_registry
        if not preserve_selection:
            self._selection_options = []
            self._selection_index = 0
        self._prompt_header = prompt_header
        self._input_enabled = True
        self._status = ""
        if self._input_buffer is not None:
            self._input_buffer.reset()
        if self._application is not None:
            self._application.layout.focus(self._input_buffer)
            self._application.invalidate()
        result = await self._input_queue.get()
        self._input_enabled = False
        self._invalidate()
        if result.cancelled:
            raise TerminalCancelled()
        if result.eof:
            raise EOFError
        return result.text

    async def ask(self, prompt: str) -> str:
        return await self.read_prompt(None, prompt_header=prompt.rstrip("：: "))

    async def read_text(self, prompt: str) -> str:
        return await self.ask(prompt)

    async def read_choice(self, prompt: str, *, allowed: set[str]) -> str:
        answer = (await self.ask(prompt)).strip().lower()
        return answer if answer in allowed else ""

    async def select(self, prompt: str, options: list[str]) -> int | None:
        if not options:
            return None
        self.emit(prompt.rstrip() + "\n")
        for index, option in enumerate(options, start=1):
            self.emit(f"  {index}. {option}\n")
        self._selection_options = list(options)
        self._selection_index = 0
        try:
            raw = await self.read_prompt(
                None,
                prompt_header="使用 ↑/↓ 选择，Enter 确认，Ctrl+C 取消",
                preserve_selection=True,
            )
        except (TerminalCancelled, EOFError):
            return None
        finally:
            options_before_clear = self._selection_options
            self._selection_options = []
            self._selection_index = 0
            self._invalidate()
        if raw.startswith("__selection__:"):
            return int(raw.split(":", 1)[1])
        try:
            selected = int(raw) - 1
        except ValueError:
            return None
        return selected if 0 <= selected < len(options_before_clear) else None

    def _build_application(self) -> None:
        key_bindings = KeyBindings()
        self._input_buffer = Buffer(
            multiline=True,
            completer=self._completer,
            complete_while_typing=True,
        )
        input_control = BufferControl(buffer=self._input_buffer)
        output_control = FormattedTextControl(self._formatted_output, focusable=False)
        self._output_window = Window(
            output_control,
            wrap_lines=True,
            always_hide_cursor=True,
            allow_scroll_beyond_bottom=False,
        )
        header_window = Window(
            FormattedTextControl(self._formatted_header),
            height=1,
            style="class:input.header",
        )
        input_window = Window(
            input_control,
            height=Dimension(min=3, max=8, preferred=3),
            wrap_lines=True,
            style="class:input.body",
        )
        status_window = Window(
            FormattedTextControl(self._formatted_status),
            height=1,
            style="class:status",
        )
        body = HSplit(
            [
                self._output_window,
                Window(height=1, char="─", style="class:separator"),
                header_window,
                input_window,
                status_window,
            ]
        )
        root = FloatContainer(
            content=body,
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=8, scroll_offset=1),
                )
            ],
        )

        @key_bindings.add("enter")
        def submit(event: Any) -> None:
            if not self._input_enabled:
                return
            if self._selection_options:
                text = f"__selection__:{self._selection_index}"
            else:
                text = event.current_buffer.text
            event.current_buffer.reset()
            if not self._selection_options:
                self._append_output(f"User:\n{text}\n")
            self._input_queue.put_nowait(_InputResult(text=text))

        @key_bindings.add("escape", "enter")
        def insert_newline(event: Any) -> None:
            if self._input_enabled:
                event.current_buffer.insert_text("\n")

        @key_bindings.add("c-c")
        def cancel(event: Any) -> None:
            if self._input_enabled:
                event.current_buffer.reset()
                self._input_queue.put_nowait(_InputResult(cancelled=True))
                return
            if self._cancel_event is not None:
                self._cancel_event.set()
                self._append_output("已请求中断当前操作。\n")
                event.app.invalidate()

        @key_bindings.add("up")
        def select_previous(event: Any) -> None:
            if self._input_enabled and self._selection_options:
                self._selection_index = (self._selection_index - 1) % len(self._selection_options)
                event.app.invalidate()

        @key_bindings.add("down")
        def select_next(event: Any) -> None:
            if self._input_enabled and self._selection_options:
                self._selection_index = (self._selection_index + 1) % len(self._selection_options)
                event.app.invalidate()

        @key_bindings.add("c-d")
        def eof(event: Any) -> None:
            if self._input_enabled and not event.current_buffer.text:
                self._input_queue.put_nowait(_InputResult(eof=True))

        style = Style.from_dict(
            {
                "input.header": "bg:#d0d0d0 #101010 bold",
                "input.body": "bg:#d0d0d0 #101010",
                "status": "#808080",
                "separator": "#606060",
                "completion-menu.completion": "bg:#202020 #d0d0d0",
                "completion-menu.completion.current": "bg:#3a3a3a #ffffff",
                "completion-menu.meta.completion": "bg:#202020 #888888",
                "completion-menu.meta.completion.current": "bg:#3a3a3a #d0d0d0",
            }
        )
        self._application = Application(
            layout=Layout(root, focused_element=self._input_buffer),
            key_bindings=key_bindings,
            full_screen=True,
            mouse_support=False,
            style=style,
            refresh_interval=None,
            min_redraw_interval=0.03,
            input=create_input(stdin=self.stdin),
            output=create_output(stdout=self.stdout),
        )

    def _apply_output(self, text: str) -> None:
        with self._output_lock:
            self._append_output(text)
        if self._output_window is not None:
            self._output_window.vertical_scroll = 10**9
        self._invalidate()

    def _apply_clear(self) -> None:
        with self._output_lock:
            self._output = ""
        self._invalidate()

    def _append_output(self, text: str) -> None:
        self._output += text
        if len(self._output) > MAX_OUTPUT_CHARS:
            self._output = self._output[-MAX_OUTPUT_CHARS:]

    def _formatted_output(self) -> Any:
        with self._output_lock:
            value = self._output
        try:
            return ANSI(value)
        except Exception:
            return ANSI(ANSI_ESCAPE_RE.sub("", value))

    def _formatted_header(self) -> FormattedText:
        marker = "" if self._input_enabled else " (busy)"
        return FormattedText([("", f" {self._prompt_header}{marker}")])

    def _formatted_status(self) -> FormattedText:
        if self._selection_options:
            selected = self._selection_options[self._selection_index]
            return FormattedText([("", f" [{self._selection_index + 1}/{len(self._selection_options)}] {selected}")])
        return FormattedText([("", f" {self._status}")])

    def _invalidate(self) -> None:
        application = self._application
        if application is not None and application.is_running:
            application.invalidate()


def current_terminal() -> TerminalApplication | None:
    return _CURRENT_TERMINAL.get()


async def request_text(prompt: str) -> str:
    terminal = current_terminal()
    if terminal is not None:
        return await terminal.read_text(prompt)
    return await asyncio.to_thread(input, prompt)


async def request_selection(prompt: str, options: list[str]) -> int | None:
    terminal = current_terminal()
    if terminal is not None:
        return await terminal.select(prompt, options)
    if not options:
        return None
    print(prompt, flush=True)
    for index, option in enumerate(options, start=1):
        print(f"  {index}. {option}", flush=True)
    try:
        answer = (await asyncio.to_thread(input, "请输入序号，或直接回车取消：")).strip()
        selected = int(answer) - 1
    except (EOFError, KeyboardInterrupt, ValueError):
        return None
    return selected if 0 <= selected < len(options) else None


async def request_confirmation(prompt: str) -> bool:
    try:
        answer = (await request_text(prompt)).strip().lower()
    except (TerminalCancelled, EOFError, KeyboardInterrupt):
        return False
    return answer in {"y", "yes"}
