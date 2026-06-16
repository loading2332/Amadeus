from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

from amadeus.events import EventBus, TurnCommitted
from amadeus.provider import (
    ChatCompletionsClient,
    ChatNamespace,
    LLMProvider,
    LLMProviderConfig,
)
from amadeus.runtime import PassiveRuntime
from amadeus.session import SessionManager
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


class StageDirectionCompletions(FakeCompletions):
    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
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
    client = FakeClient(completions=StageDirectionCompletions())
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


def test_passive_runtime_executes_single_tool_call_before_persisting_final_reply(
    tmp_path,
):
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
                                    arguments=json.dumps({"text": "hello from tool"}),
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
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="assistant after tool")
                )
            ],
            usage={},
        ),
    ]
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    registry = ToolRegistry()
    registry.register(EchoTool())
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
        tool_registry=registry,
        tool_executor=ToolExecutor(registry=registry),
    )

    result = asyncio.run(
        runtime.run_turn(session_key="chat:1", user_message="please use a tool")
    )

    session = manager.get_or_create("chat:1")
    assert result.assistant_response == "assistant after tool"
    assert [message["role"] for message in session.messages] == ["user", "assistant"]
    assert len(client.completions.calls) == 2
    assert client.completions.calls[0]["tools"] == registry.export_openai_tools()
    assert client.completions.calls[1]["tools"] == registry.export_openai_tools()
    assert [message["role"] for message in client.completions.calls[1]["messages"][-2:]] == [
        "assistant",
        "tool",
    ]
    assert (
        client.completions.calls[1]["messages"][-2]["tool_calls"][0]["function"]["name"]
        == "echo_tool"
    )
    assert (
        '"echo": "hello from tool"'
        in client.completions.calls[1]["messages"][-1]["content"]
    )
    # tool_chain records the tool call
    assert len(result.tool_chain) == 1
    assert result.tool_chain[0]["calls"][0]["name"] == "echo_tool"
    assert result.tool_chain[0]["calls"][0]["status"] == "success"


def test_passive_runtime_continues_when_followup_response_requests_another_tool(
    tmp_path,
):
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
                                    arguments=json.dumps({"text": "first"}),
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
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Need one more lookup.",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_2",
                                function=SimpleNamespace(
                                    name="echo_tool",
                                    arguments=json.dumps({"text": "second"}),
                                ),
                            )
                        ],
                    )
                )
            ],
            usage={},
        ),
        SimpleNamespace(
            id="resp_3",
            model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(content="final answer"))],
            usage={},
        ),
    ]
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    registry = ToolRegistry()
    registry.register(EchoTool())
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
        tool_registry=registry,
        tool_executor=ToolExecutor(registry=registry),
    )

    result = asyncio.run(
        runtime.run_turn(session_key="chat:1", user_message="use tools twice")
    )

    assert result.assistant_response == "final answer"
    assert len(client.completions.calls) == 3
    assert [
        message["role"]
        for message in client.completions.calls[2]["messages"][-4:]
    ] == ["assistant", "tool", "assistant", "tool"]
    assert (
        client.completions.calls[2]["messages"][-2]["tool_calls"][0]["function"]["name"]
        == "echo_tool"
    )
    assert '"echo": "second"' in client.completions.calls[2]["messages"][-1]["content"]
    # tool_chain records both tool call rounds
    assert len(result.tool_chain) == 2
    assert result.tool_chain[0]["calls"][0]["name"] == "echo_tool"
    assert result.tool_chain[0]["calls"][0]["status"] == "success"
    assert result.tool_chain[1]["calls"][0]["name"] == "echo_tool"
    assert result.tool_chain[1]["calls"][0]["status"] == "success"


def test_passive_runtime_returns_progress_summary_when_tool_loop_hits_iteration_limit(
    tmp_path,
):
    client = FakeClient()
    client.completions.responses = [
        SimpleNamespace(
            id="resp_1",
            model="fake-model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="I need a file.",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name="echo_tool",
                                    arguments=json.dumps({"text": "first"}),
                                ),
                            )
                        ],
                    )
                )
            ],
            usage={},
        ),
    ]
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    manager = SessionManager(tmp_path)
    registry = ToolRegistry()
    registry.register(EchoTool())
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=manager,
        tool_registry=registry,
        tool_executor=ToolExecutor(registry=registry),
        max_tool_iterations=1,
    )

    result = asyncio.run(
        runtime.run_turn(session_key="chat:1", user_message="use too many tools")
    )

    assert len(client.completions.calls) == 1
    assert "工具执行已经达到本轮上限" in result.assistant_response
    assert "echo_tool" in result.assistant_response
    assert "first" in result.assistant_response
    assert manager.get_or_create("chat:1").messages[-1]["content"] == result.assistant_response
    # tool_chain has the calls up to the limit
    assert len(result.tool_chain) == 1
    assert result.tool_chain[0]["calls"][0]["name"] == "echo_tool"
    assert result.tool_chain[0]["calls"][0]["status"] == "success"


def test_tool_chain_is_persisted_in_assistant_message_extra(tmp_path):
    """tool_chain 持久化进 assistant message 的 extra 字段。"""
    client = FakeClient()
    client.completions.responses = [
        SimpleNamespace(
            id="resp_1", model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(
                    id="call_1", function=SimpleNamespace(
                        name="echo_tool", arguments=json.dumps({"text": "hello"})))],
            ))],
            usage={},
        ),
        SimpleNamespace(
            id="resp_2", model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(content="done"))],
            usage={},
        ),
    ]
    provider = LLMProvider(LLMProviderConfig(api_key="secret", model="fake-model"), client=client)
    manager = SessionManager(tmp_path)
    registry = ToolRegistry()
    registry.register(EchoTool())
    runtime = PassiveRuntime(
        workspace_root=tmp_path, provider=provider, session_manager=manager,
        tool_registry=registry, tool_executor=ToolExecutor(registry=registry),
    )
    result = asyncio.run(
        runtime.run_turn(session_key="persist:1", user_message="use tool")
    )

    # 从 session 中重新读取 assistant message，验证 tool_chain 已持久化
    session = manager.get_or_create("persist:1")
    assistant_msg = session.messages[-1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == result.assistant_response
    assert "tool_chain" in assistant_msg
    assert len(assistant_msg["tool_chain"]) == 1
    assert assistant_msg["tool_chain"][0]["calls"][0]["name"] == "echo_tool"

    # 验证从数据库重新加载后 tool_chain 仍然存在
    manager._cache.clear()
    reloaded_session = manager.get_or_create("persist:1")
    reloaded_msg = reloaded_session.messages[-1]
    assert "tool_chain" in reloaded_msg
    assert reloaded_msg["tool_chain"][0]["calls"][0]["name"] == "echo_tool"


def test_tool_messages_are_not_in_session_history(tmp_path):
    """Assistant/tool 中间消息不直接持久化，但 get_history 会从 tool_chain 重建它们。"""
    client = FakeClient()
    client.completions.responses = [
        SimpleNamespace(
            id="resp_1", model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(
                    id="call_1", function=SimpleNamespace(
                        name="echo_tool", arguments=json.dumps({"text": "hello"})))],
            ))],
            usage={},
        ),
        SimpleNamespace(
            id="resp_2", model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(content="final"))],
            usage={},
        ),
    ]
    provider = LLMProvider(LLMProviderConfig(api_key="secret", model="fake-model"), client=client)
    manager = SessionManager(tmp_path)
    registry = ToolRegistry()
    registry.register(EchoTool())
    runtime = PassiveRuntime(
        workspace_root=tmp_path, provider=provider, session_manager=manager,
        tool_registry=registry, tool_executor=ToolExecutor(registry=registry),
    )
    result = asyncio.run(
        runtime.run_turn(session_key="filter:1", user_message="use tool")
    )

    session = manager.get_or_create("filter:1")
    # session.messages 应只有 user + assistant，没有 tool 中间消息
    assert [m["role"] for m in session.messages] == ["user", "assistant"]
    assert len(session.messages) == 2

    # get_history 不直接复用 raw tool 消息，而是从 assistant.tool_chain 重建 assistant/tool 序列
    history = session.get_history(500)
    assert [m["role"] for m in history] == ["user", "assistant", "tool", "assistant"]
    assert history[1]["tool_calls"][0]["function"]["name"] == "echo_tool"
    assert history[2]["tool_call_id"] == "call_1"
    assert history[3]["content"] == result.assistant_response
