from __future__ import annotations

import asyncio
from types import SimpleNamespace

from amadeus.memory import (
    ConsolidateRequest,
    MarkdownMemoryMaintenance,
    MarkdownMemoryStore,
)
from amadeus.memory_engine import (
    EvidenceRef,
    MemoryIngestRequest,
    MemoryQuery,
    MemoryQueryResult,
    MemoryRecord,
)
from amadeus.session import SessionManager
from amadeus.vector_memory import VectorMemoryEngine, VectorMemoryStore


class FakeEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        if "amadeus" in lowered or "检索" in lowered:
            return [1.0, 0.0, 0.0]
        if "dr pepper" in lowered:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


def test_memory_record_carries_resolvable_evidence():
    record = MemoryRecord(
        id="mem_1",
        kind="event",
        summary="用户确认正在迁移 Amadeus 检索记忆。",
        score=0.9,
        source_ref='["chat:1:0","chat:1:1"]',
        evidence=[
            EvidenceRef(
                kind="session_messages",
                refs=["chat:1:0", "chat:1:1"],
                resolver="amadeus.session.fetch_messages",
                source_ref='["chat:1:0","chat:1:1"]',
                metadata={},
            )
        ],
        signals={"lane": "vector"},
    )
    result = MemoryQueryResult(records=[record], trace={"mode": "ok"})

    assert result.records[0].evidence[0].refs == ["chat:1:0", "chat:1:1"]
    assert result.records[0].source_ref == '["chat:1:0","chat:1:1"]'


def test_vector_memory_ingests_and_retrieves_with_evidence(tmp_path):
    store = VectorMemoryStore(tmp_path / "vector_memory.db")
    engine = VectorMemoryEngine(store=store, embedding_provider=FakeEmbeddingProvider())

    result = asyncio.run(
        engine.ingest(
            MemoryIngestRequest(
                summary="[2026-06-06 10:00] 用户确认正在迁移 Amadeus 检索记忆。",
                kind="event",
                source_ref='["chat:1:0","chat:1:1"]#h:abc123',
            )
        )
    )
    found = asyncio.run(engine.query(MemoryQuery(text="Amadeus 检索", limit=3)))

    assert result.status == "new"
    assert found.records
    assert found.records[0].source_ref == '["chat:1:0","chat:1:1"]#h:abc123'
    assert found.records[0].evidence[0].refs == ["chat:1:0", "chat:1:1"]


def test_vector_memory_deduplicates_source_ref(tmp_path):
    store = VectorMemoryStore(tmp_path / "vector_memory.db")
    engine = VectorMemoryEngine(store=store, embedding_provider=FakeEmbeddingProvider())
    request = MemoryIngestRequest(
        summary="[2026-06-06 10:00] 用户确认正在迁移 Amadeus 检索记忆。",
        kind="event",
        source_ref='["chat:1:0"]#h:abc123',
    )

    first = asyncio.run(engine.ingest(request))
    second = asyncio.run(engine.ingest(request))

    assert first.status == "new"
    assert second.status == "skipped"
    assert len(store.list_active()) == 1


def test_vector_memory_keyword_fallback_finds_literal_match(tmp_path):
    class MismatchedEmbeddingProvider:
        async def embed(self, text: str) -> list[float]:
            if "用户说" in text:
                return [1.0, 0.0, 0.0]
            return [0.0, 0.0, 1.0]

    store = VectorMemoryStore(tmp_path / "vector_memory.db")
    engine = VectorMemoryEngine(
        store=store,
        embedding_provider=MismatchedEmbeddingProvider(),
        score_threshold=0.95,
    )
    asyncio.run(
        engine.ingest(
            MemoryIngestRequest(
                summary="[2026-06-06 11:00] 用户说 Kurisu 喜欢 Dr Pepper。",
                kind="event",
                source_ref='["chat:1:2"]#h:def456',
            )
        )
    )

    found = asyncio.run(engine.query(MemoryQuery(text="Dr Pepper", limit=3)))

    assert found.records
    assert found.records[0].signals["lane"] == "keyword"


def test_vector_memory_context_block_renders_source_refs(tmp_path):
    store = VectorMemoryStore(tmp_path / "vector_memory.db")
    engine = VectorMemoryEngine(store=store, embedding_provider=FakeEmbeddingProvider())
    asyncio.run(
        engine.ingest(
            MemoryIngestRequest(
                summary="[2026-06-06 10:00] 用户确认正在迁移 Amadeus 检索记忆。",
                source_ref='["chat:1:0"]#h:abc123',
            )
        )
    )
    result = asyncio.run(engine.query(MemoryQuery(text="Amadeus 检索")))

    block = engine.render_context_block(result)

    assert "## Retrieved Memory" in block
    assert 'source_ref=["chat:1:0"]#h:abc123' in block


class FakeConsolidationProvider:
    def __init__(self, consolidation_payload: str, recent_payload: str | None = None) -> None:
        self.responses = [
            consolidation_payload,
            recent_payload
            or '{"active_topics":[],"user_preferences":[],"follow_ups":[],"avoidances":[],"ongoing_threads":[]}',
        ]

    async def chat(self, messages, **kwargs):
        return SimpleNamespace(content=self.responses.pop(0))


def _session_ready_for_consolidation(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("chat:1")
    for index in range(8):
        session.add_message("user", f"user {index}")
        session.add_message("assistant", f"assistant {index}")
    manager.save(session)
    return manager, session


def test_markdown_consolidation_ingests_vector_memory_after_history_commit(tmp_path):
    manager, session = _session_ready_for_consolidation(tmp_path)
    vector_store = VectorMemoryStore(tmp_path / "vector_memory.db")
    vector = VectorMemoryEngine(store=vector_store, embedding_provider=FakeEmbeddingProvider())
    markdown = MarkdownMemoryStore(tmp_path)
    maintenance = MarkdownMemoryMaintenance(
        store=markdown,
        provider=FakeConsolidationProvider(
            """
            {
              "history_entries": [
                {"summary": "[2026-06-06 10:00] 用户确认迁移 Amadeus 检索记忆。"},
                {"summary": "[2026-06-06 10:05] 用户要求 source_ref 按 entry 派生。"}
              ],
              "pending_items": []
            }
            """
        ),
        model="fake",
        keep_count=4,
        session_manager=manager,
        vector_memory=vector,
    )

    result = asyncio.run(maintenance.consolidate(ConsolidateRequest(session=session)))
    found = asyncio.run(vector.query(MemoryQuery(text="source_ref entry 派生", limit=5)))

    assert result.trace["vector_ingest"]["attempted"] == 2
    assert result.trace["vector_ingest"]["failed"] == 0
    assert "用户确认迁移 Amadeus 检索记忆" in markdown.read_history()
    assert len(vector_store.list_active()) == 2
    source_refs = {record.source_ref for record in found.records}
    assert all("#h:" in source_ref for source_ref in source_refs)
    assert len(source_refs) == len(found.records)


def test_markdown_consolidation_keeps_history_when_vector_ingest_fails(tmp_path):
    class BrokenEmbeddingProvider:
        async def embed(self, text: str) -> list[float]:
            raise RuntimeError("embedding unavailable")

    manager, session = _session_ready_for_consolidation(tmp_path)
    vector = VectorMemoryEngine(
        store=VectorMemoryStore(tmp_path / "vector_memory.db"),
        embedding_provider=BrokenEmbeddingProvider(),
    )
    markdown = MarkdownMemoryStore(tmp_path)
    maintenance = MarkdownMemoryMaintenance(
        store=markdown,
        provider=FakeConsolidationProvider(
            '{"history_entries":[{"summary":"[2026-06-06 10:00] 用户确认迁移检索记忆。"}],"pending_items":[]}'
        ),
        model="fake",
        keep_count=4,
        session_manager=manager,
        vector_memory=vector,
    )

    result = asyncio.run(maintenance.consolidate(ConsolidateRequest(session=session)))

    assert "用户确认迁移检索记忆" in markdown.read_history()
    assert result.trace["vector_ingest"]["attempted"] == 1
    assert result.trace["vector_ingest"]["failed"] == 1
