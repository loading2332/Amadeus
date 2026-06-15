from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar, cast

E = TypeVar("E")
EventHandler = Callable[[E], Awaitable[E | None] | E | None]


@dataclass(frozen=True)
class ToolCallStarted:
    """Emitted before a tool call is executed within the reasoner loop."""
    session_key: str
    iteration: int
    call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolCallCompleted:
    """Emitted after a tool call has been executed within the reasoner loop."""
    session_key: str
    iteration: int
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    final_arguments: dict[str, Any]
    status: str
    result_preview: str


@dataclass(frozen=True)
class TurnCommitted:
    session_key: str
    input_message: str
    assistant_response: str
    persisted_user_message: str | None = None
    timestamp: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[object], list[EventHandler[object]]] = {}

    def on(self, event_type: type[E], handler: EventHandler[E]) -> None:
        handlers = self._handlers.setdefault(cast(type[object], event_type), [])
        handlers.append(cast(EventHandler[object], handler))

    async def emit(self, event: E) -> E:
        current = event
        for raw_handler in self._handlers.get(cast(type[object], type(event)), []):
            handler = cast(EventHandler[E], raw_handler)
            result = handler(current)
            if inspect.isawaitable(result):
                result = await result
            if result is not None:
                current = result
        return current
