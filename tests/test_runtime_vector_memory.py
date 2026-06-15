from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from amadeus.memory_engine import (
    MemoryEngine,
    MemoryIngestRequest,
    MemoryIngestResult,
    MemoryQuery,
    MemoryQueryResult,
)
from amadeus.provider import (
    ChatCompletionsClient,
    ChatNamespace,
    LLMProvider,
    LLMProviderConfig,
)
from amadeus.runtime import PassiveRuntime
from amadeus.session import SessionManager
from amadeus.vector_memory import VectorMemoryEngine, VectorMemoryStore


class FakeEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0] if "Amadeus" in text or "检索" in text else [0.0, 1.0, 0.0]


class FakeCompletions:
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
    completions: ChatCompletionsClient


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat: ChatNamespace = FakeChatNamespace(completions=self.completions)


def test_runtime_retrieves_memory_into_context_frame(tmp_path):
    vector = VectorMemoryEngine(
        store=VectorMemoryStore(tmp_path / "vector_memory.db"),
        embedding_provider=FakeEmbeddingProvider(),
    )
    asyncio.run(
        vector.ingest(
            MemoryIngestRequest(
                summary="[2026-06-06 10:00] 用户确认正在迁移 Amadeus 检索记忆。",
                source_ref='["chat:1:0"]#h:abc123',
            )
        )
    )
    client = FakeClient()
    provider = LLMProvider(LLMProviderConfig(api_key="secret", model="fake"), client=client)
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=SessionManager(tmp_path),
        memory_engine=vector,
    )

    result = asyncio.run(runtime.run_turn(session_key="chat:1", user_message="Amadeus 检索做到哪了？"))

    sent_messages = client.completions.calls[0]["messages"]
    assert result.assistant_response == "assistant reply"
    assert any("Retrieved Memory" in message["content"] for message in sent_messages)
    assert not any(
        message["role"] == "system" and "Retrieved Memory" in message["content"]
        for message in sent_messages
    )


def test_runtime_continues_when_memory_retrieval_fails(tmp_path):
    class BrokenMemory(MemoryEngine):
        async def ingest(self, request: MemoryIngestRequest) -> MemoryIngestResult:
            return MemoryIngestResult(status="skipped")

        async def query(self, query: MemoryQuery) -> MemoryQueryResult:
            raise RuntimeError("embedding unavailable")

        def render_context_block(self, result: MemoryQueryResult) -> str:
            return "should not render"

    client = FakeClient()
    provider = LLMProvider(LLMProviderConfig(api_key="secret", model="fake"), client=client)
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=SessionManager(tmp_path),
        memory_engine=BrokenMemory(),
    )

    result = asyncio.run(runtime.run_turn(session_key="chat:1", user_message="hello"))

    assert result.assistant_response == "assistant reply"
