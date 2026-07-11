from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from amadeus.session.identity import SessionRef

E = TypeVar("E")
EventHandler = Callable[[E], Awaitable[E | None] | E | None]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _HandlerRegistration:
    handler: EventHandler[object]
    priority: int
    order: int


@dataclass(frozen=True)
class ToolCallStarted:
    """Emitted before a tool call is executed within the reasoner loop."""

    session: SessionRef
    iteration: int
    call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolCallCompleted:
    """Emitted after a tool call has been executed within the reasoner loop."""

    session: SessionRef
    iteration: int
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    final_arguments: dict[str, Any]
    status: str
    result_preview: str


@dataclass(frozen=True)
class TurnCommitted:
    session: SessionRef
    input_message: str
    assistant_response: str
    persisted_user_message: str | None = None
    timestamp: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[object], list[_HandlerRegistration]] = {}
        self._next_order = 0

    def on(
        self,
        event_type: type[E],
        handler: EventHandler[E],
        *,
        priority: int = 0,
    ) -> None:
        handlers = self._handlers.setdefault(cast(type[object], event_type), [])
        handlers.append(
            _HandlerRegistration(
                handler=cast(EventHandler[object], handler),
                priority=priority,
                order=self._next_order,
            )
        )
        self._next_order += 1
        handlers.sort(key=lambda registration: (-registration.priority, registration.order))

    def off(self, event_type: type[E], handler: EventHandler[E]) -> None:
        raw_event_type = cast(type[object], event_type)
        registrations = self._handlers.get(raw_event_type)
        if registrations is None:
            return
        registrations[:] = [
            registration
            for registration in registrations
            if registration.handler is not handler
        ]
        if not registrations:
            del self._handlers[raw_event_type]

    async def emit(self, event: E) -> E:
        current = event
        registrations = list(
            self._handlers.get(cast(type[object], type(event)), [])
        )
        for registration in registrations:
            handler = cast(EventHandler[E], registration.handler)
            result = handler(current)
            if inspect.isawaitable(result):
                result = await result
            if result is not None:
                current = result
        return current

    async def fanout(self, event: object) -> None:
        registrations = list(self._handlers.get(type(event), []))
        if not registrations:
            return
        await asyncio.gather(
            *(
                self._run_observer(event, registration.handler)
                for registration in registrations
            )
        )

    async def _run_observer(
        self,
        event: object,
        handler: EventHandler[object],
    ) -> None:
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("observer error for %s", type(event).__name__)
