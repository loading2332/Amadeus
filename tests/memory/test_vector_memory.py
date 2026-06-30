from __future__ import annotations

import asyncio
from types import SimpleNamespace

from amadeus.memory import (
    ConsolidateRequest,
    MarkdownMemoryMaintenance,
    MarkdownMemoryStore,
)
from amadeus.memory.engine import (
    EvidenceRef,
    MemoryIngestRequest,
    MemoryMutation,
    MemoryQuery,
    MemoryQueryResult,
    MemoryRecord,
)
from amadeus.memory.vector import (
    VectorMemoryEngine,
    VectorMemoryStore,
    _build_query_plan,
    _extract_terms,
    _rank_rows,
    _rrf_merge,
)
from amadeus.session.store import SessionManager


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
    assert found.records[0].signals["lanes"] == ["lexical"]


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

    assert "## Relevant History" in block
    assert 'source_ref=["chat:1:0"]#h:abc123' in block
    assert result.trace["injected_ids"] == [result.records[0].id]


def test_vector_memory_forget_marks_item_superseded_and_hides_from_query(tmp_path):
    store = VectorMemoryStore(tmp_path / "vector_memory.db")
    engine = VectorMemoryEngine(store=store, embedding_provider=FakeEmbeddingProvider())
    result = asyncio.run(
        engine.ingest(
            MemoryIngestRequest(
                summary="[2026-06-06 10:00] 用户确认迁移 Amadeus 检索记忆。",
                kind="event",
                source_ref='["chat:1:0"]#h:abc123',
            )
        )
    )
    assert result.item_id is not None

    mutation = asyncio.run(
        engine.mutate(MemoryMutation(kind="forget", ids=(result.item_id,)))
    )
    found = asyncio.run(engine.query(MemoryQuery(text="Amadeus 检索", limit=3)))

    assert mutation.accepted is True
    assert mutation.status == "superseded"
    assert mutation.affected_ids == [result.item_id]
    assert mutation.missing_ids == []
    assert store.get_items_by_ids([result.item_id])[0]["status"] == "superseded"
    assert found.records == []


def test_vector_memory_forget_deduplicates_and_reports_missing(tmp_path):
    store = VectorMemoryStore(tmp_path / "vector_memory.db")
    engine = VectorMemoryEngine(store=store, embedding_provider=FakeEmbeddingProvider())
    result = asyncio.run(
        engine.ingest(
            MemoryIngestRequest(
                summary="[2026-06-06 10:00] 用户确认迁移 Amadeus 检索记忆。",
                kind="event",
                source_ref='["chat:1:0"]#h:abc123',
            )
        )
    )
    assert result.item_id is not None

    mutation = asyncio.run(
        engine.mutate(
            MemoryMutation(kind="forget", ids=(result.item_id, "missing", result.item_id))
        )
    )

    assert mutation.affected_ids == [result.item_id]
    assert mutation.missing_ids == ["missing"]


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


def test_rrf_single_lane_only():
    """只有一路有结果时，正常返回该路 top_n。"""
    result = _rrf_merge([("a", 0.9), ("b", 0.8)], [], top_n=3)
    assert len(result) == 2
    assert result[0] == ("a", 1.0 / 61)
    assert result[1] == ("b", 1.0 / 62)


def test_rrf_empty_input_returns_empty():
    """空输入返回空列表。"""
    assert _rrf_merge([], [], top_n=5) == []
    assert _rrf_merge([("a", 0.9)], [], top_n=0) == []


def test_rrf_double_lane_outranks_single_only():
    """两路都确认的条目 RRF 高于仅一路高分的条目。"""
    vector = [("a", 0.9), ("c", 0.6)]  # a: 向量高分, c: 向量中分
    keyword = [("b", 0.8), ("c", 0.5)]  # b: 关键词高分, c: 关键词中分
    # a 只出现在向量路 → vec_rank=1
    # b 只出现在关键词路 → kw_rank=1
    # c 出现在两路 → vec_rank=2, kw_rank=2
    # c 的 RRF = 1/(60+2) + 0.5/(60+2) = 0.01613 + 0.00806 = 0.02419
    # a 的 RRF = 1/(60+1) = 0.01639
    # b 的 RRF = 0.5/(60+1) = 0.00820
    result = _rrf_merge(vector, keyword, top_n=3)
    assert len(result) == 3
    assert result[0][0] == "c", "双路确认的 c 应排第一"
    assert result[0][1] > 0.024
    assert result[1][0] == "a"
    assert result[2][0] == "b"


def test_rank_rows_rrf_double_lane_wins(tmp_path):
    """双路确认的条目应排在没有关键词匹配的高分向量条目之前。"""
    rows = [
        {
            "id": "1", "kind": "event",
            "summary": "用户喜欢讨论各种游戏机制",
            "embedding": [0.9, 0.0, 0.0],
            "source_ref": "",
            "happened_at": None, "extra_json": "{}", "status": "active",
            "reinforcement": 1,
        },
        {
            "id": "2", "kind": "event",
            "summary": "仁王是一款硬核动作游戏",
            "embedding": [0.0, 0.9, 0.0],
            "source_ref": "",
            "happened_at": None, "extra_json": "{}", "status": "active",
            "reinforcement": 1,
        },
        {
            "id": "3", "kind": "preference",
            "summary": "仁王游戏的难度设计和boss机制",
            "embedding": [0.6, 0.5, 0.0],
            "source_ref": "",
            "happened_at": None, "extra_json": "{}", "status": "active",
            "reinforcement": 1,
        },
    ]
    # query_vector=[1,0,0] → cosine: id1=0.9, id2=0.0, id3=0.6
    # query_text="仁王 hardcore" → _extract_terms → ["仁王", "hardcore"]
    # kw: id1=0/2=0 (不含"仁王"也不含"hardcore")
    #     id2=1/2=0.5 (含"仁王")
    #     id3=1/2=0.5 (含"仁王")
    result = _rank_rows(rows, [1.0, 0.0, 0.0], "仁王 hardcore", limit=3, threshold=0.3)
    assert len(result) == 3
    # id=3: vec=0.6(rank=2), kw=0.5(rank=1) → RRF = 1/62 + 0.5/61 = 0.0243
    # id=1: vec=0.9(rank=1), kw=0 → RRF = 1/61 = 0.0164
    # id=2: vec=0(不达标), kw=0.5(rank=2) → RRF = 0 + 0.5/62 = 0.0081
    assert result[0].id == "3", "双路确认应排第一"
    assert result[1].id == "1", "仅向量高分排第二"
    assert result[2].id == "2", "仅关键词排最后"
    assert result[0].signals["lanes"] == ["vector", "lexical"]


def test_rrf_equal_scores_use_stable_id_tiebreak():
    expected = [("a", 1.0 / 61), ("b", 1.0 / 62)]
    for _ in range(10):
        assert _rrf_merge([("b", 0.5), ("a", 0.5)], [], top_n=2) == expected


def test_extract_terms_adds_cjk_bigrams_and_removes_stop_words():
    terms = _extract_terms("我 之前 讨论仁王机制")

    assert "仁王" in terms
    assert "机制" in terms
    assert "之前" not in terms


def test_context_query_plan_uses_explicit_queries():
    plan = _build_query_plan(
        MemoryQuery(
            text="原问题",
            intent="context",
            context={"queries": ["历史问题", "偏好问题", "历史问题"]},
        )
    )

    assert plan.queries == ("历史问题", "偏好问题")


def test_procedure_query_plan_limits_memory_kinds():
    plan = _build_query_plan(MemoryQuery(text="如何发布版本", intent="procedure"))

    assert plan.kinds == ("procedure", "preference")
    assert plan.queries == ("如何发布版本", "执行发布版本的步骤", "发布版本流程")


class FakeHypothesisProvider:
    async def generate(self, query: str, *, style: str) -> str:
        if style == "event":
            return "用户完成 Amadeus 检索重构"
        return "Amadeus memory retrieval implementation"


class BrokenHypothesisProvider:
    async def generate(self, query: str, *, style: str) -> str:
        raise RuntimeError(f"{style} unavailable")


def test_answer_query_uses_hypotheses_and_max_pools_records(tmp_path):
    store = VectorMemoryStore(tmp_path / "vector_memory.db")
    engine = VectorMemoryEngine(
        store=store,
        embedding_provider=FakeEmbeddingProvider(),
        hypothesis_provider=FakeHypothesisProvider(),
    )
    asyncio.run(
        engine.ingest(
            MemoryIngestRequest(
                summary="用户完成 Amadeus 检索重构",
                source_ref='["chat:1:0"]',
            )
        )
    )

    result = asyncio.run(engine.query(MemoryQuery(text="之前做了什么", intent="answer")))

    assert result.trace["queries"] == [
        "之前做了什么",
        "用户完成 Amadeus 检索重构",
        "Amadeus memory retrieval implementation",
    ]
    assert len({record.id for record in result.records}) == len(result.records)
    assert len(result.records[0].signals["matched_query_indexes"]) >= 2


def test_answer_query_hypothesis_failure_falls_back_to_raw_query(tmp_path):
    store = VectorMemoryStore(tmp_path / "vector_memory.db")
    engine = VectorMemoryEngine(
        store=store,
        embedding_provider=FakeEmbeddingProvider(),
        hypothesis_provider=BrokenHypothesisProvider(),
    )

    result = asyncio.run(engine.query(MemoryQuery(text="Amadeus 检索", intent="answer")))

    assert result.trace["queries"] == ["Amadeus 检索"]
    assert result.trace["fallbacks"] == [
        "hypothesis_event_failed",
        "hypothesis_general_failed",
    ]
    assert len(result.trace["errors"]) == 2


def test_render_context_block_groups_and_budgets_whole_entries(tmp_path):
    engine = VectorMemoryEngine(
        store=VectorMemoryStore(tmp_path / "vector_memory.db"),
        embedding_provider=FakeEmbeddingProvider(),
        context_char_budget=220,
    )
    result = MemoryQueryResult(
        records=[
            MemoryRecord("proc", "procedure", "发布前运行完整测试", 0.9, "p:1"),
            MemoryRecord("pref", "preference", "用户偏好中文教学", 0.8, "p:2"),
            MemoryRecord("event", "event", "用户完成了检索切片", 0.7, "p:3"),
        ],
        trace={},
    )

    block = engine.render_context_block(result)

    assert "## Applicable Procedures" in block
    assert "## User Profile" in block
    assert "[proc]" in block
    assert not any(line.endswith("source_") for line in block.splitlines())
    assert result.trace["injected_ids"]
    assert set(result.trace["injected_ids"] + result.trace["omitted_ids"]) == {
        "proc",
        "pref",
        "event",
    }
    assert result.trace["injection_char_count"] <= 220
