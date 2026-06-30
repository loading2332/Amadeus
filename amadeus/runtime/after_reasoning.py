from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeAlias, cast

from amadeus.context import ContextRenderResult
from amadeus.events import EventBus, TurnCommitted
from amadeus.response_parser import parse_response
from amadeus.runtime.lifecycle import AfterReasoningContext, TurnLifecycle
from amadeus.runtime.phase import PhaseFrame, PhaseModule, topo_sort_modules
from amadeus.session.store import SessionManager

_CTX_SLOT = "reasoning:after_ctx"
_RESULT_SLOT = "reasoning:after_result"
_ASSISTANT_METADATA_PREFIX = "outbound:metadata:"


@dataclass
class AfterReasoningInput:
    session_key: str
    user_message: str
    assistant_content: str
    rendered: ContextRenderResult
    provider_raw: Any
    tool_chain: list[dict[str, Any]]
    context_retry: dict[str, Any]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AfterReasoningResult:
    session_key: str
    user_message_id: str
    assistant_message_id: str
    assistant_response: str
    context: ContextRenderResult
    provider_raw: Any
    tool_chain: list[dict[str, Any]]
    context_retry: dict[str, Any]


@dataclass
class AfterReasoningFrame(PhaseFrame[AfterReasoningInput, AfterReasoningResult]):
    pass


AfterReasoningModules: TypeAlias = list[PhaseModule[AfterReasoningFrame]]


class _BuildAfterReasoningCtxModule:
    slot = "after_reasoning.build_ctx"
    produces = (_CTX_SLOT,)

    async def run(self, frame: AfterReasoningFrame) -> AfterReasoningFrame:
        frame.slots[_CTX_SLOT] = AfterReasoningContext(
            session_key=frame.input.session_key,
            user_message=frame.input.user_message,
            assistant_content=frame.input.assistant_content,
            tool_chain=list(frame.input.tool_chain),
            context_retry=dict(frame.input.context_retry),
            extra=dict(frame.input.extra),
        )
        return frame


class _EmitAfterReasoningCtxModule:
    slot = "after_reasoning.emit"
    requires = ("after_reasoning.build_ctx", _CTX_SLOT)
    produces = (_CTX_SLOT,)

    def __init__(self, lifecycle: TurnLifecycle) -> None:
        self._lifecycle = lifecycle

    async def run(self, frame: AfterReasoningFrame) -> AfterReasoningFrame:
        context = cast(AfterReasoningContext, frame.slots[_CTX_SLOT])
        frame.slots[_CTX_SLOT] = await self._lifecycle.after_reasoning(context)
        return frame


class _CollectAfterReasoningExportSlotsModule:
    slot = "after_reasoning.collect_exports"
    requires = ("after_reasoning.emit", _CTX_SLOT)
    produces = (_CTX_SLOT,)

    async def run(self, frame: AfterReasoningFrame) -> AfterReasoningFrame:
        context = cast(AfterReasoningContext, frame.slots[_CTX_SLOT])
        for slot, value in sorted(frame.slots.items()):
            if slot.startswith(_ASSISTANT_METADATA_PREFIX):
                key = slot.removeprefix(_ASSISTANT_METADATA_PREFIX)
                context.assistant_metadata[key] = value
        frame.slots[_CTX_SLOT] = context
        return frame


class _PersistAfterReasoningModule:
    slot = "after_reasoning.persist"
    requires = ("after_reasoning.collect_exports", _CTX_SLOT)
    produces = (_RESULT_SLOT,)

    def __init__(
        self,
        *,
        session_manager: SessionManager,
        event_bus: EventBus,
    ) -> None:
        self._session_manager = session_manager
        self._event_bus = event_bus

    async def run(self, frame: AfterReasoningFrame) -> AfterReasoningFrame:
        context = cast(AfterReasoningContext, frame.slots[_CTX_SLOT])
        parsed_response = parse_response(context.assistant_content, tool_chain=[])
        assistant_response = parsed_response.clean_text

        session = self._session_manager.get_or_create(context.session_key)
        user_record = session.add_message(
            "user",
            context.user_message,
            **context.extra,
        )
        assistant_extra: dict[str, Any] = dict(context.assistant_metadata)
        if context.tool_chain:
            assistant_extra["tool_chain"] = context.tool_chain
        if context.context_retry.get("attempts"):
            assistant_extra["context_retry"] = context.context_retry
        assistant_record = session.add_message(
            "assistant",
            assistant_response,
            **assistant_extra,
        )
        self._session_manager.save(session)
        await self._event_bus.emit(
            TurnCommitted(
                session_key=context.session_key,
                input_message=context.user_message,
                persisted_user_message=context.user_message,
                assistant_response=assistant_response,
                timestamp=datetime.now().astimezone(),
                extra={
                    **({"tool_chain": context.tool_chain} if context.tool_chain else {}),
                    "context_retry": context.context_retry,
                },
            )
        )
        frame.slots[_RESULT_SLOT] = AfterReasoningResult(
            session_key=context.session_key,
            user_message_id=str(user_record["id"]),
            assistant_message_id=str(assistant_record["id"]),
            assistant_response=assistant_response,
            context=frame.input.rendered,
            provider_raw=frame.input.provider_raw,
            tool_chain=list(context.tool_chain),
            context_retry=dict(context.context_retry),
        )
        return frame


class _ReturnAfterReasoningResultModule:
    slot = "after_reasoning.return"
    requires = ("after_reasoning.persist", _RESULT_SLOT)

    async def run(self, frame: AfterReasoningFrame) -> AfterReasoningFrame:
        frame.output = cast(AfterReasoningResult, frame.slots[_RESULT_SLOT])
        return frame


def default_after_reasoning_modules(
    *,
    lifecycle: TurnLifecycle,
    session_manager: SessionManager,
    event_bus: EventBus,
    plugin_modules: AfterReasoningModules | None = None,
) -> AfterReasoningModules:
    builtins: AfterReasoningModules = [
        _BuildAfterReasoningCtxModule(),
        _EmitAfterReasoningCtxModule(lifecycle),
        _CollectAfterReasoningExportSlotsModule(),
        _PersistAfterReasoningModule(
            session_manager=session_manager,
            event_bus=event_bus,
        ),
        _ReturnAfterReasoningResultModule(),
    ]
    return cast(
        AfterReasoningModules,
        topo_sort_modules(builtins + list(plugin_modules or [])),
    )
