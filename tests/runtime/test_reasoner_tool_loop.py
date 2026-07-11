from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from amadeus.events import EventBus, ToolCallCompleted, ToolCallStarted
from amadeus.provider import LLMProvider, LLMProviderConfig
from amadeus.session.identity import SessionRef
from amadeus.tools.base import ToolResult
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.registry import ToolRegistry


class _ControlledCompletions:
    """Returns pre-configured responses in sequence, then defaults to text reply."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: list[SimpleNamespace] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.responses:
            return self.responses.pop(0)
        return SimpleNamespace(
            id="resp_final",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="final reply"))],
            usage={},
        )


def _tool_response(
    *,
    tool_name: str = "echo_tool",
    args: dict[str, Any] | None = None,
    call_id: str = "call_1",
) -> SimpleNamespace:
    return SimpleNamespace(
        id="resp_tool",
        model="fake-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id=call_id,
                            function=SimpleNamespace(
                                name=tool_name,
                                arguments=json.dumps(args or {"text": "hello"}),
                            ),
                        )
                    ],
                )
            )
        ],
        usage={},
    )


class _EchoTool:
    name = "echo_tool"
    description = "Echo text back"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(tool_name=self.name, output={"echo": kwargs.get("text", "")})


@dataclass
class _FakeChatNamespace:
    completions: _ControlledCompletions


class _FakeClient:
    def __init__(self, completions: _ControlledCompletions | None = None) -> None:
        self.completions: _ControlledCompletions = completions or _ControlledCompletions()
        self.chat = _FakeChatNamespace(completions=self.completions)


def _make_reasoner(
    client: _FakeClient,
    *,
    max_iterations: int = 10,
):
    from amadeus.runtime.reasoner import Reasoner

    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    registry = ToolRegistry()
    registry.register(_EchoTool())
    tool_executor = ToolExecutor(hooks=[], invoker=registry.execute)
    return Reasoner(
        provider=provider,
        tool_executor=tool_executor,
        max_tool_iterations=max_iterations,
    )


class TestReasonerToolLoop:
    """Tool loop within Reasoner: single tool, multi-step, and guards."""

    def test_single_tool_call_produces_tool_chain(self) -> None:
        client = _FakeClient()
        client.completions.responses = [
            _tool_response(tool_name="echo_tool", args={"text": "ping"}),
        ]
        reasoner = _make_reasoner(client)

        result = asyncio.run(reasoner.reason(messages=[{"role": "user", "content": "do it"}]))

        assert result.reply == "final reply"
        assert len(result.tool_chain) == 1
        assert result.tool_chain[0]["calls"][0]["name"] == "echo_tool"
        assert result.tool_chain[0]["calls"][0]["status"] == "success"
        assert len(client.completions.calls) == 2  # initial + follow-up

    def test_multi_step_tool_loop(self) -> None:
        """Multiple tool call rounds before final reply."""
        client = _FakeClient()
        client.completions.responses = [
            _tool_response(tool_name="echo_tool", args={"text": "step1"}, call_id="call_1"),
            _tool_response(tool_name="echo_tool", args={"text": "step2"}, call_id="call_2"),
        ]
        reasoner = _make_reasoner(client)

        result = asyncio.run(reasoner.reason(messages=[{"role": "user", "content": "multi"}]))

        assert result.reply == "final reply"
        assert len(result.tool_chain) == 2
        assert result.metadata["react_stats"]["iteration_count"] == 2

    def test_max_iterations_guard(self) -> None:
        """Loop stops after max_tool_iterations and returns progress summary."""
        client = _FakeClient()
        # Keep returning tool_calls — model never gives a final reply
        client.completions.responses = [
            _tool_response(tool_name="echo_tool", args={"text": str(i)}, call_id=f"call_{i}")
            for i in range(20)
        ]
        reasoner = _make_reasoner(client, max_iterations=3)

        result = asyncio.run(reasoner.reason(messages=[{"role": "user", "content": "loop"}]))

        assert result.metadata["stop_reason"] == "max_iterations"
        assert len(result.tool_chain) == 3  # 3 iterations executed
        assert len(client.completions.calls) == 3  # initial + 2 followups

    def test_ordinary_chat_with_tool_registry_still_works(self) -> None:
        """When provider returns no tool_calls, tool_chain is empty."""
        client = _FakeClient()
        reasoner = _make_reasoner(client)
        # No responses set → _ControlledCompletions defaults to "final reply"

        result = asyncio.run(reasoner.reason(messages=[{"role": "user", "content": "hello"}]))

        assert result.reply == "final reply"
        assert result.tool_chain == []
        assert len(client.completions.calls) == 1

    def test_repeat_guard_detects_repeated_signature(self) -> None:
        """Repeat guard stops loop when same tool+args repeats."""
        from amadeus.runtime.reasoner import _detect_repeated_signature

        # A-B-A-B pattern within window of 4 → repeated
        history = [
            ("echo_tool", '{"args":{"text":"x"},"name":"echo_tool"}'),
            ("read_file", '{"args":{"path":"/tmp/a"},"name":"read_file"}'),
            ("echo_tool", '{"args":{"text":"x"},"name":"echo_tool"}'),
            ("read_file", '{"args":{"path":"/tmp/a"},"name":"read_file"}'),
        ]
        assert _detect_repeated_signature(history) is True

    def test_repeat_guard_does_not_false_positive(self) -> None:
        """Different args should not trigger repeat guard."""
        from amadeus.runtime.reasoner import _detect_repeated_signature

        history = [
            ("echo_tool", '{"text":"a"}'),
            ("read_file", '{"path":"/tmp/x"}'),
            ("echo_tool", '{"text":"b"}'),
            ("read_file", '{"path":"/tmp/y"}'),
        ]
        assert _detect_repeated_signature(history) is False

    def test_tool_loop_handles_tool_execution_error(self) -> None:
        """未知工具必须记录为 error，且工具循环仍能继续得到最终回复。"""
        client = _FakeClient()
        client.completions.responses = [
            _tool_response(tool_name="missing_tool", args={}, call_id="call_1"),
        ]
        reasoner = _make_reasoner(client)

        result = asyncio.run(
            reasoner.reason(messages=[{"role": "user", "content": "do it"}])
        )

        call = result.tool_chain[0]["calls"][0]
        assert result.reply == "final reply"
        assert call["name"] == "missing_tool"
        assert call["status"] == "error"
        assert "不存在" in call["result"]


class _BusinessPurposeTool:
    name = "business_purpose"
    description = "Consume a business purpose."
    parameters = {
        "type": "object",
        "properties": {"purpose": {"type": "string"}},
        "required": ["purpose"],
    }

    def __init__(self) -> None:
        self.received: dict[str, Any] = {}

    def execute(self, **kwargs: Any) -> ToolResult:
        self.received = dict(kwargs)
        return ToolResult(tool_name=self.name, output=dict(kwargs))


def test_business_purpose_remains_a_plain_argument_end_to_end() -> None:
    from amadeus.runtime.reasoner import Reasoner

    client = _FakeClient()
    client.completions.responses = [
        _tool_response(
            tool_name="business_purpose",
            args={"purpose": "business-purpose"},
        )
    ]
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    registry = ToolRegistry()
    tool = _BusinessPurposeTool()
    registry.register(tool, always_on=True)
    event_bus = EventBus()
    started_events: list[ToolCallStarted] = []
    completed_events: list[ToolCallCompleted] = []
    event_bus.on(ToolCallStarted, started_events.append)
    event_bus.on(ToolCallCompleted, completed_events.append)
    reasoner = Reasoner(
        provider=provider,
        tool_registry=registry,
        tool_executor=ToolExecutor(hooks=[], invoker=registry.execute),
        event_bus=event_bus,
    )

    result = asyncio.run(
        reasoner.reason(
            messages=[{"role": "user", "content": "do it"}],
            session=SessionRef(user_id=1, session_id=1),
        )
    )

    assert tool.received == {"purpose": "business-purpose"}
    assert result.invocations[0].arguments == {"purpose": "business-purpose"}
    assert started_events[0].arguments == {"purpose": "business-purpose"}
    assert completed_events[0].final_arguments == {
        "purpose": "business-purpose"
    }
    call = result.tool_chain[0]["calls"][0]
    assert call["arguments"] == {"purpose": "business-purpose"}

    sent_parameters = client.completions.calls[0]["tools"][0]["function"][
        "parameters"
    ]
    assert sent_parameters == tool.parameters

    follow_up_messages = client.completions.calls[1]["messages"]
    assistant_tool_message = next(
        message for message in follow_up_messages if message.get("tool_calls")
    )
    wire_arguments = json.loads(
        assistant_tool_message["tool_calls"][0]["function"]["arguments"]
    )
    assert wire_arguments == {"purpose": "business-purpose"}
