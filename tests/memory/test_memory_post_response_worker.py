from __future__ import annotations

import asyncio

from amadeus.memory.memorizer import MemoryMemorizer
from amadeus.memory.post_response_worker import PostResponseMemoryWorker
from amadeus.memory.store import MemoryStore


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        if "中文" in text:
            return [1.0, 0.0, 0.0]
        return [0.8, 0.2, 0.0]


class FakeExtractor:
    async def extract(self, *, session_key: str, messages: list[dict[str, str]]):
        return [
            {
                "summary": "用户明确要求长期记住：默认用中文",
                "memory_type": "preference",
                "source_ref": '["chat:1:0"]#h:extract',
            }
        ]


def test_post_response_worker_writes_implicit_memory_once(tmp_path) -> None:
    worker = PostResponseMemoryWorker(
        memorizer=MemoryMemorizer(
            store=MemoryStore(tmp_path / "long_term_memory.db"),
            embedding_provider=StableEmbeddingProvider(),
        ),
        extractor=FakeExtractor(),
    )

    result = asyncio.run(
        worker.run(
            session_key="chat:1",
            messages=[{"role": "user", "content": "以后默认中文回复"}],
            explicit_memory_ids=[],
        )
    )

    assert result["written_count"] == 1
    assert result["skipped_duplicates"] == 0
    assert result["written_ids"]
