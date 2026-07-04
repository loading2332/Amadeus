from __future__ import annotations

import asyncio

from amadeus.memory import (
    LongTermMemoryEngine,
    MemoryMemorizer,
    MemoryRetriever,
    MemoryStore,
    MemoryWriteRequest,
    PostResponseMemoryWorker,
)
from amadeus.tools.recall_memory import RecallMemoryTool
from amadeus.tools.undo_memory_by_source import UndoMemoryBySourceTool


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        if "旧事实" in text:
            return [1.0, 0.0, 0.0]
        if "新事实" in text:
            return [0.95, 0.05, 0.0]
        return [0.8, 0.2, 0.0]


class FakeExtractor:
    async def extract(
        self,
        *,
        session_key: str,
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return []


def _build_memory_engine(tmp_path):
    provider = StableEmbeddingProvider()
    store = MemoryStore(tmp_path / "long_term_memory.db")
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
                source_ref='["chat:1:0"]#h:old',
            )
        )
    )
    asyncio.run(
        engine.memorizer.replace(
            target_id=original.item_id,
            request=MemoryWriteRequest(
                summary="新事实",
                memory_type="fact",
                source_ref='["chat:1:1"]#h:new',
            ),
        )
    )
    return original.item_id, '["chat:1:1"]#h:new'


def test_undo_memory_by_source_tool_restores_replaced_item(tmp_path) -> None:
    engine = _build_memory_engine(tmp_path)
    original_id, source_ref = _seed_replaced_memory(engine)

    result = UndoMemoryBySourceTool(memory_engine=engine).execute(source_ref=source_ref)
    recalled = asyncio.run(RecallMemoryTool(memory_engine=engine).execute(query="旧事实"))

    assert result.is_error is False
    assert original_id in result.output["restored_ids"]
    assert original_id in [item["id"] for item in recalled.output["items"]]
