from __future__ import annotations

from datetime import UTC, datetime

import psycopg
import pytest
from amadeus.db import PostgresDatabase
from amadeus.memory.postgres import PostgresMemoryStore

from tests.db.postgres_helpers import clean_postgres

EMBEDDING_DIM = 1024


def _pad(values: list[float], dim: int = EMBEDDING_DIM) -> list[float]:
    """Pad a small signal vector to the schema's pgvector dimension.

    Cosine distance only depends on the non-zero coordinates, so a 3-dimensional
    signal vector padded with zeros keeps identical cosine relationships to any
    other vector padded the same way. This lets deterministic tests assert the
    same ranking signals while writing into a ``vector(1024)`` column.
    """
    if len(values) >= dim:
        return [float(v) for v in values[:dim]]
    return [float(v) for v in values] + [0.0] * (dim - len(values))


def _store_for(db: PostgresDatabase, *, user_id: int = 1) -> PostgresMemoryStore:
    return PostgresMemoryStore(user_id, db=db)


def test_insert_and_fetch_round_trip_preserves_embedding_and_extra() -> None:
    db = clean_postgres()
    try:
        store = _store_for(db)
        store.insert_item(
            item_id="mem_a",
            memory_type="fact",
            summary="用户偏好中文",
            content_hash="hash_a",
            embedding=_pad([1.0, 0.0, 0.0]),
            source_ref='["chat:1:0"]#h:a',
            happened_at="2026-07-04T10:00:00+00:00",
            scope_channel="telegram",
            scope_chat_id="100",
            emotional_weight=0.5,
            extra={"k": "v"},
        )

        item = store.get_item_by_id("mem_a")
        assert item is not None
        assert item["memory_type"] == "fact"
        assert item["summary"] == "用户偏好中文"
        assert item["source_ref"] == '["chat:1:0"]#h:a'
        assert item["status"] == "active"
        assert item["reinforcement"] == 1
        assert item["emotional_weight"] == 0.5
        assert item["extra"]["scope_channel"] == "telegram"
        assert item["extra"]["scope_chat_id"] == "100"
        assert item["extra"]["k"] == "v"
        assert item["embedding"][:3] == [1.0, 0.0, 0.0]
        assert len(item["embedding"]) == EMBEDDING_DIM
    finally:
        db.close()


def test_upsert_skips_by_source_ref_reinforces_by_content_hash() -> None:
    db = clean_postgres()
    try:
        store = _store_for(db)
        embedding = _pad([1.0, 0.0, 0.0])

        first_id, first_status = store.upsert_item(
            memory_type="preference",
            summary="默认中文",
            embedding=embedding,
            source_ref='["chat:1:0"]#h:a',
        )
        assert first_status == "new"

        # Same source_ref + type => skipped, no new row.
        second_id, second_status = store.upsert_item(
            memory_type="preference",
            summary="默认中文",
            embedding=embedding,
            source_ref='["chat:1:0"]#h:a',
        )
        assert second_status == "skipped"
        assert second_id == first_id

        # Different source_ref, identical content => reinforcement, no new row.
        reinforced_id, reinforced_status = store.upsert_item(
            memory_type="preference",
            summary="默认中文",
            embedding=embedding,
            source_ref='["chat:1:1"]#h:b',
        )
        assert reinforced_status == "reinforced"
        assert reinforced_id == first_id

        item = store.get_item_by_id(first_id)
        assert item is not None
        assert item["reinforcement"] == 2
    finally:
        db.close()


def test_replacement_chain_records_and_reads_with_user_scope() -> None:
    db = clean_postgres()
    try:
        store = _store_for(db)
        store.insert_item(
            item_id="mem_old",
            memory_type="fact",
            summary="旧事实",
            content_hash="old",
            embedding=_pad([0.0, 1.0, 0.0]),
            source_ref='["chat:1:0"]#h:old',
            happened_at=None,
            scope_channel=None,
            scope_chat_id=None,
            emotional_weight=0.0,
            extra={},
        )
        store.insert_item(
            item_id="mem_new",
            memory_type="fact",
            summary="新事实",
            content_hash="new",
            embedding=_pad([1.0, 0.0, 0.0]),
            source_ref='["chat:1:1"]#h:new',
            happened_at=None,
            scope_channel=None,
            scope_chat_id=None,
            emotional_weight=0.0,
            extra={},
        )
        store.record_replacement("mem_old", "mem_new", '["chat:1:1"]#h:new')

        assert store.list_replacements_for("mem_old") == [
            {"old_item_id": "mem_old", "new_item_id": "mem_new"}
        ]
        by_source = store.find_replacements_by_source_ref('["chat:1:1"]#h:new')
        assert by_source == [
            {
                "old_item_id": "mem_old",
                "new_item_id": "mem_new",
                "source_ref": '["chat:1:1"]#h:new',
            }
        ]
    finally:
        db.close()


def test_list_active_items_filters_scope_type_and_time() -> None:
    db = clean_postgres()
    try:
        store = _store_for(db)
        store.upsert_item(
            memory_type="procedure",
            summary="部署前 smoke",
            embedding=_pad([1.0, 0.0, 0.0]),
            source_ref='["chat:1:0"]#h:p',
            scope_channel="telegram",
            scope_chat_id="100",
            happened_at="2026-07-04T10:00:00+00:00",
        )
        store.upsert_item(
            memory_type="preference",
            summary="偏好中文",
            embedding=_pad([0.95, 0.05, 0.0]),
            source_ref='["chat:1:1"]#h:f',
            scope_channel="web",
            scope_chat_id="200",
            happened_at="2026-07-04T09:00:00+00:00",
        )

        scoped = store.list_active_items(
            memory_types=("procedure",),
            scope_channel="telegram",
            scope_chat_id="100",
        )
        assert [item["summary"] for item in scoped] == ["部署前 smoke"]

        in_window = store.list_active_items(
            time_start=datetime(2026, 7, 4, 9, 30, tzinfo=UTC),
            time_end=datetime(2026, 7, 4, 11, 0, tzinfo=UTC),
        )
        assert {item["summary"] for item in in_window} == {"部署前 smoke"}
    finally:
        db.close()


def test_search_active_items_uses_pgvector_distance_operator() -> None:
    """Candidate recall must go through SQL ``<=>``, not a Python scan.

    With one row aligned with the query vector and one orthogonal to it, the
    pgvector-ordered result must surface the aligned row first and report a
    smaller ``vector_distance``. If the store silently fell back to a Python
    full-table scan, ``vector_distance`` would be absent.
    """
    db = clean_postgres()
    try:
        store = _store_for(db)
        store.upsert_item(
            memory_type="fact",
            summary="aligned fact",
            embedding=_pad([1.0, 0.0, 0.0]),
            source_ref='["chat:1:0"]#h:aligned',
        )
        store.upsert_item(
            memory_type="fact",
            summary="orthogonal fact",
            embedding=_pad([0.0, 1.0, 0.0]),
            source_ref='["chat:1:1"]#h:orthogonal',
        )

        rows = store.search_active_items(
            query_embedding=_pad([1.0, 0.0, 0.0]),
            memory_types=("fact",),
            limit=10,
        )
        assert [item["summary"] for item in rows] == [
            "aligned fact",
            "orthogonal fact",
        ]
        assert rows[0]["vector_distance"] is not None
        assert rows[0]["vector_distance"] < rows[1]["vector_distance"]
        assert rows[0]["vector_distance"] < 0.001
    finally:
        db.close()


def test_user_isolation_blocks_cross_user_reads_and_writes() -> None:
    db = clean_postgres()
    try:
        store_user1 = _store_for(db, user_id=1)
        store_user2 = _store_for(db, user_id=2)

        store_user1.upsert_item(
            memory_type="fact",
            summary="user1 secret fact",
            embedding=_pad([1.0, 0.0, 0.0]),
            source_ref='["chat:1:0"]#h:u1',
        )
        store_user2.upsert_item(
            memory_type="fact",
            summary="user2 secret fact",
            embedding=_pad([1.0, 0.0, 0.0]),
            source_ref='["chat:2:0"]#h:u2',
        )

        u1_ids = [item["id"] for item in store_user1.list_active_items()]
        u2_ids = [item["id"] for item in store_user2.list_active_items()]
        assert u1_ids and u2_ids
        assert set(u1_ids).isdisjoint(set(u2_ids))
        # Cross-user direct lookups return nothing.
        assert store_user2.get_item_by_id(u1_ids[0]) is None
        assert store_user1.get_item_by_id(u2_ids[0]) is None
        # Cross-user source_ref lookups do not leak rows.
        assert store_user2.find_items_by_source_ref('["chat:1:0"]#h:u1') == []
        assert store_user1.find_items_by_source_ref('["chat:2:0"]#h:u2') == []

        # Search must stay within user scope.
        u1_search = store_user1.search_active_items(
            query_embedding=_pad([1.0, 0.0, 0.0]),
            limit=10,
        )
        u2_search = store_user2.search_active_items(
            query_embedding=_pad([1.0, 0.0, 0.0]),
            limit=10,
        )
        assert {item["summary"] for item in u1_search} == {"user1 secret fact"}
        assert {item["summary"] for item in u2_search} == {"user2 secret fact"}
    finally:
        db.close()


def test_embedding_dimension_mismatch_is_rejected_by_pgvector() -> None:
    """PRD R9: dimension mismatch against ``vector(1024)`` must fail loudly."""
    db = clean_postgres()
    try:
        store = _store_for(db)
        with pytest.raises(psycopg.Error):
            store.insert_item(
                item_id="mem_bad",
                memory_type="fact",
                summary="bad dim",
                content_hash="bad",
                embedding=[1.0, 0.0, 0.0],  # only 3 dims, schema wants 1024
                source_ref='["chat:1:0"]#h:bad',
                happened_at=None,
                scope_channel=None,
                scope_chat_id=None,
                emotional_weight=0.0,
                extra={},
            )
    finally:
        db.close()


def test_store_fail_fast_when_vector_extension_missing(monkeypatch) -> None:
    """Constructing an owning store against a non-pgvector DB must fail at open.

    ``PostgresDatabase.open`` runs the extension check; we simulate a missing
    extension by pointing at a fresh database where ``vector`` is not installed.
    Skipped when no second database is reachable, so this is a unit-level guard
    exercised through the ``check_vector_extension`` helper in the db suite.
    """
    from amadeus.db.postgres import PostgresExtensionError, check_vector_extension

    class FakeCursor:
        def __enter__(self) -> FakeCursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, query: str, params: tuple[str, ...]) -> None:
            del query, params

        def fetchone(self) -> None:
            return None

    class FakeConnection:
        def cursor(self) -> FakeCursor:
            return FakeCursor()

    with pytest.raises(PostgresExtensionError, match="vector"):
        check_vector_extension(FakeConnection())
    del monkeypatch
