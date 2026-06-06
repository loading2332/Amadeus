from __future__ import annotations

import asyncio
from types import SimpleNamespace

from amadeus.events import EventBus, TurnCommitted
from amadeus.provider import LLMProvider, LLMProviderConfig
from amadeus.runtime import PassiveRuntime
from amadeus.session import SessionManager


class FakeCompletions:
    def __init__(self) -> None:
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="resp",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="assistant reply"))],
            usage={},
        )


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def test_passive_runtime_persists_turn_and_emits_committed_event(tmp_path):
    client = FakeClient()
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    bus = EventBus()
    events = []
    bus.on(TurnCommitted, lambda event: events.append(event))
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
        event_bus=bus,
    )

    result = asyncio.run(
        runtime.run_turn(session_key="chat:1", user_message="hello")
    )

    session = manager.get_or_create("chat:1")
    assert [message["role"] for message in session.messages] == ["user", "assistant"]
    assert result.user_message_id == "chat:1:0"
    assert result.assistant_message_id == "chat:1:1"
    assert result.assistant_response == "assistant reply"
    assert len(events) == 1
    assert events[0].assistant_response == "assistant reply"


def test_passive_runtime_strips_stage_directions_before_persisting(tmp_path):
    client = FakeClient()
    async def create_with_stage_direction(**kwargs):
        client.completions.calls.append(kwargs)
        return SimpleNamespace(
            id="resp",
            model=kwargs["model"],
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="（突然被夸，愣了一下）\n\n什么啊……谢了。"
                    )
                )
            ],
            usage={},
        )

    client.completions.create = create_with_stage_direction
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    bus = EventBus()
    events = []
    bus.on(TurnCommitted, lambda event: events.append(event))
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
        event_bus=bus,
    )

    result = asyncio.run(
        runtime.run_turn(session_key="chat:1", user_message="你真厉害。")
    )

    session = manager.get_or_create("chat:1")
    assert result.assistant_response == "什么啊……谢了。"
    assert session.messages[-1]["content"] == "什么啊……谢了。"
    assert events[0].assistant_response == "什么啊……谢了。"
