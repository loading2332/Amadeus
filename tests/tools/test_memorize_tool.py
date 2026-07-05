from __future__ import annotations

import asyncio

import pytest
from amadeus.memory import (
    LongTermMemoryEngine,
    MemoryMemorizer,
    MemoryRetriever,
    PostResponseMemoryWorker,
)
from amadeus.memory.postgres import PostgresMemoryStore
from amadeus.session.identity import SessionRef
from amadeus.tools.memorize import MemorizeTool

from tests.db.pgvector_helpers import pad_embedding
from tests.db.postgres_helpers import clean_postgres


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        if "中文" in text:
            return pad_embedding([1.0, 0.0, 0.0])
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


def test_memorize_tool_writes_long_term_memory(memory_engine) -> None:
    engine = memory_engine

    result = asyncio.run(
        MemorizeTool(memory_engine=engine).execute(
            summary="用户明确要求长期记住：默认中文输出",
            memory_type="preference",
            source_ref='["session:1:1:0"]#h:memorize',
        )
    )

    assert result.is_error is False
    assert result.output["status"] in {"new", "reinforced"}
    assert result.output["memory_id"]

