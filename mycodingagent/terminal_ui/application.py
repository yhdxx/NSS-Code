from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol, TextIO

from prompt_toolkit import Application
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.input.defaults import create_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, VSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.utils import get_cwidth

from mycodingagent.commands import CommandRegistry, CommandSpec
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


@dataclass(frozen=True)
class _InputResult:
    text: str = ""
    cancelled: bool = False
    eof: bool = False


@dataclass(frozen=True)
class _RenderEvent:
    """A queued terminal event with optional rich rendering semantics."""

    plain_text: str
    renderer: Callable[[TextIO], None] | None = None


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
        self._render_queue: asyncio.Queue[str | _RenderEvent] = asyncio.Queue()
        self._ready = False
        self._modal_input = False
        self._agent_busy = False
        self._prompt_header = "User"
        self._status = ""
        self._activity_status = ""
        self._mode_status = ""
        self._network_enabled = True
        self._shift_tab_handler: Callable[[], bool] | None = None
        self._cancel_event: asyncio.Event | None = None
        self._selection_options: list[str] = []
        self._selection_index = 0
        self._selection_toggle_labels: list[str] = []
        self._selection_toggle_states: list[bool] = []
        self._plan_selection_preview = ""
        self._stream_active = False
        self._stream_label = "模型"
        self._stream_text = ""
        self._command_registry: CommandRegistry | None = None
        self._command_suggestions: list[CommandSpec] = []
        self._command_selection_index: int | None = None
        self._dismissed_command_text: str | None = None
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

    def set_interaction_mode(self, mode: str) -> None:
        self._mode_status = "Plan" if mode == "plan" else ""
        self._refresh_status()

    def set_network_enabled(self, enabled: bool) -> None:
        self._network_enabled = bool(enabled)
        self._refresh_status()

    def bind_shift_tab_handler(self, handler: Callable[[], bool] | None) -> None:
        self._shift_tab_handler = handler

    def commit_runtime_user_message(self, text: str) -> None:
        self._commit_user_message(text)

    def begin_assistant_stream(
        self,
        label: str = "模型",
        *,
        markdown_renderer: Callable[..., None] | None = None,
        text_renderer: Callable[..., None] | None = None,
    ) -> "TerminalAssistantStream":
        return TerminalAssistantStream(
            self,
            label,
            markdown_renderer=markdown_renderer,
            text_renderer=text_renderer,
        )

    def _stream_start(self, label: str) -> None:
        self._stream_active = True
        self._stream_label = label
        self._stream_text = ""
        self._invalidate()

    def _stream_delta(self, text: str) -> None:
        if not text:
            return
        self._stream_text += text
        self.notify_agent_output()
        self._invalidate()

    def _stream_finish(
        self,
        text: str,
        *,
        renderer: Callable[..., None] | None = None,
    ) -> None:
        self._stream_active = False
        rendered = text or self._stream_text
        self._stream_text = ""
        if rendered:
            self._enqueue_assistant_render(rendered, renderer=renderer)
        self._invalidate()

    def _stream_abort(
        self,
        text: str,
        *,
        renderer: Callable[..., None] | None = None,
    ) -> None:
        self._stream_active = False
        rendered = text or self._stream_text
        self._stream_text = ""
        if rendered:
            self._enqueue_assistant_render(rendered, renderer=renderer)
        self._invalidate()

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
        self._command_registry = command_registry
        self._refresh_command_suggestions()
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
        self._command_registry = command_registry
        self._refresh_command_suggestions()
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

    async def select_plan(self, preview: str, options: list[str]) -> int | None:
        if not options:
            return None
        if not self.is_tty:
            self.stdout.write(preview.rstrip() + "\n")
            for index, option in enumerate(options, start=1):
                self.stdout.write(f"  {index}. {option}\n")
            self.stdout.flush()
            return await self.select("请选择计划处理方式：", options)
        self._plan_selection_preview = preview.rstrip()
        self._selection_options = list(options)
        self._selection_index = 0
        self._invalidate()
        try:
            raw = await self.read_prompt(
                None,
                prompt_header="使用 ↑/↓ 选择，Enter 确认，Esc 取消",
                preserve_selection=True,
            )
        except (TerminalCancelled, EOFError):
            return None
        finally:
            options_before_clear = self._selection_options
            self._plan_selection_preview = ""
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

    async def select_network_permissions(
        self,
        prompt: str,
        entries: list[tuple[str, bool]],
    ) -> dict[str, bool] | None:
        if not entries:
            return {}
        if not self.is_tty:
            return None
        self._plan_selection_preview = prompt.rstrip()
        self._selection_toggle_labels = [name for name, _enabled in entries]
        self._selection_toggle_states = [enabled for _name, enabled in entries]
        self._refresh_toggle_options()
        self._selection_index = 0
        self._invalidate()
        try:
            await self.read_prompt(
                None,
                prompt_header="使用 ↑/↓ 选择，← 关闭，→ 开启，Enter 保存，Esc 取消",
                preserve_selection=True,
            )
        except (TerminalCancelled, EOFError):
            return None
        finally:
            labels = self._selection_toggle_labels
            states = self._selection_toggle_states
            self._plan_selection_preview = ""
            self._selection_options = []
            self._selection_toggle_labels = []
            self._selection_toggle_states = []
            self._selection_index = 0
            self._invalidate()
        return dict(zip(labels, states, strict=True))

    def _refresh_toggle_options(self) -> None:
        self._selection_options = [
            f"{name:<24} {'网络权限已开启' if enabled else '网络权限已关闭'}"
            for name, enabled in zip(
                self._selection_toggle_labels,
                self._selection_toggle_states,
                strict=True,
            )
        ]

    def _build_application(self) -> None:
        key_bindings = KeyBindings()
        self._input_buffer = Buffer(multiline=True)
        self._input_buffer.on_text_changed += self._refresh_command_suggestions
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
            VSplit(
                [
                    Window(
                        FormattedTextControl(self._formatted_status),
                        height=1,
                        style="class:status",
                    ),
                    Window(
                        FormattedTextControl(self._formatted_network_status),
                        height=1,
                        width=Dimension(min=0, preferred=18, max=18),
                        align=WindowAlign.RIGHT,
                        style="class:status",
                    ),
                ]
            ),
            filter=Condition(self._has_status),
        )
        stream_window = ConditionalContainer(
            Window(
                FormattedTextControl(self._formatted_stream),
                height=self._stream_height,
                wrap_lines=True,
                style="class:stream.text",
            ),
            # Text is emitted incrementally; keeping the cumulative preview
            # window would print old frames into terminal scrollback.
            filter=Condition(lambda: False),
        )
        plan_selection = ConditionalContainer(
            Window(
                FormattedTextControl(
                    self._formatted_plan_selection,
                    get_cursor_position=self._plan_selection_cursor,
                    show_cursor=False,
                ),
                height=self._plan_selection_height,
                wrap_lines=True,
                style="class:plan.preview",
            ),
            filter=Condition(lambda: bool(self._plan_selection_preview)),
        )
        composer = ConditionalContainer(
            HSplit(
                [
                    ConditionalContainer(
                        Window(
                            FormattedTextControl(self._formatted_command_suggestions),
                            height=self._command_suggestions_height,
                            wrap_lines=False,
                            style="class:completion-menu.completion",
                        ),
                        filter=Condition(lambda: bool(self._command_suggestions)),
                    ),
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
                stream_window,
                plan_selection,
                composer,
            ]
        )
        root = body

        @key_bindings.add("enter")
        def submit(event: Any) -> None:
            if not self._ready and not self._modal_input:
                return
            selected_index = self._command_selection_index
            if self._command_suggestions and selected_index is not None:
                command = self._command_suggestions[selected_index].name
                self._dismissed_command_text = command
                self._clear_command_suggestions()
                event.current_buffer.set_document(Document(command, len(command)))
                event.app.invalidate()
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
            if self._command_suggestions:
                self._dismissed_command_text = event.current_buffer.document.text_before_cursor
                self._clear_command_suggestions()
                event.app.invalidate()
                return
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

        @key_bindings.add("s-tab", eager=True)
        def exit_plan_mode(event: Any) -> None:
            if self._selection_options or self._modal_input:
                return
            handler = self._shift_tab_handler
            if handler is not None and handler():
                if self._agent_busy and self._cancel_event is not None:
                    self._cancel_event.set()
                    self.emit("已退出 Plan 模式，并中断当前规划请求。\n")
                else:
                    self.emit("已退出 Plan 模式。\n")

        @key_bindings.add("/")
        def open_command_palette(event: Any) -> None:
            buffer = event.current_buffer
            if buffer.cursor_position == 0 and not buffer.text:
                buffer.insert_text("/")
                event.app.invalidate()
                return
            buffer.insert_text("/")

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
            if self._command_suggestions:
                if self._command_selection_index is None:
                    self._command_selection_index = len(self._command_suggestions) - 1
                else:
                    self._command_selection_index = (
                        self._command_selection_index - 1
                    ) % len(self._command_suggestions)
                event.app.invalidate()
                return
            if self._selection_options:
                self._selection_index = (self._selection_index - 1) % len(self._selection_options)
                event.app.invalidate()

        @key_bindings.add("down")
        def select_next(event: Any) -> None:
            if self._command_suggestions:
                if self._command_selection_index is None:
                    self._command_selection_index = 0
                else:
                    self._command_selection_index = (
                        self._command_selection_index + 1
                    ) % len(self._command_suggestions)
                event.app.invalidate()
                return
            if self._selection_options:
                self._selection_index = (self._selection_index + 1) % len(self._selection_options)
                event.app.invalidate()

        @key_bindings.add("left")
        def disable_selected_network(event: Any) -> None:
            if not self._selection_toggle_states:
                event.current_buffer.cursor_left(count=1)
                return
            self._selection_toggle_states[self._selection_index] = False
            self._refresh_toggle_options()
            event.app.invalidate()

        @key_bindings.add("right")
        def enable_selected_network(event: Any) -> None:
            if not self._selection_toggle_states:
                event.current_buffer.cursor_right(count=1)
                return
            self._selection_toggle_states[self._selection_index] = True
            self._refresh_toggle_options()
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
        # Some terminals and PTY wrappers do not answer cursor-position
        # reports. `run_in_terminal` waits for that response before flushing
        # persistent output, which can otherwise leave model answers stuck in
        # the render queue and echo fragments of the escape sequence.
        if hasattr(self._prompt_output, "enable_cpr"):
            self._prompt_output.enable_cpr = False
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
            event = await self._render_queue.get()
            try:
                if isinstance(event, _RenderEvent) and event.renderer is not None:
                    await run_in_terminal(lambda: event.renderer(self.stdout))
                else:
                    text = event.plain_text if isinstance(event, _RenderEvent) else event
                    await run_in_terminal(lambda: self._write_rendered(text))
            finally:
                self._render_queue.task_done()

    def _write_rendered(self, text: str) -> None:
        # Persistent agent output must bypass prompt_toolkit's redraw buffer.
        # Writing through `Output.write_raw` lets the next redraw erase the
        # answer, which is especially visible for streamed model deltas.
        self.stdout.write(text)
        self.stdout.flush()

    def _enqueue_output(self, text: str) -> None:
        with self._output_lock:
            self._append_output(text)
        self._render_queue.put_nowait(text)

    def _enqueue_assistant_render(
        self,
        text: str,
        *,
        renderer: Callable[..., None] | None,
    ) -> None:
        label = self._stream_label
        plain_text = f"{label}：{text}\n"

        with self._output_lock:
            self._append_output(plain_text)
        if renderer is None:
            if not self.is_tty:
                self.stdout.write(plain_text)
                self.stdout.flush()
                return
            self._render_queue.put_nowait(_RenderEvent(plain_text=plain_text))
            return

        def render(output: TextIO) -> None:
            renderer(text, label=label, file=output)

        if not self.is_tty:
            render(self.stdout)
            return
        self._render_queue.put_nowait(_RenderEvent(plain_text=plain_text, renderer=render))

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

    def _refresh_command_suggestions(self, buffer: Buffer | None = None) -> None:
        buffer = buffer or self._input_buffer
        if buffer is None:
            return
        text = buffer.document.text_before_cursor
        if self._dismissed_command_text is not None:
            if text == self._dismissed_command_text:
                self._clear_command_suggestions()
                self._invalidate()
                return
            self._dismissed_command_text = None
        registry = self._command_registry
        if (
            registry is None
            or not text.startswith("/")
            or any(char.isspace() for char in text)
        ):
            suggestions: list[CommandSpec] = []
        else:
            suggestions = registry.suggestions(text)
        self._command_suggestions = suggestions
        self._command_selection_index = None
        self._invalidate()

    def _clear_command_suggestions(self) -> None:
        self._command_suggestions = []
        self._command_selection_index = None

    def _visible_command_suggestions(self) -> list[tuple[int, CommandSpec]]:
        max_visible = 8
        selected = self._command_selection_index
        if selected is None or selected < max_visible:
            start = 0
        else:
            start = selected - max_visible + 1
        return list(enumerate(self._command_suggestions[start : start + max_visible], start))

    def _command_suggestions_height(self) -> Dimension:
        return Dimension.exact(len(self._visible_command_suggestions()))

    def _formatted_command_suggestions(self) -> FormattedText:
        visible = self._visible_command_suggestions()
        fragments: list[tuple[str, str]] = []
        for row, (index, spec) in enumerate(visible):
            current = index == self._command_selection_index
            command_style = (
                "class:completion-menu.completion.current"
                if current
                else "class:completion-menu.completion"
            )
            meta_style = (
                "class:completion-menu.meta.completion.current"
                if current
                else "class:completion-menu.meta.completion"
            )
            marker = "›" if current else " "
            suffix = "\n" if row < len(visible) - 1 else ""
            fragments.append((command_style, f" {marker} {spec.name}"))
            fragments.append((meta_style, f"  {spec.description}{suffix}"))
        return FormattedText(fragments)

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

    def _stream_height(self) -> Dimension:
        rows = 24
        columns = 80
        if self._prompt_output is not None:
            size = self._prompt_output.get_size()
            rows = max(8, size.rows)
            columns = max(10, size.columns)
        max_rows = max(2, rows - self._input_height().preferred - 4)
        text = f"{self._stream_label}:\n{self._stream_text}"
        visual_lines = sum(
            max(1, (max(1, get_cwidth(line)) + columns - 1) // columns)
            for line in text.splitlines() or [""]
        )
        return Dimension.exact(min(max_rows, visual_lines))

    def _formatted_stream(self) -> FormattedText:
        rows = 24
        columns = 80
        if self._prompt_output is not None:
            size = self._prompt_output.get_size()
            rows = max(8, size.rows)
            columns = max(10, size.columns)
        max_chars = max(columns * max(2, rows - 6), columns)
        text = self._stream_text
        if len(text) > max_chars:
            text = "...\n" + text[-max_chars:]
        return FormattedText(
            [
                ("class:stream.label", f"{self._stream_label}:\n"),
                ("class:stream.text", text),
            ]
        )

    def _plan_selection_height(self) -> Dimension:
        rows = 24
        columns = 80
        if self._prompt_output is not None:
            size = self._prompt_output.get_size()
            rows = max(8, size.rows)
            columns = max(10, size.columns)
        lines = [*self._plan_selection_preview.splitlines(), "", *self._selection_options]
        visual_lines = sum(
            max(1, (max(1, get_cwidth(line)) + columns - 1) // columns)
            for line in lines
        )
        return Dimension.exact(min(max(4, rows - 4), visual_lines + 1))

    def _formatted_plan_selection(self) -> FormattedText:
        fragments: list[tuple[str, str]] = [
            ("class:plan.preview", self._plan_selection_preview + "\n\n")
        ]
        for index, option in enumerate(self._selection_options):
            style = "class:plan.option.current" if index == self._selection_index else "class:plan.option"
            marker = "›" if index == self._selection_index else " "
            fragments.append((style, f" {marker} {option}\n"))
        fragments.append(("class:plan.hint", " 使用 ↑/↓ 选择，Enter 确认，Esc 取消"))
        return FormattedText(fragments)

    def _plan_selection_cursor(self) -> Point:
        preview_lines = len(self._plan_selection_preview.splitlines())
        return Point(x=0, y=preview_lines + 2 + self._selection_index)

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

    def _formatted_network_status(self) -> FormattedText:
        state = "开启" if self._network_enabled else "关闭"
        return FormattedText([("", f"网络访问（{state}） ")])

    def _has_status(self) -> bool:
        return True

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
            part for part in (self._mode_status, self._activity_status, queue_status) if part
        )
        self._invalidate()

    def _invalidate(self) -> None:
        application = self._application
        if application is not None and application.is_running:
            application.invalidate()


class TerminalAssistantStream:
    # Providers use this marker to distinguish the built-in sink, which
    # commits the final answer in _stream_finish, from external sinks.
    commits_final = True

    def __init__(
        self,
        terminal: TerminalApplication,
        label: str,
        *,
        markdown_renderer: Callable[..., None] | None = None,
        text_renderer: Callable[..., None] | None = None,
    ) -> None:
        self._terminal = terminal
        self._label = label
        self._markdown_renderer = markdown_renderer
        self._text_renderer = text_renderer
        self._started = False
        self._finished = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._terminal._stream_start(self._label)

    def delta(self, text: str) -> None:
        if self._finished:
            return
        if not self._started:
            self.start()
        self._terminal._stream_delta(text)

    def finish(self, text: str, *, markdown: bool = True) -> None:
        if self._finished:
            return
        self._finished = True
        if not self._started:
            self.start()
        renderer = self._markdown_renderer if markdown else self._text_renderer
        self._terminal._stream_finish(text, renderer=renderer)

    def abort(self, text: str) -> None:
        if self._finished:
            return
        self._finished = True
        self._terminal._stream_abort(text, renderer=self._text_renderer)

    def reset(self) -> None:
        if self._finished:
            return
        self._started = False
        self._terminal._stream_active = False
        self._terminal._stream_text = ""
        self._terminal._invalidate()


def current_terminal() -> TerminalApplication | None:
    return _CURRENT_TERMINAL.get()


def create_assistant_stream(
    label: str = "模型",
    *,
    markdown_renderer: Callable[..., None] | None = None,
    text_renderer: Callable[..., None] | None = None,
) -> TerminalAssistantStream | None:
    terminal = current_terminal()
    if terminal is None or not terminal.is_tty:
        return None
    return terminal.begin_assistant_stream(
        label,
        markdown_renderer=markdown_renderer,
        text_renderer=text_renderer,
    )


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


async def request_network_permissions(
    prompt: str,
    entries: list[tuple[str, bool]],
) -> dict[str, bool] | None:
    terminal = current_terminal()
    if terminal is not None:
        return await terminal.select_network_permissions(prompt, entries)
    if not entries:
        return {}
    print(prompt, flush=True)
    for name, enabled in entries:
        print(f"  {name:<24} {'网络权限已开启' if enabled else '网络权限已关闭'}", flush=True)
    return None


async def request_plan_selection(preview: str, options: list[str]) -> int | None:
    terminal = current_terminal()
    if terminal is not None:
        return await terminal.select_plan(preview, options)
    return await request_selection(preview, options)


async def request_confirmation(prompt: str) -> bool:
    try:
        answer = (await request_text(prompt)).strip().lower()
    except (TerminalCancelled, EOFError, KeyboardInterrupt):
        return False
    return answer in {"y", "yes"}
