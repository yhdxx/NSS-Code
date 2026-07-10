from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class CommandContext:
    memory_runtime: Any
    skill_runtime: Any
    messages: list[dict]
    file_state_cache: Any = None
    workspace_tracker: Any = None
    multicoding_controller: Any = None


@dataclass
class CommandResult:
    handled: bool = True
    messages: list[dict] | None = None
    should_exit: bool = False


CommandHandler = Callable[[CommandContext, str], Awaitable[CommandResult]]


@dataclass
class CommandSpec:
    name: str
    description: str
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    usage: str = ""
    examples: tuple[str, ...] = ()
    usages: tuple[tuple[str, str], ...] = ()

    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)

    def help_text(self) -> str:
        lines = [f"{self.name} - {self.description}"]
        if self.usages:
            lines.append("用法：")
            lines.extend(f"  {self.name}{usage:<18} {description}" for usage, description in self.usages)
        elif self.usage:
            lines.append(f"用法：{self.name} {self.usage}")
        if self.aliases:
            lines.append("别名：" + "、".join(self.aliases))
        if self.examples:
            lines.append("示例：")
            lines.extend(f"  {example}" for example in self.examples)
        return "\n".join(lines)


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def register(self, spec: CommandSpec) -> None:
        self._commands[spec.name] = spec

    def suggestions(self, buffer: str) -> list[CommandSpec]:
        text = buffer
        if not text.startswith("/") or any(char.isspace() for char in text):
            return []
        if text == "/":
            return list(self._commands.values())
        return [spec for spec in self._commands.values() if spec.name.startswith(text)]

    def exact_command(self, buffer: str) -> CommandSpec | None:
        text = buffer.strip()
        if not text.startswith("/"):
            return None
        command = text.split(maxsplit=1)[0]
        return self._commands.get(command)

    def match(self, text: str) -> tuple[CommandSpec, str] | None:
        stripped = text.strip()
        for spec in self._commands.values():
            for name in spec.names():
                if stripped == name:
                    return spec, ""
                if stripped.startswith(name + " "):
                    return spec, stripped[len(name) :].strip()
        return None

    async def execute(self, text: str, context: CommandContext) -> CommandResult:
        matched = self.match(text)
        if matched is None:
            return CommandResult(handled=False)
        spec, arguments = matched
        return await spec.handler(context, arguments)
