from __future__ import annotations

import asyncio

from amadeus.memory import (
    AkashicMemoryEngine,
    MemoryMemorizer,
    MemoryRetriever,
    MemoryStore,
    MemoryWriteRequest,
    PostResponseMemoryWorker,
)
from amadeus.tools.forget_memory import ForgetMemoryTool


class FakeEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0] if "Amadeus" in text else [0.0, 1.0]


class FakeExtractor:
    async def extract(
        self,
        *,
        session_key: str,
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return []


def _build_engine(tmp_path):
    store = MemoryStore(tmp_path / "long_term_memory.db")
    memorizer = MemoryMemorizer(store=store, embedding_provider=FakeEmbeddingProvider())
    return store, AkashicMemoryEngine(
        store=store,
        retriever=MemoryRetriever(store=store, embedding_provider=FakeEmbeddingProvider()),
        memorizer=memorizer,
        worker=PostResponseMemoryWorker(memorizer=memorizer, extractor=FakeExtractor()),
    )


def test_forget_memory_tool_marks_existing_items_superseded(tmp_path):
    store, engine = _build_engine(tmp_path)
    result = asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="[2026-06-06 10:00] 用户确认迁移 Amadeus 检索记忆。",
                memory_type="event",
                source_ref='["chat:1:0"]#h:abc123',
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


def test_forget_memory_tool_ignores_duplicates_and_reports_missing(tmp_path):
    _store, engine = _build_engine(tmp_path)
    result = asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="[2026-06-06 10:00] 用户确认迁移 Amadeus 检索记忆。",
                memory_type="event",
                source_ref='["chat:1:0"]#h:abc123',
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
