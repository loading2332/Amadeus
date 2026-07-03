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
        store=MemoryStore(tmp_path / "long_term_memory.db"),
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
        store=MemoryStore(tmp_path / "long_term_memory.db"),
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


def test_memorizer_supersede_many_marks_items_and_records_replacements(tmp_path):
    store = MemoryStore(tmp_path / "long_term_memory.db")
    memorizer = MemoryMemorizer(
        store=store,
        embedding_provider=StableEmbeddingProvider(),
    )
    first = asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="旧偏好一",
                memory_type="preference",
                source_ref='["chat:1:0"]#h:old-a',
            )
        )
    )
    second = asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="旧偏好二",
                memory_type="preference",
                source_ref='["chat:1:1"]#h:old-b',
            )
        )
    )
    replacement = asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="新偏好",
                memory_type="preference",
                source_ref='["chat:1:2"]#h:new',
            )
        )
    )
    assert first.item_id is not None
    assert second.item_id is not None
    assert replacement.item_id is not None

    mutation = memorizer.supersede_many(
        target_ids=[first.item_id, second.item_id, "missing-id", first.item_id],
        reason="user correction",
        replacement_id=replacement.item_id,
        replacement_source_ref='["chat:1:2"]#h:new',
    )

    first_item, second_item = store.get_items_by_ids([first.item_id, second.item_id])
    assert mutation.accepted is True
    assert mutation.status == "superseded"
    assert mutation.affected_ids == [first.item_id, second.item_id]
    assert mutation.missing_ids == ["missing-id"]
    assert mutation.trace == {
        "superseded_ids": [first.item_id, second.item_id],
        "replacement_id": replacement.item_id,
        "replacement_count": 2,
    }
    assert first_item["status"] == "superseded"
    assert first_item["extra"]["replacement_id"] == replacement.item_id
    assert first_item["extra"]["superseded_reason"] == "user correction"
    assert second_item["status"] == "superseded"
    assert store.list_replacements_for(first.item_id) == [
        {"old_item_id": first.item_id, "new_item_id": replacement.item_id}
    ]
    assert store.list_replacements_for(second.item_id) == [
        {"old_item_id": second.item_id, "new_item_id": replacement.item_id}
    ]


def test_memorizer_supersede_many_reports_missing_without_mutation(tmp_path):
    memorizer = MemoryMemorizer(
        store=MemoryStore(tmp_path / "long_term_memory.db"),
        embedding_provider=StableEmbeddingProvider(),
    )

    mutation = memorizer.supersede_many(
        target_ids=["missing-a", "missing-b"],
        reason="user correction",
        replacement_id="mem_new",
        replacement_source_ref='["chat:1:2"]#h:new',
    )

    assert mutation.accepted is False
    assert mutation.status == "missing"
    assert mutation.affected_ids == []
    assert mutation.missing_ids == ["missing-a", "missing-b"]
