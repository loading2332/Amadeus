from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from amadeus.events import EventBus


@dataclass
class OrderedEvent:
    calls: list[str]


@dataclass(frozen=True)
class GateEvent:
    value: str
    calls: list[str]


@dataclass(frozen=True)
class TapEvent:
    value: str


class EqualHandler:
    def __init__(self, label: str) -> None:
        self.label = label

    def __call__(self, event: OrderedEvent) -> None:
        event.calls.append(self.label)

    def __eq__(self, _other: object) -> bool:
        return True


def test_emit_runs_higher_priority_handlers_first_with_stable_ties() -> None:
    bus = EventBus()

    def low(event: OrderedEvent) -> None:
        event.calls.append("low")

    def high_first(event: OrderedEvent) -> None:
        event.calls.append("high-first")

    def high_second(event: OrderedEvent) -> None:
        event.calls.append("high-second")

    bus.on(OrderedEvent, low, priority=0)
    bus.on(OrderedEvent, high_first, priority=100)
    bus.on(OrderedEvent, high_second, priority=100)

    result = asyncio.run(bus.emit(OrderedEvent(calls=[])))

    assert result.calls == ["high-first", "high-second", "low"]


def test_off_removes_only_the_exact_handler_and_missing_removals_are_safe() -> None:
    bus = EventBus()

    def first(event: OrderedEvent) -> None:
        event.calls.append("first")

    def second(event: OrderedEvent) -> None:
        event.calls.append("second")

    bus.on(OrderedEvent, first)
    bus.on(OrderedEvent, second)

    bus.off(OrderedEvent, first)
    bus.off(OrderedEvent, first)
    bus.off(OrderedEvent, lambda _event: None)
    bus.off(str, lambda _event: None)

    result = asyncio.run(bus.emit(OrderedEvent(calls=[])))

    assert result.calls == ["second"]


def test_off_uses_handler_identity_instead_of_equality() -> None:
    bus = EventBus()
    removed = EqualHandler("removed")
    retained = EqualHandler("retained")
    assert removed is not retained
    assert removed == retained

    bus.on(OrderedEvent, removed)
    bus.on(OrderedEvent, retained)

    bus.off(OrderedEvent, removed)
    result = asyncio.run(bus.emit(OrderedEvent(calls=[])))

    assert result.calls == ["retained"]


def test_emit_passes_the_current_result_through_each_gate_sequentially() -> None:
    bus = EventBus()
    calls: list[str] = []

    def replace(event: GateEvent) -> GateEvent:
        calls.append(f"replace:{event.value}")
        return GateEvent(value=f"{event.value}:replaced", calls=event.calls)

    async def observe_replacement(event: GateEvent) -> None:
        calls.append(f"observe:{event.value}")

    bus.on(GateEvent, replace)
    bus.on(GateEvent, observe_replacement)

    result = asyncio.run(bus.emit(GateEvent(value="initial", calls=[])))

    assert result.value == "initial:replaced"
    assert calls == ["replace:initial", "observe:initial:replaced"]


def test_emit_uses_a_subscription_snapshot_for_the_current_dispatch() -> None:
    bus = EventBus()
    calls: list[str] = []

    def late(_event: OrderedEvent) -> None:
        calls.append("late")

    def victim(_event: OrderedEvent) -> None:
        calls.append("victim")

    def change_subscriptions(_event: OrderedEvent) -> None:
        calls.append("change")
        bus.on(OrderedEvent, late)
        bus.off(OrderedEvent, victim)

    bus.on(OrderedEvent, change_subscriptions)
    bus.on(OrderedEvent, victim)

    asyncio.run(bus.emit(OrderedEvent(calls=[])))
    assert calls == ["change", "victim"]

    calls.clear()
    asyncio.run(bus.emit(OrderedEvent(calls=[])))
    assert calls == ["change", "late"]


def test_fanout_isolates_observer_exceptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    seen: list[str] = []

    async def broken(_event: TapEvent) -> None:
        raise RuntimeError("tap observer failed")

    async def healthy(event: TapEvent) -> None:
        seen.append(event.value)

    bus.on(TapEvent, broken)
    bus.on(TapEvent, healthy)

    asyncio.run(bus.fanout(TapEvent(value="observed")))

    assert seen == ["observed"]
    assert "tap observer failed" in caplog.text


def test_fanout_uses_a_subscription_snapshot_for_the_current_dispatch() -> None:
    bus = EventBus()
    calls: list[str] = []

    def late(_event: TapEvent) -> None:
        calls.append("late")

    def victim(_event: TapEvent) -> None:
        calls.append("victim")

    def change_subscriptions(_event: TapEvent) -> None:
        calls.append("change")
        bus.on(TapEvent, late)
        bus.off(TapEvent, victim)

    bus.on(TapEvent, change_subscriptions)
    bus.on(TapEvent, victim)

    asyncio.run(bus.fanout(TapEvent(value="first")))
    assert sorted(calls) == ["change", "victim"]

    calls.clear()
    asyncio.run(bus.fanout(TapEvent(value="second")))
    assert sorted(calls) == ["change", "late"]
