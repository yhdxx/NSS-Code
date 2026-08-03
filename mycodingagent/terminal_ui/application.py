from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol, TextIO

from prompt_toolkit import Application
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.input.defaults import create_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, Float, FloatContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.utils import get_cwidth

from mycodingagent.commands import CommandRegistry
from mycodingagent.terminal_ui.message_queue import FollowUpSignal, MessageQueue
from mycodingagent.terminal_ui.theme import (
    ACTIVE_USER_ANSI,
    RESET_ANSI,
    prompt_toolkit_style,
)


MAX_OUTPUT_CHARS = 500_000
QUEUE_PREVIEW_TITLE = (
    "Messages to be submitted after next tool call (press esc to interrupt and send immediately)"
)
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
        self._buffer = ""
        self._lock = RLock()

    def write(self, text: str) -> int:
        with self._lock:
            self._buffer += text
            if "\n" in self._buffer:
                complete, self._buffer = self._buffer.rsplit("\n", 1)
                self.terminal.emit(complete + "\n")
        return len(text)

    def flush(self) -> None:
        with self._lock:
            if self._buffer:
                self.terminal.emit(self._buffer)
                self._buffer = ""

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
        self._stdout_stream: _TerminalStream | None = None
        self._stderr_stream: _TerminalStream | None = None
        self._output = ""
        self._output_lock = RLock()
        self._message_queue = MessageQueue()
        self._response_queue: asyncio.Queue[_InputResult] = asyncio.Queue()
        self._render_queue: asyncio.Queue[str] = asyncio.Queue()
        self._ready = False
        self._modal_input = False
        self._agent_busy = False
        self._prompt_header = "User"
        self._status = ""
        self._activity_status = ""
        self._cancel_event: asyncio.Event | None = None
        self._selection_options: list[str] = []
        self._selection_index = 0
        self._completer = _CommandCompleter()
        self._application: Application[Any] | None = None
        self._input_buffer: Buffer | None = None
        self._loading_control: FormattedTextControl | None = None
        self._output_task: asyncio.Task[None] | None = None
        self._prompt_output: Any = None
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
        self._app_task = asyncio.create_task(
            self._application.run_async(pre_run=self._start_output_consumer)
        )
        await asyncio.sleep(0)
        self._stdout_stream = _TerminalStream(self, self.stdout)
        self._stderr_stream = _TerminalStream(self, self.stdout)
        sys.stdout = self._stdout_stream  # type: ignore[assignment]
        sys.stderr = self._stderr_stream  # type: ignore[assignment]

    async def close(self) -> None:
        if self._stdout_stream is not None:
            self._stdout_stream.flush()
        if self._stderr_stream is not None:
            self._stderr_stream.flush()
        if self._original_stdout is not None:
            sys.stdout = self._original_stdout
        if self._original_stderr is not None:
            sys.stderr = self._original_stderr
        if self.is_tty:
            await self._render_queue.join()
        if self._application is not None and self._application.is_running:
            self._application.exit()
        if self._app_task is not None:
            await asyncio.gather(self._app_task, return_exceptions=True)
        if self._output_task is not None:
            self._output_task.cancel()
            await asyncio.gather(self._output_task, return_exceptions=True)
            self._output_task = None
        self._stdout_stream = None
        self._stderr_stream = None
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
            self.stdout.write(text)
            self.stdout.flush()
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is loop:
            self._enqueue_output(text)
        else:
            loop.call_soon_threadsafe(self._enqueue_output, text)

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
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is loop:
            self._apply_clear()
        else:
            loop.call_soon_threadsafe(self._apply_clear)

    def set_status(self, text: str) -> None:
        self._activity_status = text
        self._refresh_status()

    def mark_ready(self) -> None:
        """Expose the normal composer after startup initialization has completed."""
        self._ready = True
        self._refresh_status()
        self._focus_input()

    def notify_agent_output(self) -> None:
        """Reveal queued follow-ups only after later Agent output is visible."""
        if self._message_queue.reveal_waiting():
            self._refresh_status()

    def bind_cancel_event(self, event: asyncio.Event | None) -> None:
        self._cancel_event = event
        self._agent_busy = event is not None
        self._refresh_status()

    @property
    def follow_up_signal(self) -> FollowUpSignal:
        return self._message_queue

    async def read_message(
        self,
        command_registry: CommandRegistry | None = None,
        *,
        prompt_header: str = "User",
    ) -> str:
        if not self.is_tty:
            return await self.read_prompt(command_registry, prompt_header=prompt_header)
        self._modal_input = False
        self._completer.registry = command_registry
        self._prompt_header = prompt_header
        self._refresh_status()
        self._focus_input()
        result = await self._message_queue.get()
        if result.text and not result.committed:
            self._commit_user_message(result.text)
            result.committed = True
        self._refresh_status()
        if result.cancelled:
            raise TerminalCancelled()
        if result.eof:
            raise EOFError
        return result.text

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
        self._modal_input = True
        self._completer.registry = command_registry
        if not preserve_selection:
            self._selection_options = []
            self._selection_index = 0
        self._prompt_header = prompt_header
        self._status = ""
        draft = ""
        if self._input_buffer is not None:
            draft = self._input_buffer.text
            self._input_buffer.reset()
        self._focus_input()
        try:
            result = await self._response_queue.get()
        finally:
            self._modal_input = False
            if self._input_buffer is not None and draft:
                self._input_buffer.set_document(Document(draft, len(draft)))
            self._refresh_status()
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
        input_window = Window(
            input_control,
            height=self._input_height,
            wrap_lines=True,
            style="class:input.body",
            get_line_prefix=self._input_prefix,
        )
        queue_preview = ConditionalContainer(
            Window(
                FormattedTextControl(self._formatted_queue_preview),
                height=self._queue_preview_height,
                wrap_lines=True,
                style="class:queue.item",
            ),
            filter=Condition(lambda: bool(self._message_queue.visible_messages)),
        )
        status_window = ConditionalContainer(
            Window(
                FormattedTextControl(self._formatted_status),
                height=1,
                style="class:status",
            ),
            filter=Condition(self._has_status),
        )
        composer = ConditionalContainer(
            HSplit(
                [
                    queue_preview,
                    input_window,
                    status_window,
                ]
            ),
            filter=Condition(lambda: self._ready or self._modal_input),
        )
        self._loading_control = FormattedTextControl("", focusable=True)
        loading = ConditionalContainer(
            Window(self._loading_control, height=0, style="class:loading"),
            filter=Condition(lambda: not (self._ready or self._modal_input)),
        )
        body = HSplit(
            [
                loading,
                composer,
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
            if not self._ready and not self._modal_input:
                return
            if self._selection_options:
                text = f"__selection__:{self._selection_index}"
            else:
                text = event.current_buffer.text
                if not text.strip():
                    return
            event.current_buffer.reset()
            if self._modal_input:
                self._response_queue.put_nowait(_InputResult(text=text))
            else:
                waiting = self._agent_busy
                item = self._message_queue.submit(text, waiting=waiting)
                if not waiting:
                    self._commit_user_message(text)
                    item.committed = True
                self._refresh_status()

        @key_bindings.add("c-j")
        def insert_newline(event: Any) -> None:
            if not self._ready and not self._modal_input:
                return
            event.current_buffer.insert_text("\n")

        @key_bindings.add("escape", eager=True)
        def interrupt(event: Any) -> None:
            if self._modal_input:
                event.current_buffer.reset()
                self._response_queue.put_nowait(_InputResult(cancelled=True))
                return
            if self._agent_busy and self._cancel_event is not None:
                self._cancel_event.set()
                if not self._message_queue.has_waiting:
                    self.emit("已请求中断当前任务。\n")
                else:
                    self.emit("已请求中断当前任务，将立即处理排队消息。\n")
                self._refresh_status()

        @key_bindings.add("c-c")
        def cancel(event: Any) -> None:
            if self._modal_input:
                event.current_buffer.reset()
                self._response_queue.put_nowait(_InputResult(cancelled=True))
                return
            if self._cancel_event is not None:
                self._cancel_event.set()
                self.emit("已请求中断当前任务。\n")
                return
            if self._ready:
                self._message_queue.submit_cancelled()

        @key_bindings.add("up")
        def select_previous(event: Any) -> None:
            if self._selection_options:
                self._selection_index = (self._selection_index - 1) % len(self._selection_options)
                event.app.invalidate()

        @key_bindings.add("down")
        def select_next(event: Any) -> None:
            if self._selection_options:
                self._selection_index = (self._selection_index + 1) % len(self._selection_options)
                event.app.invalidate()

        @key_bindings.add("c-d")
        def eof(event: Any) -> None:
            if event.current_buffer.text:
                return
            if self._modal_input:
                self._response_queue.put_nowait(_InputResult(eof=True))
            elif self._ready:
                self._message_queue.submit_eof()

        style = prompt_toolkit_style()
        self._prompt_output = create_output(stdout=self.stdout)
        self._application = Application(
            layout=Layout(root, focused_element=self._loading_control),
            key_bindings=key_bindings,
            full_screen=False,
            erase_when_done=True,
            mouse_support=False,
            style=style,
            color_depth=ColorDepth.TRUE_COLOR,
            refresh_interval=None,
            min_redraw_interval=0.03,
            input=create_input(stdin=self.stdin),
            output=self._prompt_output,
        )

    def _start_output_consumer(self) -> None:
        self._output_task = asyncio.create_task(self._consume_output())

    async def _consume_output(self) -> None:
        while True:
            text = await self._render_queue.get()
            try:
                await run_in_terminal(lambda: self._write_rendered(text))
            finally:
                self._render_queue.task_done()

    def _write_rendered(self, text: str) -> None:
        if self._prompt_output is None:
            return
        self._prompt_output.write_raw(text)
        self._prompt_output.flush()

    def _enqueue_output(self, text: str) -> None:
        with self._output_lock:
            self._append_output(text)
        self._render_queue.put_nowait(text)

    def _apply_clear(self) -> None:
        with self._output_lock:
            self._output = ""
        self._render_queue.put_nowait("\x1b[2J\x1b[H")

    def _append_output(self, text: str) -> None:
        self._output += text
        if len(self._output) > MAX_OUTPUT_CHARS:
            self._output = self._output[-MAX_OUTPUT_CHARS:]

    def _commit_user_message(self, text: str) -> None:
        with self._output_lock:
            self._append_output(f"User:\n{text}\n")
        lines = [" User", *(text.splitlines() or [""])]
        block = "".join(
            f"{ACTIVE_USER_ANSI}{line}\x1b[K{RESET_ANSI}\n"
            for line in lines
        )
        self._render_queue.put_nowait(block)

    def _input_prefix(self, line_number: int, wrap_count: int) -> FormattedText:
        if wrap_count:
            return FormattedText([("class:input.prefix", "  ")])
        if self._modal_input:
            return FormattedText([("class:input.prefix", f" {self._prompt_header} › ")])
        return FormattedText([("class:input.prefix", " › ")])

    def _input_height(self) -> Dimension:
        if self._input_buffer is None:
            return Dimension.exact(1)
        columns = 80
        if self._prompt_output is not None:
            columns = max(10, self._prompt_output.get_size().columns)
        prefix_width = get_cwidth(self._prompt_header) + 4 if self._modal_input else 3
        usable_width = max(1, columns - prefix_width)
        visual_lines = 0
        for line in self._input_buffer.document.lines:
            width = max(1, get_cwidth(line))
            visual_lines += max(1, (width + usable_width - 1) // usable_width)
        return Dimension.exact(min(6, max(1, visual_lines)))

    def _queue_preview_height(self) -> int:
        columns = 80
        if self._prompt_output is not None:
            columns = max(10, self._prompt_output.get_size().columns)
        title_lines = max(1, (get_cwidth(QUEUE_PREVIEW_TITLE) + columns - 1) // columns)
        return title_lines + len(self._message_queue.visible_messages)

    def _formatted_queue_preview(self) -> FormattedText:
        fragments: list[tuple[str, str]] = [
            ("class:queue.title", QUEUE_PREVIEW_TITLE + "\n")
        ]
        for index, message in enumerate(self._message_queue.visible_messages):
            suffix = "\n" if index < len(self._message_queue.visible_messages) - 1 else ""
            fragments.append(("class:queue.item", f"└ {self._truncate_queue_message(message)}{suffix}"))
        return FormattedText(fragments)

    def _truncate_queue_message(self, text: str) -> str:
        normalized = " ".join(text.split())
        columns = 80
        if self._prompt_output is not None:
            columns = max(10, self._prompt_output.get_size().columns)
        available = max(4, columns - 2)
        if get_cwidth(normalized) <= available:
            return normalized
        target = max(1, available - 3)
        result = ""
        for char in normalized:
            if get_cwidth(result + char) > target:
                break
            result += char
        return result + "..."

    def _formatted_status(self) -> FormattedText:
        if self._selection_options:
            selected = self._selection_options[self._selection_index]
            return FormattedText([("", f" [{self._selection_index + 1}/{len(self._selection_options)}] {selected}")])
        return FormattedText([("", f" {self._status}")])

    def _has_status(self) -> bool:
        return bool(self._selection_options or self._status)

    def _focus_input(self) -> None:
        if self._application is not None:
            if self._ready or self._modal_input:
                self._application.layout.focus(self._input_buffer)
            elif self._loading_control is not None:
                self._application.layout.focus(self._loading_control)
            self._application.invalidate()

    def _refresh_status(self) -> None:
        queued = len(self._message_queue)
        if self._modal_input:
            return
        if self._agent_busy and queued:
            queue_status = (
                f"已排队 {queued} 条；Esc 立即中断，否则在下一次工具调用结束后处理"
            )
        elif self._agent_busy:
            queue_status = "Agent 工作中；可继续输入消息"
        elif queued:
            queue_status = f"已排队 {queued} 条消息"
        else:
            queue_status = ""
        self._status = " | ".join(
            part for part in (self._activity_status, queue_status) if part
        )
        self._invalidate()

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
