from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from amadeus.context import Message, RuntimeContext
from amadeus.events import EventBus
from amadeus.session.identity import SessionRef


@dataclass
class BeforeTurnContext:
    session: SessionRef
    user_message: str
    history: list[Message]
    retrieved_memory: str | None
    memory_trace: dict[str, Any] = field(default_factory=dict)
    active_skills: list[str] = field(default_factory=list)
    runtime_metadata: dict[str, str] = field(default_factory=dict)
    extra_hints: list[str] = field(default_factory=list)
    abort_reply: str | None = None

    @property
    def session_key(self) -> str:
        return self.session.session_key


@dataclass
class BeforeReasoningContext:
    session: SessionRef
    user_message: str
    history: list[Message]
    retrieved_memory: str | None
    memory_trace: dict[str, Any] = field(default_factory=dict)
    active_skills: list[str] = field(default_factory=list)
    runtime_metadata: dict[str, str] = field(default_factory=dict)
    extra_hints: list[str] = field(default_factory=list)
    abort_reply: str | None = None

    @property
    def session_key(self) -> str:
        return self.session.session_key


@dataclass
class BeforeStepContext:
    session: SessionRef
    iteration: int
    messages: list[dict[str, Any]]
    tool_schemas: list[dict[str, Any]] | None
    extra_hints: list[str] = field(default_factory=list)
    early_stop_reply: str | None = None

    @property
    def session_key(self) -> str:
        return self.session.session_key


@dataclass
class AfterStepContext:
    session: SessionRef
    iteration: int
    messages: list[dict[str, Any]]
    tool_chain: list[dict[str, Any]]
    telemetry: dict[str, Any] = field(default_factory=dict)
    early_stop_reply: str | None = None

    @property
    def session_key(self) -> str:
        return self.session.session_key


@dataclass
class AfterReasoningContext:
    session: SessionRef
    user_message: str
    assistant_content: str
    tool_chain: list[dict[str, Any]]
    context_retry: dict[str, Any]
    extra: dict[str, Any] = field(default_factory=dict)
    assistant_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def session_key(self) -> str:
        return self.session.session_key


@dataclass
class PromptRenderContext:
    session: SessionRef
    attempt_index: int
    attempt_name: str
    runtime_context: RuntimeContext

    @property
    def session_key(self) -> str:
        return self.session.session_key


@dataclass(frozen=True)
class AfterTurnContext:
    session: SessionRef
    user_message_id: str
    assistant_message_id: str
    assistant_response: str
    tool_chain: tuple[dict[str, Any], ...]
    context_retry: dict[str, Any]
    memory_trace: dict[str, Any] = field(default_factory=dict)

    @property
    def session_key(self) -> str:
        return self.session.session_key


class TurnLifecycle:
    """Typed facade over the turn lifecycle's two Gate seams and one Tap seam."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def on_before_turn(self, handler: Callable[[BeforeTurnContext], Any]) -> None:
        self._bus.on(BeforeTurnContext, handler)

    def on_prompt_render(self, handler: Callable[[PromptRenderContext], Any]) -> None:
        self._bus.on(PromptRenderContext, handler)

    def on_after_turn(self, handler: Callable[[AfterTurnContext], Any]) -> None:
        self._bus.on(AfterTurnContext, handler)

    async def before_turn(self, context: BeforeTurnContext) -> BeforeTurnContext:
        return await self._bus.emit(context)

    async def prompt_render(self, context: PromptRenderContext) -> PromptRenderContext:
        return await self._bus.emit(context)

    async def after_turn(self, context: AfterTurnContext) -> None:
        await self._bus.fanout(context)

    async def before_reasoning(
        self, context: BeforeReasoningContext
    ) -> BeforeReasoningContext:
        return await self._bus.emit(context)

    async def before_step(self, context: BeforeStepContext) -> BeforeStepContext:
        return await self._bus.emit(context)

    async def after_step(self, context: AfterStepContext) -> AfterStepContext:
        return await self._bus.emit(context)

    async def after_reasoning(
        self, context: AfterReasoningContext
    ) -> AfterReasoningContext:
        return await self._bus.emit(context)
