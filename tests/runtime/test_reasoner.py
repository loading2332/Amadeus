from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from amadeus.provider import LLMProvider, LLMProviderConfig
from amadeus.session.identity import SessionRef
from amadeus.tools.registry import ToolRegistry
from amadeus.types import ReasonerResult


class FakeCompletions:
    """Returns a canned assistant reply. Captures call kwargs for inspection."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="resp",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="assistant reply"))],
            usage={},
        )


@dataclass
class FakeChatNamespace:
    completions: FakeCompletions


class FakeClient:
    def __init__(self, completions: FakeCompletions | None = None) -> None:
        self.completions: FakeCompletions = completions or FakeCompletions()
        self.chat = FakeChatNamespace(completions=self.completions)


class _SchemaOnlyTool:
    name = "test_tool"
    description = "test tool"
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> Any:
        raise AssertionError("ordinary chat must not execute tools")


class TestReasonerFromResponse:
    """from_response() packages an existing LLMResponse without an extra provider call."""

    def test_packages_assistant_reply(self) -> None:
        from amadeus.provider import LLMResponse
        from amadeus.runtime.reasoner import Reasoner

        response = LLMResponse(
            content="packaged reply",
            raw={"id": "test"},
            model="test-model",
            response_id="test-id",
            usage={},
        )

        result = Reasoner.from_response(response)

        assert result.reply == "packaged reply"
        assert result.tool_chain == []
        assert result.provider_raw == {"id": "test"}

    def test_raises_on_none_content(self) -> None:
        from amadeus.provider import LLMResponse
        from amadeus.runtime.reasoner import Reasoner

        response = LLMResponse(content=None, raw=None)

        with pytest.raises(ValueError, match="assistant content"):
            Reasoner.from_response(response)


class TestReasonerOrdinaryChat:
    """Ordinary chat (no tool_calls) returns reply through Reasoner.reason()."""

    # ── RED: test that describes the desired behavior ──────────────────────

    def test_returns_reply_for_simple_chat(self) -> None:
        """Reasoner calls provider and returns assistant reply."""
        from amadeus.runtime.reasoner import Reasoner

        client = FakeClient()
        provider = LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        )
        reasoner = Reasoner(provider=provider)

        result = asyncio.run(
            reasoner.reason(messages=[{"role": "user", "content": "hello"}])
        )

        assert isinstance(result, ReasonerResult)
        assert result.reply == "assistant reply"
        assert result.tool_chain == []
        assert len(client.completions.calls) == 1

    def test_forwards_messages_and_tools_to_provider(self) -> None:
        """Reasoner passes messages and tool schemas through to provider.chat()."""
        from amadeus.runtime.reasoner import Reasoner

        client = FakeClient()
        provider = LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        )
        registry = ToolRegistry()
        registry.register(_SchemaOnlyTool(), always_on=True)
        reasoner = Reasoner(provider=provider, tool_registry=registry)

        asyncio.run(
            reasoner.reason(
                messages=[{"role": "user", "content": "hello"}],
                session=SessionRef(user_id=1, session_id=1),
            )
        )

        assert len(client.completions.calls) == 1
        call_kwargs = client.completions.calls[0]
        assert call_kwargs["messages"] == [{"role": "user", "content": "hello"}]
        assert call_kwargs["tools"] == registry.get_schemas(
            names=registry.get_always_on_names()
        )

    def test_returns_empty_tool_chain_when_no_tools_used(self) -> None:
        """Ordinary chat produces no tool_chain entries."""
        from amadeus.runtime.reasoner import Reasoner

        client = FakeClient()
        provider = LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake-model"),
            client=client,
        )
        reasoner = Reasoner(provider=provider)

        result = asyncio.run(
            reasoner.reason(messages=[{"role": "user", "content": "hello"}])
        )

        assert result.tool_chain == []
        assert result.invocations == []

    def test_uses_provided_model(self) -> None:
        """Reasoner delegates model selection to provider."""
        from amadeus.runtime.reasoner import Reasoner

        client = FakeClient()
        provider = LLMProvider(
            LLMProviderConfig(api_key="secret", model="custom-model"),
            client=client,
        )
        reasoner = Reasoner(provider=provider)

        asyncio.run(
            reasoner.reason(messages=[{"role": "user", "content": "hello"}])
        )

        assert client.completions.calls[0]["model"] == "custom-model"
