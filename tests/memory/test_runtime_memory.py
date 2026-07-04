from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from amadeus.memory import (
    LongTermMemoryEngine,
    MemoryMemorizer,
    MemoryRetriever,
    MemoryStore,
    MemoryWriteRequest,
    PostResponseMemoryWorker,
)
from amadeus.memory.engine import (
    MemoryContextResult,
    MemoryEngine,
    MemoryIngestResult,
    MemoryMutationResult,
    MemoryQueryResult,
    MemoryRecallRequest,
)
from amadeus.provider import (
    ChatCompletionsClient,
    ChatNamespace,
    LLMProvider,
    LLMProviderConfig,
)
from amadeus.runtime.passive import PassiveRuntime
from amadeus.session.store import SessionManager
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.recall_memory import RecallMemoryTool
from amadeus.tools.registry import ToolRegistry


class FakeEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0] if "Amadeus" in text or "检索" in text else [0.0, 1.0, 0.0]


class FakeExtractor:
    async def extract(
        self,
        *,
        session_key: str,
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return []


class FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: list[SimpleNamespace] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.responses:
            return self.responses.pop(0)
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


def _build_engine(tmp_path) -> LongTermMemoryEngine:
    provider = FakeEmbeddingProvider()
    store = MemoryStore(tmp_path / "long_term_memory.db")
    memorizer = MemoryMemorizer(store=store, embedding_provider=provider)
    return LongTermMemoryEngine(
        store=store,
        retriever=MemoryRetriever(store=store, embedding_provider=provider),
        memorizer=memorizer,
        worker=PostResponseMemoryWorker(memorizer=memorizer, extractor=FakeExtractor()),
    )


def test_runtime_retrieves_memory_into_context_frame(tmp_path):
    engine = _build_engine(tmp_path)
    asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="[2026-06-06 10:00] 用户确认正在迁移 Amadeus 检索记忆。",
                memory_type="event",
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
        memory_engine=engine,
    )

    result = asyncio.run(runtime.run_turn(session_key="chat:1", user_message="Amadeus 检索做到哪了？"))

    sent_messages = client.completions.calls[0]["messages"]
    assert result.assistant_response == "assistant reply"
    assert any("Relevant History" in message["content"] for message in sent_messages)
    assert not any(
        message["role"] == "system" and "Relevant History" in message["content"]
        for message in sent_messages
    )


def test_runtime_exposes_memory_trace_on_turn_result(tmp_path):
    engine = _build_engine(tmp_path)
    asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="[2026-06-06 10:00] 用户完成 Memory Phase 2 设计。",
                memory_type="event",
                source_ref='["chat:1:0"]#h:trace',
            )
        )
    )
    client = FakeClient()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(LLMProviderConfig(api_key="secret", model="fake"), client=client),
        session_manager=SessionManager(tmp_path),
        memory_engine=engine,
    )

    result = asyncio.run(runtime.run_turn(session_key="chat:1", user_message="Memory Phase 2 到哪了？"))

    assert result.memory_trace["record_count"] >= 1
    assert result.memory_trace["injected_ids"]


def test_runtime_continues_when_memory_retrieval_fails(tmp_path):
    class BrokenMemory(MemoryEngine):
        async def recall(self, request: MemoryRecallRequest) -> MemoryQueryResult:
            raise RuntimeError("embedding unavailable")

        async def memorize(self, request) -> MemoryIngestResult:
            return MemoryIngestResult(status="skipped")

        def forget(self, ids: list[str]) -> MemoryMutationResult:
            return MemoryMutationResult()

        def undo_by_source(self, source_ref: str) -> MemoryMutationResult:
            return MemoryMutationResult()

        async def build_context(self, request: MemoryRecallRequest) -> MemoryContextResult:
            raise RuntimeError("embedding unavailable")

        async def run_post_response(
            self,
            *,
            session_key: str,
            messages: list[dict[str, Any]],
            explicit_memory_ids: list[str],
        ) -> dict[str, Any]:
            return {"status": "skipped"}

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


def test_runtime_marks_pre_retrieval_as_context_intent(tmp_path):
    class RecordingMemory(MemoryEngine):
        def __init__(self) -> None:
            self.requests: list[MemoryRecallRequest] = []

        async def recall(self, request: MemoryRecallRequest) -> MemoryQueryResult:
            return MemoryQueryResult()

        async def memorize(self, request) -> MemoryIngestResult:
            return MemoryIngestResult(status="skipped")

        def forget(self, ids: list[str]) -> MemoryMutationResult:
            return MemoryMutationResult()

        def undo_by_source(self, source_ref: str) -> MemoryMutationResult:
            return MemoryMutationResult()

        async def build_context(self, request: MemoryRecallRequest) -> MemoryContextResult:
            self.requests.append(request)
            return MemoryContextResult()

        async def run_post_response(
            self,
            *,
            session_key: str,
            messages: list[dict[str, Any]],
            explicit_memory_ids: list[str],
        ) -> dict[str, Any]:
            return {"status": "skipped"}

    memory = RecordingMemory()
    client = FakeClient()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake"), client=client
        ),
        session_manager=SessionManager(tmp_path),
        memory_engine=memory,
    )

    asyncio.run(runtime.run_turn(session_key="chat:1", user_message="hello"))

    assert memory.requests[0].intent == "context"
    assert memory.requests[0].context == {"history": [], "session_key": "chat:1"}


def test_passive_and_active_memory_paths_coexist_in_tool_loop(tmp_path):
    engine = _build_engine(tmp_path)
    asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="用户完成 Amadeus 检索重构",
                memory_type="event",
                source_ref='["chat:1:0"]',
            )
        )
    )
    client = FakeClient()
    client.completions.responses = [
        SimpleNamespace(
            id="tool",
            model="fake",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call-memory",
                                function=SimpleNamespace(
                                    name="recall_memory",
                                    arguments='{"query":"Amadeus 检索重构"}',
                                ),
                            )
                        ],
                    )
                )
            ],
            usage={},
        ),
        SimpleNamespace(
            id="final",
            model="fake",
            choices=[SimpleNamespace(message=SimpleNamespace(content="done"))],
            usage={},
        ),
    ]
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake"), client=client
    )
    registry = ToolRegistry()
    registry.register(RecallMemoryTool(memory_engine=engine))
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=SessionManager(tmp_path),
        memory_engine=engine,
        tool_registry=registry,
        tool_executor=ToolExecutor(registry=registry),
    )

    result = asyncio.run(
        runtime.run_turn(session_key="chat:1", user_message="Amadeus 检索做到哪了？")
    )

    assert result.assistant_response == "done"
    first_messages = client.completions.calls[0]["messages"]
    second_messages = client.completions.calls[1]["messages"]
    assert any("## Relevant History" in str(message["content"]) for message in first_messages)
    assert any("## Relevant History" in str(message["content"]) for message in second_messages)
    tool_messages = [message for message in second_messages if message["role"] == "tool"]
    assert len(tool_messages) == 1
    assert '"count": 1' in tool_messages[0]["content"]
