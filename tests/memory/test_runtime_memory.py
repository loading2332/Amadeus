from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from amadeus.memory import (
    LongTermMemoryEngine,
    MemoryMemorizer,
    MemoryRetriever,
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
from amadeus.memory.postgres import PostgresMemoryStore
from amadeus.provider import (
    ChatCompletionsClient,
    ChatNamespace,
    LLMProvider,
    LLMProviderConfig,
)
from amadeus.runtime.passive import PassiveRuntime
from amadeus.session.identity import SessionRef
from amadeus.session.store import InMemorySessionStore, SessionManager
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.recall_memory import RecallMemoryTool
from amadeus.tools.registry import ToolRegistry

from tests.db.pgvector_helpers import pad_embedding
from tests.db.postgres_helpers import clean_postgres


class FakeEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        if "Amadeus" in text or "检索" in text:
            return pad_embedding([1.0, 0.0, 0.0])
        return pad_embedding([0.0, 1.0, 0.0])


class FakeExtractor:
    async def extract(
        self,
        *,
        session: SessionRef,
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        del session, messages
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


def _session(session_id: int = 1, *, user_id: int = 1) -> SessionRef:
    return SessionRef(user_id=user_id, session_id=session_id)


@pytest.fixture
def memory_engine():
    db = clean_postgres()
    try:
        yield _build_engine(db)
    finally:
        db.close()


def _build_engine(db) -> LongTermMemoryEngine:
    provider = FakeEmbeddingProvider()
    store = PostgresMemoryStore(user_id=1, db=db)
    memorizer = MemoryMemorizer(store=store, embedding_provider=provider)
    return LongTermMemoryEngine(
        store=store,
        retriever=MemoryRetriever(store=store, embedding_provider=provider),
        memorizer=memorizer,
        worker=PostResponseMemoryWorker(memorizer=memorizer, extractor=FakeExtractor()),
    )


def test_runtime_retrieves_memory_into_context_frame(tmp_path, memory_engine):
    engine = memory_engine
    asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="[2026-06-06 10:00] 用户确认正在迁移 Amadeus 检索记忆。",
                memory_type="event",
                source_ref='["session:1:1:0"]#h:abc123',
            )
        )
    )
    client = FakeClient()
    provider = LLMProvider(LLMProviderConfig(api_key="secret", model="fake"), client=client)
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=SessionManager(tmp_path, store=InMemorySessionStore()),
        memory_engine=engine,
    )

    result = asyncio.run(
        runtime.run_turn(session=_session(), user_message="Amadeus 检索做到哪了？")
    )

    sent_messages = client.completions.calls[0]["messages"]
    assert result.assistant_response == "assistant reply"
    assert any("Relevant History" in message["content"] for message in sent_messages)
    assert not any(
        message["role"] == "system" and "Relevant History" in message["content"]
        for message in sent_messages
    )


def test_runtime_exposes_memory_trace_on_turn_result(tmp_path, memory_engine):
    engine = memory_engine
    asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="[2026-06-06 10:00] 用户完成 Memory Phase 2 设计。",
                memory_type="event",
                source_ref='["session:1:1:0"]#h:trace',
            )
        )
    )
    client = FakeClient()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(LLMProviderConfig(api_key="secret", model="fake"), client=client),
        session_manager=SessionManager(tmp_path, store=InMemorySessionStore()),
        memory_engine=engine,
    )

    result = asyncio.run(
        runtime.run_turn(session=_session(), user_message="Memory Phase 2 到哪了？")
    )

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
            session: SessionRef,
            messages: list[dict[str, Any]],
            explicit_memory_ids: list[str],
        ) -> dict[str, Any]:
            del session, messages, explicit_memory_ids
            return {"status": "skipped"}

    client = FakeClient()
    provider = LLMProvider(LLMProviderConfig(api_key="secret", model="fake"), client=client)
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=SessionManager(tmp_path, store=InMemorySessionStore()),
        memory_engine=BrokenMemory(),
    )

    result = asyncio.run(runtime.run_turn(session=_session(), user_message="hello"))

    assert result.assistant_response == "assistant reply"


def test_runtime_does_not_wait_for_post_response_memory(tmp_path):
    class BlockingPostResponseMemory(MemoryEngine):
        async def recall(self, request: MemoryRecallRequest) -> MemoryQueryResult:
            del request
            return MemoryQueryResult()

        async def memorize(self, request) -> MemoryIngestResult:
            del request
            return MemoryIngestResult(status="skipped")

        def forget(self, ids: list[str]) -> MemoryMutationResult:
            del ids
            return MemoryMutationResult()

        def undo_by_source(self, source_ref: str) -> MemoryMutationResult:
            del source_ref
            return MemoryMutationResult()

        async def build_context(
            self, request: MemoryRecallRequest
        ) -> MemoryContextResult:
            del request
            return MemoryContextResult()

        async def run_post_response(
            self,
            *,
            session: SessionRef,
            messages: list[dict[str, Any]],
            explicit_memory_ids: list[str],
        ) -> dict[str, Any]:
            del session, messages, explicit_memory_ids
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake"),
            client=FakeClient(),
        ),
        session_manager=SessionManager(tmp_path, store=InMemorySessionStore()),
        memory_engine=BlockingPostResponseMemory(),
    )

    async def run_with_deadline():
        return await asyncio.wait_for(
            runtime.run_turn(session=_session(), user_message="hello"),
            timeout=0.1,
        )

    result = asyncio.run(run_with_deadline())

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
            session: SessionRef,
            messages: list[dict[str, Any]],
            explicit_memory_ids: list[str],
        ) -> dict[str, Any]:
            del session, messages, explicit_memory_ids
            return {"status": "skipped"}

    memory = RecordingMemory()
    client = FakeClient()
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=LLMProvider(
            LLMProviderConfig(api_key="secret", model="fake"), client=client
        ),
        session_manager=SessionManager(tmp_path, store=InMemorySessionStore()),
        memory_engine=memory,
    )

    asyncio.run(runtime.run_turn(session=_session(), user_message="hello"))

    assert memory.requests[0].intent == "context"
    assert memory.requests[0].context == {
        "history": [],
        "session": _session(),
    }


def test_passive_and_active_memory_paths_coexist_in_tool_loop(tmp_path, memory_engine):
    engine = memory_engine
    asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="用户完成 Amadeus 检索重构",
                memory_type="event",
                source_ref='["session:1:1:0"]',
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
    registry.register(RecallMemoryTool(memory_engine=engine), always_on=True)
    runtime = PassiveRuntime(
        workspace_root=tmp_path,
        provider=provider,
        session_manager=SessionManager(tmp_path, store=InMemorySessionStore()),
        memory_engine=engine,
        tool_registry=registry,
        tool_executor=ToolExecutor(hooks=[], invoker=registry.execute),
    )

    result = asyncio.run(
        runtime.run_turn(session=_session(), user_message="Amadeus 检索做到哪了？")
    )

    assert result.assistant_response == "done"
    first_messages = client.completions.calls[0]["messages"]
    second_messages = client.completions.calls[1]["messages"]
    assert any("## Relevant History" in str(message["content"]) for message in first_messages)
    assert any("## Relevant History" in str(message["content"]) for message in second_messages)
    tool_messages = [message for message in second_messages if message["role"] == "tool"]
    assert len(tool_messages) == 1
    assert '"count": 1' in tool_messages[0]["content"]
