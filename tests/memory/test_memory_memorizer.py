from __future__ import annotations

import asyncio

from amadeus.memory.engine import MemoryScope, MemoryWriteRequest
from amadeus.memory.memorizer import MemoryMemorizer
from amadeus.memory.store import MemoryStore


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


def test_memorizer_reinforces_same_content(tmp_path):
    memorizer = MemoryMemorizer(
        store=MemoryStore(tmp_path / "memory2.db"),
        embedding_provider=StableEmbeddingProvider(),
    )

    first = asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="用户偏好中文输出",
                memory_type="preference",
                source_ref='["chat:1:0"]#h:a',
                scope=MemoryScope(channel="telegram", chat_id="100"),
            )
        )
    )
    second = asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="用户偏好中文输出",
                memory_type="preference",
                source_ref='["chat:1:1"]#h:b',
                scope=MemoryScope(channel="telegram", chat_id="100"),
            )
        )
    )

    assert first.status == "new"
    assert second.status == "reinforced"
    assert first.item_id == second.item_id


def test_memorizer_can_replace_and_undo_by_source(tmp_path):
    memorizer = MemoryMemorizer(
        store=MemoryStore(tmp_path / "memory2.db"),
        embedding_provider=StableEmbeddingProvider(),
    )

    original = asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="用户现在住在上海",
                memory_type="fact",
                source_ref='["chat:1:0"]#h:old',
            )
        )
    )
    replacement = asyncio.run(
        memorizer.replace(
            target_id=original.item_id,
            request=MemoryWriteRequest(
                summary="用户现在住在杭州",
                memory_type="fact",
                source_ref='["chat:1:1"]#h:new',
            ),
        )
    )

    undone = memorizer.undo_by_source('["chat:1:1"]#h:new')

    assert replacement.accepted is True
    assert undone.accepted is True
    assert undone.affected_ids == [original.item_id, replacement.affected_ids[-1]]
