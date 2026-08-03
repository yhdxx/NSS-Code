from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class FollowUpSignal(Protocol):
    def is_set(self) -> bool: ...


class MessageState(str, Enum):
    QUEUED_HIDDEN = "queued_hidden"
    QUEUED_VISIBLE = "queued_visible"
    ACTIVE = "active"


@dataclass
class QueuedInput:
    text: str = ""
    state: MessageState = MessageState.ACTIVE
    committed: bool = False
    cancelled: bool = False
    eof: bool = False


class MessageQueue:
    """FIFO user input queue with explicit display and handoff states."""

    def __init__(self) -> None:
        self._items: deque[QueuedInput] = deque()
        self._available = asyncio.Event()
        self._follow_up_requested = asyncio.Event()

    def is_set(self) -> bool:
        return self._follow_up_requested.is_set()

    def submit(self, text: str, *, waiting: bool) -> QueuedInput:
        item = QueuedInput(
            text=text,
            state=MessageState.QUEUED_HIDDEN if waiting else MessageState.ACTIVE,
        )
        self._items.append(item)
        self._available.set()
        if waiting:
            self._follow_up_requested.set()
        return item

    def submit_cancelled(self) -> None:
        self._items.append(QueuedInput(cancelled=True))
        self._available.set()

    def submit_eof(self) -> None:
        self._items.append(QueuedInput(eof=True))
        self._available.set()

    async def get(self) -> QueuedInput:
        while not self._items:
            self._available.clear()
            await self._available.wait()
        item = self._items.popleft()
        item.state = MessageState.ACTIVE
        if not self._items:
            self._available.clear()
        if not self.has_waiting:
            self._follow_up_requested.clear()
        return item

    def reveal_waiting(self) -> bool:
        changed = False
        for item in self._items:
            if item.state is MessageState.QUEUED_HIDDEN:
                item.state = MessageState.QUEUED_VISIBLE
                changed = True
        return changed

    @property
    def visible_messages(self) -> tuple[str, ...]:
        return tuple(
            item.text
            for item in self._items
            if item.state is MessageState.QUEUED_VISIBLE and item.text
        )

    @property
    def has_waiting(self) -> bool:
        return any(
            item.state in {MessageState.QUEUED_HIDDEN, MessageState.QUEUED_VISIBLE}
            for item in self._items
        )

    def __len__(self) -> int:
        return len(self._items)
