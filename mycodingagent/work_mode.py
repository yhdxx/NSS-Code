from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum


class WorkMode(StrEnum):
    GENERAL = "general"
    CODE = "code"

    @classmethod
    def parse(cls, value: str | WorkMode) -> WorkMode:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValueError("work mode must be general or code") from exc


class WorkModeManager:
    """Own the active mode; persistence is an injected side effect."""

    def __init__(
        self,
        initial: str | WorkMode = WorkMode.GENERAL,
        *,
        persist: Callable[[str], object] | None = None,
    ) -> None:
        self._current = WorkMode.parse(initial)
        self._persist = persist

    @property
    def current(self) -> WorkMode:
        return self._current

    def commit(self, mode: str | WorkMode) -> WorkMode:
        selected = WorkMode.parse(mode)
        if selected == self._current:
            return selected
        if self._persist is not None:
            self._persist(selected.value)
        self._current = selected
        return selected

    def load(self, mode: str | WorkMode) -> WorkMode:
        self._current = WorkMode.parse(mode)
        return self._current
