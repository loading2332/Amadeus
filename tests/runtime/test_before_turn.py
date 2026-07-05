from __future__ import annotations

import asyncio
import inspect
from typing import cast

import amadeus.runtime.before_turn as before_turn_module
from amadeus.events import EventBus
from amadeus.memory.engine import (
    MemoryContextResult,
    MemoryEngine,
    MemoryRecallRequest,
)
from amadeus.runtime.before_turn import (
    BeforeTurnFrame,
    BeforeTurnInput,
    default_before_turn_modules,
)
from amadeus.runtime.lifecycle import BeforeTurnContext, TurnLifecycle
from amadeus.runtime.phase import Phase, inspect_phase
from amadeus.session.identity import SessionRef
from amadeus.session.store import InMemorySessionStore, SessionManager


def _session(session_id: int = 1, *, user_id: int = 1) -> SessionRef:
    return SessionRef(user_id=user_id, session_id=session_id)


def test_before_turn_phase_builds_context_from_session_history(tmp_path) -> None:
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(_session())
    session.add_message("user", "earlier message")
    manager.save(session)
    lifecycle = TurnLifecycle(EventBus())
    phase = Phase[BeforeTurnInput, BeforeTurnContext, BeforeTurnFrame](
        default_before_turn_modules(
            lifecycle=lifecycle,
            session_manager=manager,
            memory_engine=None,
            history_window=500,
        ),
        frame_factory=BeforeTurnFrame,
    )

    result = asyncio.run(
        phase.run(
            BeforeTurnInput(
                session=_session(),
                user_message="new message",
                retrieved_memory="supplied memory",
                active_skills=("phase-engine",),
                runtime_metadata={"source": "test"},
            )
        )
    )

    assert result == BeforeTurnContext(
        session=_session(),
        user_message="new message",
        history=[{"role": "user", "content": "earlier message"}],
        retrieved_memory="supplied memory",
        active_skills=["phase-engine"],
        runtime_metadata={"source": "test"},
    )


class _BuildContextMemory:
    def __init__(self) -> None:
        self.requests: list[MemoryRecallRequest] = []

    async def build_context(
        self,
        request: MemoryRecallRequest,
    ) -> MemoryContextResult:
        self.requests.append(request)
        return MemoryContextResult(
            text="memory from build_context",
            injected_ids=["mem_1"],
            omitted_ids=[],
            trace={"record_count": 1},
        )


def test_before_turn_uses_build_context_when_caller_did_not_supply_it(
    tmp_path,
) -> None:
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    memory = _BuildContextMemory()
    phase = Phase[BeforeTurnInput, BeforeTurnContext, BeforeTurnFrame](
        default_before_turn_modules(
            lifecycle=TurnLifecycle(EventBus()),
            session_manager=manager,
            memory_engine=cast(MemoryEngine, memory),
            history_window=500,
        ),
        frame_factory=BeforeTurnFrame,
    )

    result = asyncio.run(
        phase.run(BeforeTurnInput(session=_session(), user_message="remember"))
    )

    assert result.retrieved_memory == "memory from build_context"
    assert memory.requests[0].text == "remember"
    assert memory.requests[0].intent == "context"
    assert memory.requests[0].scope.chat_id is None
    assert memory.requests[0].scope.session == _session()
    assert memory.requests[0].context["session"] == _session()
    assert result.memory_trace["injected_ids"] == ["mem_1"]
    assert result.memory_trace["record_count"] == 1


def test_before_turn_passes_structured_session_into_memory_scope(tmp_path) -> None:
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    memory = _BuildContextMemory()
    phase = Phase[BeforeTurnInput, BeforeTurnContext, BeforeTurnFrame](
        default_before_turn_modules(
            lifecycle=TurnLifecycle(EventBus()),
            session_manager=manager,
            memory_engine=cast(MemoryEngine, memory),
            history_window=500,
        ),
        frame_factory=BeforeTurnFrame,
    )

    result = asyncio.run(
        phase.run(
            BeforeTurnInput(
                session=SessionRef(user_id=3, session_id=5),
                user_message="remember",
            )
        )
    )

    assert result.session == SessionRef(user_id=3, session_id=5)
    assert memory.requests[0].scope.session == SessionRef(user_id=3, session_id=5)
    assert memory.requests[0].context["session"] == SessionRef(user_id=3, session_id=5)


class _FailingMemory(_BuildContextMemory):
    async def build_context(
        self,
        request: MemoryRecallRequest,
    ) -> MemoryContextResult:
        self.requests.append(request)
        raise RuntimeError("memory unavailable")


def test_before_turn_keeps_memory_query_failure_fail_open(tmp_path) -> None:
    memory = _FailingMemory()
    phase = Phase[BeforeTurnInput, BeforeTurnContext, BeforeTurnFrame](
        default_before_turn_modules(
            lifecycle=TurnLifecycle(EventBus()),
            session_manager=SessionManager(tmp_path, store=InMemorySessionStore()),
            memory_engine=cast(MemoryEngine, memory),
            history_window=500,
        ),
        frame_factory=BeforeTurnFrame,
    )

    result = asyncio.run(
        phase.run(BeforeTurnInput(session=_session(), user_message="hello"))
    )

    assert result.retrieved_memory is None
    assert len(memory.requests) == 1


def test_before_turn_emit_can_replace_context(tmp_path) -> None:
    lifecycle = TurnLifecycle(EventBus())
    replacement = BeforeTurnContext(
        session=_session(),
        user_message="replacement",
        history=[],
        retrieved_memory="replaced memory",
    )
    lifecycle.on_before_turn(lambda _context: replacement)
    phase = Phase[BeforeTurnInput, BeforeTurnContext, BeforeTurnFrame](
        default_before_turn_modules(
            lifecycle=lifecycle,
            session_manager=SessionManager(tmp_path, store=InMemorySessionStore()),
            memory_engine=None,
            history_window=500,
        ),
        frame_factory=BeforeTurnFrame,
    )

    result = asyncio.run(
        phase.run(BeforeTurnInput(session=_session(), user_message="hello"))
    )

    assert result is replacement


class _BeforeTurnExportModule:
    slot = "plugin.before_turn_exports"
    requires = ("before_turn.emit", "session:ctx")
    produces = ("session:extra_hint:test", "session:abort_reply")

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        frame.slots["session:extra_hint:test"] = "hint from before_turn"
        frame.slots["session:abort_reply"] = "blocked before reasoning"
        return frame


def test_before_turn_collects_export_hints_and_abort_reply(tmp_path) -> None:
    phase = Phase[BeforeTurnInput, BeforeTurnContext, BeforeTurnFrame](
        default_before_turn_modules(
            lifecycle=TurnLifecycle(EventBus()),
            session_manager=SessionManager(tmp_path, store=InMemorySessionStore()),
            memory_engine=None,
            history_window=500,
            plugin_modules=[_BeforeTurnExportModule()],
        ),
        frame_factory=BeforeTurnFrame,
    )

    result = asyncio.run(
        phase.run(BeforeTurnInput(session=_session(), user_message="hello"))
    )

    assert result.extra_hints == ["hint from before_turn"]
    assert result.abort_reply == "blocked before reasoning"


class _EarlyContextModule:
    slot = "plugin.early_context"
    requires = ("before_turn.acquire_session", "session:session")
    produces = ("session:ctx",)

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        frame.slots["session:ctx"] = BeforeTurnContext(
            session=frame.input.session,
            user_message=frame.input.user_message,
            history=[],
            retrieved_memory="early context",
        )
        return frame


def test_plugin_can_produce_context_before_normal_prepare_and_build(tmp_path) -> None:
    phase = Phase[BeforeTurnInput, BeforeTurnContext, BeforeTurnFrame](
        default_before_turn_modules(
            lifecycle=TurnLifecycle(EventBus()),
            session_manager=SessionManager(tmp_path, store=InMemorySessionStore()),
            memory_engine=None,
            history_window=500,
            plugin_modules=[_EarlyContextModule()],
        ),
        frame_factory=BeforeTurnFrame,
    )

    result = asyncio.run(
        phase.run(BeforeTurnInput(session=_session(), user_message="stop early"))
    )

    assert result.retrieved_memory == "early context"


def test_before_turn_phase_inspection_exposes_real_graph(tmp_path) -> None:
    modules = default_before_turn_modules(
        lifecycle=TurnLifecycle(EventBus()),
        session_manager=SessionManager(tmp_path, store=InMemorySessionStore()),
        memory_engine=None,
        history_window=500,
    )

    report = inspect_phase(modules)

    assert "before_turn.acquire_session" in report
    assert "before_turn.prepare_context" in report
    assert "before_turn.build_ctx" in report
    assert "before_turn.emit" in report
    assert "before_turn.return" in report
    assert "session:session" in report
    assert "session:context_bundle" in report
    assert "session:ctx" in report


def test_before_turn_modules_use_build_context_contract() -> None:
    assert ".build_context(" in inspect.getsource(before_turn_module)

