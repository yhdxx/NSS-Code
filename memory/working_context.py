from __future__ import annotations

from dataclasses import dataclass, field

from memory.context_objects import ContextLifecycleState, RecoverableContextObject


@dataclass
class WorkingContext:
    contexts: dict[str, RecoverableContextObject] = field(default_factory=dict)

    def add(self, context: RecoverableContextObject) -> None:
        context.lifecycle_state = ContextLifecycleState.WORKING
        self.contexts[context.id] = context

    def evict(self, context_id: str) -> RecoverableContextObject | None:
        context = self.contexts.pop(context_id, None)
        if context is not None:
            context.lifecycle_state = ContextLifecycleState.EXTERNAL
        return context

    def archive(self, context_id: str) -> RecoverableContextObject | None:
        context = self.contexts.pop(context_id, None)
        if context is not None:
            context.lifecycle_state = ContextLifecycleState.ARCHIVED
        return context

    def metadata(self) -> list[dict]:
        return [context.to_dict() for context in self.contexts.values()]

    def clear(self) -> None:
        for context in self.contexts.values():
            context.lifecycle_state = ContextLifecycleState.EXTERNAL
        self.contexts.clear()
