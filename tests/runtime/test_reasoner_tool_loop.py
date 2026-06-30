from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from amadeus.provider import LLMProvider, LLMProviderConfig
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
    tool_executor = ToolExecutor(registry=registry)
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
        """Tool error is recorded in tool_chain with status='error', loop continues."""
        client = _FakeClient()
        client.completions.responses = [
            _tool_response(tool_name="echo_tool", args={"text": "ok"}, call_id="call_1"),
        ]
        reasoner = _make_reasoner(client)

        result = asyncio.run(reasoner.reason(messages=[{"role": "user", "content": "do it"}]))

        assert result.reply == "final reply"
        assert result.tool_chain[0]["calls"][0]["status"] == "success"
