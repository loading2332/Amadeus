from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

from amadeus.provider import (
    ChatCompletionsClient,
    ChatNamespace,
    LLMProvider,
    LLMProviderConfig,
)
from amadeus.runtime.passive import PassiveRuntime
from amadeus.session.identity import SessionRef
from amadeus.session.store import InMemorySessionStore, SessionManager
from amadeus.tools.base import ToolResult
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.registry import ToolRegistry


class FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: list[Any] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.responses:
            return cast(SimpleNamespace, self.responses.pop(0))
        return SimpleNamespace(
            id="resp",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="assistant reply"))],
            usage={},
        )


@dataclass
class FakeChatNamespace:
    completions: ChatCompletionsClient


class FakeClient:
    def __init__(self, completions: FakeCompletions | None = None) -> None:
        self.completions: FakeCompletions = completions or FakeCompletions()
        self.chat: ChatNamespace = FakeChatNamespace(completions=self.completions)


class EchoTool:
    name = "echo_tool"
    description = "Echo text input back to the model."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(tool_name=self.name, output={"echo": kwargs["text"]})


def _session(session_id: int = 1, *, user_id: int = 1) -> SessionRef:
    return SessionRef(user_id=user_id, session_id=session_id)


def test_session_history_rebuilds_tool_chain_into_assistant_and_tool_messages(tmp_path):
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(_session())
    session.add_message("user", "please use a tool")
    session.add_message(
        "assistant",
        "final answer",
        tool_chain=[
            {
                "text": "Need a tool.",
                "calls": [
                    {
                        "call_id": "call_1",
                        "name": "echo_tool",
                        "arguments": {"text": "hello"},
                        "status": "success",
                        "result": '{"echo": "hello"}',
                    }
                ],
            }
        ],
    )
    manager.save(session)
    manager._cache.clear()

    reloaded = manager.get_or_create(_session())
    history = reloaded.get_history()

    assert [message["role"] for message in history] == ["user", "assistant", "tool", "assistant"]
    assert history[1]["tool_calls"][0]["function"]["name"] == "echo_tool"
    assert history[1]["tool_calls"][0]["function"]["arguments"] == json.dumps(
        {"text": "hello"},
        ensure_ascii=False,
    )
    assert history[2]["tool_call_id"] == "call_1"
    assert history[2]["content"] == '{"echo": "hello"}'
    assert history[3]["content"] == "final answer"


def test_second_turn_reuses_rebuilt_tool_chain_history_for_provider_messages(tmp_path):
    client = FakeClient()
    client.completions.responses = [
        SimpleNamespace(
            id="resp_1",
            model="fake-model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name="echo_tool",
                                    arguments=json.dumps({"text": "hello"}),
                                ),
                            )
                        ],
                    )
                )
            ],
            usage={},
        ),
        SimpleNamespace(
            id="resp_2",
            model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(content="first final"))],
            usage={},
        ),
        SimpleNamespace(
            id="resp_3",
            model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(content="second final"))],
            usage={},
        ),
    ]
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    registry = ToolRegistry()
    registry.register(EchoTool(), always_on=True)
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
        tool_registry=registry,
        tool_executor=ToolExecutor(hooks=[], invoker=registry.execute),
    )

    asyncio.run(runtime.run_turn(session=_session(), user_message="first turn"))
    asyncio.run(runtime.run_turn(session=_session(), user_message="second turn"))

    second_turn_messages = client.completions.calls[2]["messages"]
    history_slice = second_turn_messages[1:-1]

    assert [message["role"] for message in history_slice] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert history_slice[1]["tool_calls"][0]["function"]["name"] == "echo_tool"
    rebuilt_arguments = json.loads(
        history_slice[1]["tool_calls"][0]["function"]["arguments"]
    )
    assert rebuilt_arguments == {"text": "hello"}
    assert history_slice[2]["tool_call_id"] == "call_1"
    assert '"echo": "hello"' in history_slice[2]["content"]
    assert history_slice[3]["content"] == "first final"


