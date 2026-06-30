from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from amadeus.context import RuntimeContext
from amadeus.events import EventBus
from amadeus.runtime.lifecycle import (
    AfterTurnContext,
    BeforeTurnContext,
    PromptRenderContext,
    TurnLifecycle,
)


@dataclass(frozen=True)
class _TapEvent:
    value: str


def test_event_bus_fanout_isolates_observer_failures(caplog):
    bus = EventBus()
    seen: list[str] = []

    async def broken(event: _TapEvent) -> None:
        raise RuntimeError("observer failed")

    async def healthy(event: _TapEvent) -> None:
        seen.append(event.value)

    bus.on(_TapEvent, broken)
    bus.on(_TapEvent, healthy)

    asyncio.run(bus.fanout(_TapEvent("reply")))

    assert seen == ["reply"]
    assert "observer failed" in caplog.text


def test_turn_lifecycle_runs_mutable_gates_in_registration_order():
    lifecycle = TurnLifecycle(EventBus())
    before = BeforeTurnContext(
        session_key="cli:1",
        user_message="hello",
        history=[],
        retrieved_memory=None,
        active_skills=[],
        runtime_metadata={},
    )
    prompt = PromptRenderContext(
        session_key="cli:1",
        attempt_index=0,
        attempt_name="full",
        runtime_context=RuntimeContext(
            workspace_root=Path.cwd(),
            history=[],
            current_user_message="hello",
        ),
    )

    lifecycle.on_before_turn(
        lambda context: context.runtime_metadata.__setitem__("order", "first")
    )
    lifecycle.on_before_turn(
        lambda context: context.runtime_metadata.__setitem__(
            "order", f"{context.runtime_metadata['order']}:second"
        )
    )
    lifecycle.on_prompt_render(
        lambda context: context.runtime_context.turn_injection_context.__setitem__(
            "order", "first"
        )
    )
    lifecycle.on_prompt_render(
        lambda context: context.runtime_context.turn_injection_context.__setitem__(
            "order",
            f"{context.runtime_context.turn_injection_context['order']}:second",
        )
    )

    asyncio.run(lifecycle.before_turn(before))
    asyncio.run(lifecycle.prompt_render(prompt))

    assert before.runtime_metadata["order"] == "first:second"
    assert prompt.runtime_context.turn_injection_context["order"] == "first:second"


def test_turn_lifecycle_gate_can_replace_context():
    lifecycle = TurnLifecycle(EventBus())
    original = BeforeTurnContext(
        session_key="cli:1",
        user_message="hello",
        history=[],
        retrieved_memory=None,
    )
    replacement = BeforeTurnContext(
        session_key="cli:1",
        user_message="hello",
        history=[],
        retrieved_memory="replacement memory",
    )
    lifecycle.on_before_turn(lambda _context: replacement)

    result = asyncio.run(lifecycle.before_turn(original))

    assert result is replacement


def test_turn_lifecycle_routes_after_turn_through_failure_isolated_tap(caplog):
    lifecycle = TurnLifecycle(EventBus())
    seen: list[str] = []
    context = AfterTurnContext(
        session_key="cli:1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        assistant_response="reply",
        tool_chain=(),
        context_retry={},
    )

    def broken(_context: AfterTurnContext) -> None:
        raise RuntimeError("after-turn observer failed")

    lifecycle.on_after_turn(broken)
    lifecycle.on_after_turn(lambda event: seen.append(event.assistant_response))

    asyncio.run(lifecycle.after_turn(context))

    assert seen == ["reply"]
    assert "after-turn observer failed" in caplog.text
