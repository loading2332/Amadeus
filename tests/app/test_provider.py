from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from amadeus.provider import (
    ChatCompletionsClient,
    ChatNamespace,
    LLMProvider,
    LLMProviderConfig,
)


class FakeCompletions:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@dataclass
class FakeChatNamespace:
    completions: ChatCompletionsClient


class FakeClient:
    def __init__(self, response: Any) -> None:
        self.completions = FakeCompletions(response)
        self.chat: ChatNamespace = FakeChatNamespace(completions=self.completions)


class FakeStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self):
        async def iterate():
            for chunk in self._chunks:
                yield chunk

        return iterate()


def test_llm_provider_sends_chat_completion_payload_and_parses_response():
    raw = SimpleNamespace(
        id="resp_1",
        model="fake-model",
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))],
        usage={"prompt_tokens": 1},
    )
    client = FakeClient(raw)
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model", max_tokens=100),
        client=client,
    )

    result = asyncio.run(
        provider.chat(
            [{"role": "user", "content": "hi"}],
            max_tokens=10,
            temperature=0,
        )
    )

    assert result.content == "hello"
    assert result.tool_calls == []
    assert result.model == "fake-model"
    assert result.response_id == "resp_1"
    assert client.completions.calls == [
        {
            "model": "fake-model",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 10,
            "temperature": 0,
        }
    ]


def test_llm_provider_parses_flat_tool_arguments_without_assistant_content():
    raw = SimpleNamespace(
        id="resp_2",
        model="fake-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            function=SimpleNamespace(
                                name="fetch_messages",
                                arguments=json.dumps(
                                    {"source_ref": '["session:1:1:0"]'}
                                ),
                            ),
                        )
                    ],
                )
            )
        ],
        usage={"prompt_tokens": 2},
    )
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=FakeClient(raw),
    )

    result = asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))

    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].name == "fetch_messages"
    assert result.tool_calls[0].arguments == {
        "source_ref": '["session:1:1:0"]'
    }


def test_llm_provider_sends_business_tool_schema_unchanged():
    raw = SimpleNamespace(
        id="resp_schema",
        model="fake-model",
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))],
        usage={},
    )
    client = FakeClient(raw)
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    business_parameters = {
        "type": "object",
        "properties": {
            "purpose": {
                "type": "string",
                "description": "远端工具真正消费的业务用途。",
            }
        },
        "required": ["purpose"],
    }
    schema: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": "business_purpose",
            "description": "Consume a business purpose.",
            "parameters": business_parameters,
        },
    }

    asyncio.run(
        provider.chat(
            [{"role": "user", "content": "hi"}],
            tools=[schema],
        )
    )

    assert client.completions.calls[0]["tools"] == [schema]
    assert schema["function"]["parameters"] == business_parameters


def test_llm_provider_rejects_response_without_content_or_tool_calls():
    raw = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))],
    )
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=FakeClient(raw),
    )

    with pytest.raises(ValueError, match="assistant content"):
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))


def test_llm_provider_streams_ordered_content_and_ignores_thinking_fields():
    chunks = [
        SimpleNamespace(
            id="resp_stream",
            model="fake-model",
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="你",
                        reasoning_content="private thought",
                    )
                )
            ],
            usage=None,
        ),
        SimpleNamespace(
            id="resp_stream",
            model="fake-model",
            choices=[SimpleNamespace(delta=SimpleNamespace(content="好"))],
            usage={"completion_tokens": 2},
        ),
    ]
    client = FakeClient(FakeStream(chunks))
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    deltas: list[str] = []

    async def scenario():
        async def collect(delta: str) -> None:
            deltas.append(delta)

        return await provider.chat(
            [{"role": "user", "content": "hi"}],
            content_sink=collect,
        )

    result = asyncio.run(scenario())

    assert deltas == ["你", "好"]
    assert result.content == "你好"
    assert result.usage == {"completion_tokens": 2}
    assert client.completions.calls[0]["stream"] is True
    assert "private thought" not in result.content
