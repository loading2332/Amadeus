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
from amadeus.tools.recall_memory import RecallMemoryTool
from amadeus.tools.undo_memory_by_source import UndoMemoryBySourceTool

from tests.db.pgvector_helpers import pad_embedding
from tests.db.postgres_helpers import clean_postgres


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        if "旧事实" in text:
            return pad_embedding([1.0, 0.0, 0.0])
        if "新事实" in text:
            return pad_embedding([0.95, 0.05, 0.0])
        return pad_embedding([0.8, 0.2, 0.0])


class FakeExtractor:
    async def extract(
        self,
        *,
        session: SessionRef,
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        del session, messages
        return []


@pytest.fixture
def memory_engine():
    db = clean_postgres()
    try:
        yield _build_memory_engine(db)
    finally:
        db.close()


def _build_memory_engine(db):
    provider = StableEmbeddingProvider()
    store = PostgresMemoryStore(user_id=1, db=db)
    memorizer = MemoryMemorizer(store=store, embedding_provider=provider)
    retriever = MemoryRetriever(store=store, embedding_provider=provider)
    worker = PostResponseMemoryWorker(memorizer=memorizer, extractor=FakeExtractor())
    return LongTermMemoryEngine(
        store=store,
        retriever=retriever,
        memorizer=memorizer,
        worker=worker,
    )


def _seed_replaced_memory(engine):
    original = asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="旧事实",
                memory_type="fact",
                source_ref='["session:1:1:0"]#h:old',
            )
        )
    )
    asyncio.run(
        engine.memorizer.replace(
            target_id=original.item_id,
            request=MemoryWriteRequest(
                summary="新事实",
                memory_type="fact",
                source_ref='["session:1:1:1"]#h:new',
            ),
        )
    )
    return original.item_id, '["session:1:1:1"]#h:new'


def test_undo_memory_by_source_tool_restores_replaced_item(memory_engine) -> None:
    engine = memory_engine
    original_id, source_ref = _seed_replaced_memory(engine)

    result = UndoMemoryBySourceTool(memory_engine=engine).execute(source_ref=source_ref)
    recalled = asyncio.run(RecallMemoryTool(memory_engine=engine).execute(query="旧事实"))

    assert result.is_error is False
    assert original_id in result.output["restored_ids"]
    assert original_id in [item["id"] for item in recalled.output["items"]]

