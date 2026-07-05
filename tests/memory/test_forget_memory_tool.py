from __future__ import annotations

import asyncio

import pytest
from amadeus.memory import (
    LongTermMemoryEngine,
    MemoryMemorizer,
    MemoryRetriever,
    MemoryWriteRequest,
    PostResponseMemoryWorker,
)
from amadeus.memory.postgres import PostgresMemoryStore
from amadeus.session.identity import SessionRef
from amadeus.tools.forget_memory import ForgetMemoryTool

from tests.db.pgvector_helpers import pad_embedding
from tests.db.postgres_helpers import clean_postgres


class FakeEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        if "Amadeus" in text:
            return pad_embedding([1.0, 0.0])
        return pad_embedding([0.0, 1.0])


class FakeExtractor:
    async def extract(
        self,
        *,
        session: SessionRef,
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        del session, messages
        return []


def _build_engine(store):
    memorizer = MemoryMemorizer(store=store, embedding_provider=FakeEmbeddingProvider())
    return store, LongTermMemoryEngine(
        store=store,
        retriever=MemoryRetriever(store=store, embedding_provider=FakeEmbeddingProvider()),
        memorizer=memorizer,
        worker=PostResponseMemoryWorker(memorizer=memorizer, extractor=FakeExtractor()),
    )


@pytest.fixture
def memory_store():
    db = clean_postgres()
    try:
        yield PostgresMemoryStore(user_id=1, db=db)
    finally:
        db.close()


def test_forget_memory_tool_marks_existing_items_superseded(memory_store):
    store, engine = _build_engine(memory_store)
    result = asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="[2026-06-06 10:00] 用户确认迁移 Amadeus 检索记忆。",
                memory_type="event",
                source_ref='["session:1:1:0"]#h:abc123',
            )
        )
    )
    assert result.item_id is not None

    tool = ForgetMemoryTool(memory_engine=engine)
    output = tool.execute(ids=[result.item_id])

    assert output.is_error is False
    assert output.output["requested_ids"] == [result.item_id]
    assert output.output["superseded_ids"] == [result.item_id]
    assert output.output["missing_ids"] == []
    assert output.output["count"] == 1
    assert store.get_items_by_ids([result.item_id])[0]["status"] == "superseded"


def test_forget_memory_tool_ignores_duplicates_and_reports_missing(memory_store):
    _store, engine = _build_engine(memory_store)
    result = asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="[2026-06-06 10:00] 用户确认迁移 Amadeus 检索记忆。",
                memory_type="event",
                source_ref='["session:1:1:0"]#h:abc123',
            )
        )
    )
    assert result.item_id is not None

    tool = ForgetMemoryTool(memory_engine=engine)
    output = tool.execute(ids=[result.item_id, "missing", result.item_id])

    assert output.is_error is False
    assert output.output["requested_ids"] == [result.item_id, "missing"]
    assert output.output["superseded_ids"] == [result.item_id]
    assert output.output["missing_ids"] == ["missing"]


def test_forget_memory_tool_reports_unconfigured_memory_engine():
    tool = ForgetMemoryTool(memory_engine=None)

    output = tool.execute(ids=["mem_missing"])

    assert output.is_error is True
    assert output.output["error"] == "memory engine is not configured"

