from __future__ import annotations

import asyncio

from amadeus.memory import (
    AkashicMemoryEngine,
    MemoryMemorizer,
    MemoryRetriever,
    MemoryStore,
    PostResponseMemoryWorker,
)
from amadeus.tools.memorize import MemorizeTool


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        if "中文" in text:
            return [1.0, 0.0, 0.0]
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
    store = MemoryStore(tmp_path / "memory2.db")
    memorizer = MemoryMemorizer(store=store, embedding_provider=provider)
    retriever = MemoryRetriever(store=store, embedding_provider=provider)
    worker = PostResponseMemoryWorker(memorizer=memorizer, extractor=FakeExtractor())
    return AkashicMemoryEngine(
        store=store,
        retriever=retriever,
        memorizer=memorizer,
        worker=worker,
    )


def test_memorize_tool_writes_long_term_memory(tmp_path) -> None:
    engine = _build_memory_engine(tmp_path)

    result = asyncio.run(
        MemorizeTool(memory_engine=engine).execute(
            summary="用户明确要求长期记住：默认中文输出",
            memory_type="preference",
            source_ref='["chat:1:0"]#h:memorize',
        )
    )

    assert result.is_error is False
    assert result.output["status"] in {"new", "reinforced"}
    assert result.output["memory_id"]
