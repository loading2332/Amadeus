from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias, cast

from amadeus.runtime.lifecycle import (
    BeforeReasoningContext,
    BeforeTurnContext,
    TurnLifecycle,
)
from amadeus.runtime.phase import PhaseFrame, PhaseModule, topo_sort_modules

_CTX_SLOT = "reasoning:ctx"
_EXTRA_HINT_PREFIX = "reasoning:extra_hint:"
_ABORT_REPLY_SLOT = "reasoning:abort_reply"


@dataclass
class BeforeReasoningInput:
    before_turn: BeforeTurnContext


@dataclass
class BeforeReasoningFrame(PhaseFrame[BeforeReasoningInput, BeforeReasoningContext]):
    pass


BeforeReasoningModules: TypeAlias = list[PhaseModule[BeforeReasoningFrame]]


class _BuildBeforeReasoningCtxModule:
    slot = "before_reasoning.build_ctx"
    produces = (_CTX_SLOT,)

    async def run(self, frame: BeforeReasoningFrame) -> BeforeReasoningFrame:
        before_turn = frame.input.before_turn
        frame.slots[_CTX_SLOT] = BeforeReasoningContext(
            session_key=before_turn.session_key,
            user_message=before_turn.user_message,
            history=list(before_turn.history),
            retrieved_memory=before_turn.retrieved_memory,
            memory_trace=dict(before_turn.memory_trace),
            active_skills=list(before_turn.active_skills),
            runtime_metadata=dict(before_turn.runtime_metadata),
            extra_hints=list(before_turn.extra_hints),
        )
        return frame


class _EmitBeforeReasoningCtxModule:
    slot = "before_reasoning.emit"
    requires = ("before_reasoning.build_ctx", _CTX_SLOT)
    produces = (_CTX_SLOT,)

    def __init__(self, lifecycle: TurnLifecycle) -> None:
        self._lifecycle = lifecycle

    async def run(self, frame: BeforeReasoningFrame) -> BeforeReasoningFrame:
        context = cast(BeforeReasoningContext, frame.slots[_CTX_SLOT])
        frame.slots[_CTX_SLOT] = await self._lifecycle.before_reasoning(context)
        return frame


class _CollectBeforeReasoningExportSlotsModule:
    slot = "before_reasoning.collect_exports"
    requires = ("before_reasoning.emit", _CTX_SLOT)
    produces = (_CTX_SLOT,)

    async def run(self, frame: BeforeReasoningFrame) -> BeforeReasoningFrame:
        context = cast(BeforeReasoningContext, frame.slots[_CTX_SLOT])
        extra_hints = [
            str(value)
            for slot, value in sorted(frame.slots.items())
            if slot.startswith(_EXTRA_HINT_PREFIX) and value is not None
        ]
        if extra_hints:
            context.extra_hints.extend(extra_hints)
        abort_reply = frame.slots.get(_ABORT_REPLY_SLOT)
        if abort_reply is not None:
            context.abort_reply = str(abort_reply)
        frame.slots[_CTX_SLOT] = context
        return frame


class _ReturnBeforeReasoningCtxModule:
    slot = "before_reasoning.return"
    requires = ("before_reasoning.collect_exports", _CTX_SLOT)

    async def run(self, frame: BeforeReasoningFrame) -> BeforeReasoningFrame:
        frame.output = cast(BeforeReasoningContext, frame.slots[_CTX_SLOT])
        return frame


def default_before_reasoning_modules(
    *,
    lifecycle: TurnLifecycle,
    plugin_modules: BeforeReasoningModules | None = None,
) -> BeforeReasoningModules:
    builtins: BeforeReasoningModules = [
        _BuildBeforeReasoningCtxModule(),
        _EmitBeforeReasoningCtxModule(lifecycle),
        _CollectBeforeReasoningExportSlotsModule(),
        _ReturnBeforeReasoningCtxModule(),
    ]
    return cast(
        BeforeReasoningModules,
        topo_sort_modules(builtins + list(plugin_modules or [])),
    )
