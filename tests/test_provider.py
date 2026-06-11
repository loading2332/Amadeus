from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from amadeus.provider import LLMProvider, LLMProviderConfig


class FakeCompletions:
    def __init__(self, response) -> None:
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeClient:
    def __init__(self, response) -> None:
        self.completions = FakeCompletions(response)
        self.chat = SimpleNamespace(completions=self.completions)


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


def test_llm_provider_parses_tool_calls_without_assistant_content():
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
                                arguments=json.dumps({"source_ref": '["chat:1:0"]'}),
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
    assert result.tool_calls[0].arguments == {"source_ref": '["chat:1:0"]'}


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
