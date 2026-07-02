from __future__ import annotations

import asyncio

from amadeus.memory.engine import MemoryRecallRequest, MemoryScope, MemoryWriteRequest
from amadeus.memory.memorizer import MemoryMemorizer
from amadeus.memory.retriever import MemoryRetriever
from amadeus.memory.store import MemoryStore


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        if "部署" in text or "smoke" in lowered or "测试" in text:
            return [1.0, 0.0, 0.0]
        if "中文" in text or "偏好" in text:
            return [0.95, 0.05, 0.0]
        return [1.0, 0.02, 0.0]


def test_retriever_prefers_scope_matched_procedure_then_preference(tmp_path) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
    memorizer = MemoryMemorizer(
        store=store,
        embedding_provider=StableEmbeddingProvider(),
    )
    asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="部署前先运行 smoke tests",
                memory_type="procedure",
                source_ref='["chat:1:0"]#h:p',
                scope=MemoryScope(channel="telegram", chat_id="100"),
            )
        )
    )
    asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="用户偏好中文输出",
                memory_type="preference",
                source_ref='["chat:1:1"]#h:f',
                scope=MemoryScope(channel="telegram", chat_id="100"),
            )
        )
    )

    retriever = MemoryRetriever(
        store=store,
        embedding_provider=StableEmbeddingProvider(),
    )
    result = asyncio.run(
        retriever.build_context(
            MemoryRecallRequest(
                text="怎么继续这个任务",
                intent="context",
                scope=MemoryScope(channel="telegram", chat_id="100"),
            )
        )
    )

    assert result.injected_ids
    assert "部署前先运行 smoke tests" in result.text
    assert "用户偏好中文输出" in result.text
    assert result.text.index("部署前先运行 smoke tests") < result.text.index(
        "用户偏好中文输出"
    )
