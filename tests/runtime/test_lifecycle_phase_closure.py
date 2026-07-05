from __future__ import annotations

import asyncio
from typing import Any

from amadeus.context import ContextBuilder, RuntimeContext
from amadeus.events import EventBus, TurnCommitted
from amadeus.runtime.after_reasoning import (
    AfterReasoningFrame,
    AfterReasoningInput,
    default_after_reasoning_modules,
)
from amadeus.runtime.after_turn import (
    AfterTurnFrame,
    AfterTurnInput,
    default_after_turn_modules,
)
from amadeus.runtime.before_reasoning import (
    BeforeReasoningFrame,
    BeforeReasoningInput,
    default_before_reasoning_modules,
)
from amadeus.runtime.lifecycle import AfterTurnContext, BeforeTurnContext, TurnLifecycle
from amadeus.runtime.phase import Phase
from amadeus.runtime.step_phases import (
    AfterStepFrame,
    AfterStepInput,
    BeforeStepFrame,
    BeforeStepInput,
    default_after_step_modules,
    default_before_step_modules,
)
from amadeus.session.identity import SessionRef
from amadeus.session.store import InMemorySessionStore, SessionManager


class _BeforeReasoningExportModule:
    slot = "plugin.before_reasoning_exports"
    requires = ("before_reasoning.emit", "reasoning:ctx")
    produces = ("reasoning:extra_hint:test", "reasoning:abort_reply")

    async def run(self, frame: BeforeReasoningFrame) -> BeforeReasoningFrame:
        frame.slots["reasoning:extra_hint:test"] = "hint before reasoning"
        frame.slots["reasoning:abort_reply"] = "abort before reasoning"
        return frame


def _session(session_id: int = 1) -> SessionRef:
    return SessionRef(user_id=1, session_id=session_id)


def test_before_reasoning_collects_hints_and_abort_reply() -> None:
    phase = Phase(
        default_before_reasoning_modules(
            lifecycle=TurnLifecycle(EventBus()),
            plugin_modules=[_BeforeReasoningExportModule()],
        ),
        frame_factory=BeforeReasoningFrame,
    )

    result = asyncio.run(
        phase.run(
            BeforeReasoningInput(
                before_turn=BeforeTurnContext(
                    session=_session(),
                    user_message="hello",
                    history=[],
                    retrieved_memory=None,
                    extra_hints=["from before_turn"],
                )
            )
        )
    )

    assert result.extra_hints == ["from before_turn", "hint before reasoning"]
    assert result.abort_reply == "abort before reasoning"


class _BeforeStepExportModule:
    slot = "plugin.before_step_exports"
    requires = ("before_step.emit", "step:before_ctx")
    produces = ("step:extra_hint:test", "step:early_stop_reply")

    async def run(self, frame: BeforeStepFrame) -> BeforeStepFrame:
        frame.slots["step:extra_hint:test"] = "use cached result"
        frame.slots["step:early_stop_reply"] = "stop before tool batch"
        return frame


class _AfterStepExportModule:
    slot = "plugin.after_step_exports"
    requires = ("after_step.emit", "step:after_ctx")
    produces = ("step:telemetry:budget", "step:early_stop_reply")

    async def run(self, frame: AfterStepFrame) -> AfterStepFrame:
        frame.slots["step:telemetry:budget"] = {"remaining": 3}
        frame.slots["step:early_stop_reply"] = "stop after tool batch"
        return frame


def test_step_phases_collect_early_stop_and_telemetry() -> None:
    before_phase = Phase(
        default_before_step_modules(
            lifecycle=TurnLifecycle(EventBus()),
            plugin_modules=[_BeforeStepExportModule()],
        ),
        frame_factory=BeforeStepFrame,
    )
    after_phase = Phase(
        default_after_step_modules(
            lifecycle=TurnLifecycle(EventBus()),
            plugin_modules=[_AfterStepExportModule()],
        ),
        frame_factory=AfterStepFrame,
    )

    before = asyncio.run(
        before_phase.run(
            BeforeStepInput(
                session=_session(),
                iteration=0,
                messages=[],
                tool_schemas=None,
            )
        )
    )
    after = asyncio.run(
        after_phase.run(
            AfterStepInput(
                session=_session(),
                iteration=0,
                messages=[],
                tool_chain=[{"calls": []}],
            )
        )
    )

    assert before.extra_hints == ["use cached result"]
    assert before.early_stop_reply == "stop before tool batch"
    assert after.telemetry == {"budget": {"remaining": 3}}
    assert after.early_stop_reply == "stop after tool batch"


class _AfterReasoningMetadataModule:
    slot = "plugin.after_reasoning_metadata"
    requires = ("after_reasoning.emit", "reasoning:after_ctx")
    produces = ("outbound:metadata:source",)

    async def run(self, frame: Any) -> Any:
        frame.slots["outbound:metadata:source"] = "phase"
        return frame


def test_after_reasoning_persists_turn_and_metadata(tmp_path) -> None:
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    bus = EventBus()
    events: list[TurnCommitted] = []
    bus.on(TurnCommitted, lambda event: events.append(event))
    phase = Phase(
        default_after_reasoning_modules(
            lifecycle=TurnLifecycle(bus),
            session_manager=manager,
            event_bus=bus,
            plugin_modules=[_AfterReasoningMetadataModule()],
        ),
        frame_factory=AfterReasoningFrame,
    )
    rendered = ContextBuilder().render(
        RuntimeContext(
            workspace_root=tmp_path,
            history=[],
            current_user_message="hello",
        )
    )

    result = asyncio.run(
        phase.run(
            AfterReasoningInput(
                session=_session(),
                user_message="hello",
                assistant_content="saved reply",
                rendered=rendered,
                provider_raw={"id": "raw"},
                tool_chain=[],
                context_retry={"attempts": [], "selected_plan": "full"},
            )
        )
    )

    session = manager.get_or_create(_session())
    assert result.assistant_response == "saved reply"
    assert [message["role"] for message in session.messages] == ["user", "assistant"]
    assert session.messages[-1]["source"] == "phase"
    assert events[0].assistant_response == "saved reply"


def test_after_turn_phase_calls_existing_tap_and_isolates_failures(
    tmp_path,
    caplog,
) -> None:
    bus = EventBus()
    lifecycle = TurnLifecycle(bus)
    observed: list[str] = []

    def broken(_context: AfterTurnContext) -> None:
        raise RuntimeError("tap failed")

    def observe(context: AfterTurnContext) -> None:
        observed.append(context.assistant_response)

    lifecycle.on_after_turn(broken)
    lifecycle.on_after_turn(observe)
    phase = Phase(
        default_after_turn_modules(
            lifecycle=lifecycle,
            memory_engine=None,
            session_manager=SessionManager(tmp_path, store=InMemorySessionStore()),
        ),
        frame_factory=AfterTurnFrame,
    )

    asyncio.run(
        phase.run(
            AfterTurnInput(
                context=AfterTurnContext(
                    session=_session(),
                    user_message_id="u1",
                    assistant_message_id="a1",
                    assistant_response="done",
                    tool_chain=(),
                    context_retry={},
                )
            )
        )
    )

    assert observed == ["done"]
    assert "tap failed" in caplog.text

