from __future__ import annotations

from amadeus.memory.store import MemoryStore


def test_store_creates_memory2_schema(tmp_path):
    store = MemoryStore(tmp_path / "long_term_memory.db")

    names = store.list_table_names()

    assert "memory_items" in names
    assert "memory_replacements" in names


def test_store_can_record_and_read_replacement_chain(tmp_path):
    store = MemoryStore(tmp_path / "long_term_memory.db")
    store.insert_item(
        item_id="mem_old",
        memory_type="fact",
        summary="旧事实",
        content_hash="old",
        embedding=[1.0, 0.0],
        source_ref='["chat:1:0"]#h:old',
        happened_at=None,
        scope_channel="telegram",
        scope_chat_id="100",
        emotional_weight=0.0,
        extra={},
    )
    store.insert_item(
        item_id="mem_new",
        memory_type="fact",
        summary="新事实",
        content_hash="new",
        embedding=[1.0, 0.1],
        source_ref='["chat:1:1"]#h:new',
        happened_at=None,
        scope_channel="telegram",
        scope_chat_id="100",
        emotional_weight=0.0,
        extra={},
    )

    store.record_replacement("mem_old", "mem_new", '["chat:1:1"]#h:new')

    assert store.list_replacements_for("mem_old") == [
        {"old_item_id": "mem_old", "new_item_id": "mem_new"}
    ]
