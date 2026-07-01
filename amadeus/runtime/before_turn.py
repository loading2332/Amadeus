from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias, cast

from amadeus.context import Message
from amadeus.memory.engine import MemoryEngine, MemoryRecallRequest, MemoryScope
from amadeus.runtime.lifecycle import BeforeTurnContext, TurnLifecycle
from amadeus.runtime.phase import PhaseFrame, PhaseModule, topo_sort_modules
from amadeus.session.store import Session, SessionManager

_SESSION_SLOT = "session:session"
_CONTEXT_BUNDLE_SLOT = "session:context_bundle"
_CTX_SLOT = "session:ctx"
_EXTRA_HINT_PREFIX = "session:extra_hint:"
_ABORT_REPLY_SLOT = "session:abort_reply"


@dataclass
class BeforeTurnInput:
    session_key: str
    user_message: str
    retrieved_memory: str | None = None
    active_skills: tuple[str, ...] = ()
    runtime_metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _BeforeTurnContextBundle:
    session: Session
    history: tuple[Message, ...]
    retrieved_memory: str | None
    memory_trace: dict[str, object]


@dataclass
class BeforeTurnFrame(PhaseFrame[BeforeTurnInput, BeforeTurnContext]):
    pass


BeforeTurnModules: TypeAlias = list[PhaseModule[BeforeTurnFrame]]


class _AcquireSessionModule:
    slot = "before_turn.acquire_session"
    requires: tuple[str, ...] = ()
    produces = (_SESSION_SLOT,)

    def __init__(self, session_manager: SessionManager) -> None:
        self._session_manager = session_manager

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        frame.slots[_SESSION_SLOT] = self._session_manager.get_or_create(
            frame.input.session_key
        )
        return frame


class _PrepareContextModule:
    slot = "before_turn.prepare_context"
    requires = ("before_turn.acquire_session", _SESSION_SLOT)
    produces = (_CONTEXT_BUNDLE_SLOT,)

    def __init__(
        self,
        memory_engine: MemoryEngine | None,
        history_window: int,
    ) -> None:
        self._memory_engine = memory_engine
        self._history_window = history_window

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        if _CTX_SLOT in frame.slots:
            return frame
        session = cast(Session, frame.slots[_SESSION_SLOT])
        history = session.get_history(self._history_window)
        retrieved_memory = frame.input.retrieved_memory
        memory_trace: dict[str, object] = {}
        if retrieved_memory is None and self._memory_engine is not None:
            try:
                context_result = await self._memory_engine.build_context(
                    MemoryRecallRequest(
                        text=frame.input.user_message,
                        intent="context",
                        scope=MemoryScope(chat_id=frame.input.session_key),
                        context={
                            "history": history,
                            "session_key": frame.input.session_key,
                        },
                    )
                )
                retrieved_memory = context_result.text
                memory_trace = dict(context_result.trace)
                memory_trace["injected_ids"] = list(context_result.injected_ids)
                memory_trace["omitted_ids"] = list(context_result.omitted_ids)
            except Exception as error:
                memory_trace = {
                    "errors": [f"context_build: {error}"],
                    "record_count": 0,
                }
                retrieved_memory = None
        frame.slots[_CONTEXT_BUNDLE_SLOT] = _BeforeTurnContextBundle(
            session=session,
            history=tuple(history),
            retrieved_memory=retrieved_memory,
            memory_trace=memory_trace,
        )
        return frame


class _BuildBeforeTurnCtxModule:
    slot = "before_turn.build_ctx"
    requires = ("before_turn.prepare_context", _CONTEXT_BUNDLE_SLOT)
    produces = (_CTX_SLOT,)

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        if _CTX_SLOT in frame.slots:
            return frame
        bundle = cast(
            _BeforeTurnContextBundle,
            frame.slots[_CONTEXT_BUNDLE_SLOT],
        )
        frame.slots[_CTX_SLOT] = BeforeTurnContext(
            session_key=frame.input.session_key,
            user_message=frame.input.user_message,
            history=list(bundle.history),
            retrieved_memory=bundle.retrieved_memory,
            memory_trace=dict(bundle.memory_trace),
            active_skills=list(frame.input.active_skills),
            runtime_metadata=dict(frame.input.runtime_metadata),
        )
        return frame


class _EmitBeforeTurnCtxModule:
    slot = "before_turn.emit"
    requires = ("before_turn.build_ctx", _CTX_SLOT)
    produces = (_CTX_SLOT,)

    def __init__(self, lifecycle: TurnLifecycle) -> None:
        self._lifecycle = lifecycle

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        context = cast(BeforeTurnContext, frame.slots[_CTX_SLOT])
        frame.slots[_CTX_SLOT] = await self._lifecycle.before_turn(context)
        return frame


class _ReturnBeforeTurnCtxModule:
    slot = "before_turn.return"
    requires = ("before_turn.collect_exports", _CTX_SLOT)

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        frame.output = cast(BeforeTurnContext, frame.slots[_CTX_SLOT])
        return frame


class _CollectBeforeTurnExportSlotsModule:
    slot = "before_turn.collect_exports"
    requires = ("before_turn.emit", _CTX_SLOT)
    produces = (_CTX_SLOT,)

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        context = cast(BeforeTurnContext, frame.slots[_CTX_SLOT])
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


def default_before_turn_modules(
    *,
    lifecycle: TurnLifecycle,
    session_manager: SessionManager,
    memory_engine: MemoryEngine | None,
    history_window: int,
    plugin_modules: BeforeTurnModules | None = None,
) -> BeforeTurnModules:
    builtins: BeforeTurnModules = [
        _AcquireSessionModule(session_manager),
        _PrepareContextModule(memory_engine, history_window),
        _BuildBeforeTurnCtxModule(),
        _EmitBeforeTurnCtxModule(lifecycle),
        _CollectBeforeTurnExportSlotsModule(),
        _ReturnBeforeTurnCtxModule(),
    ]
    return cast(
        BeforeTurnModules,
        topo_sort_modules(builtins + list(plugin_modules or [])),
    )
