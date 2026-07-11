from __future__ import annotations

import asyncio

import pytest
from amadeus.memory.engine import MemoryRecallRequest, MemoryScope, MemoryWriteRequest
from amadeus.memory.memorizer import MemoryMemorizer
from amadeus.memory.postgres import PostgresMemoryStore
from amadeus.memory.retriever import MemoryRetriever

from tests.db.pgvector_helpers import pad_embedding
from tests.db.postgres_helpers import clean_postgres


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        if "部署" in text or "smoke" in lowered or "测试" in text:
            return pad_embedding([1.0, 0.0, 0.0])
        if "中文" in text or "偏好" in text:
            return pad_embedding([0.95, 0.05, 0.0])
        return pad_embedding([1.0, 0.02, 0.0])


class QueryAwareEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        if "event-hypothesis" in lowered:
            return pad_embedding([0.0, 1.0, 0.0])
        if "general-hypothesis" in lowered:
            return pad_embedding([0.0, 0.95, 0.0])
        if "rarelexical" in lowered:
            return pad_embedding([0.0, 0.0, 1.0])
        if "raw" in lowered:
            return pad_embedding([1.0, 0.0, 0.0])
        return pad_embedding([0.0, 1.0, 0.0])


class FakeHypothesisProvider:
    def __init__(
        self,
        *,
        event: str = "event-hypothesis memory statement",
        general: str = "general-hypothesis memory statement",
        fail_styles: set[str] | None = None,
    ) -> None:
        self.event = event
        self.general = general
        self.fail_styles = fail_styles or set()
        self.calls: list[tuple[str, str]] = []

    async def generate(self, query: str, *, style: str) -> str:
        self.calls.append((query, style))
        if style in self.fail_styles:
            raise RuntimeError(f"{style} failed")
        return self.event if style == "event" else self.general


class SlowHypothesisProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate(self, query: str, *, style: str) -> str:
        self.calls.append(style)
        await asyncio.sleep(0.05)
        return f"{style}-too-late"


class FailingEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


class PartiallyFailingEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        if "event-hypothesis" in text:
            raise RuntimeError("event embedding unavailable")
        return pad_embedding([1.0, 0.0, 0.0])


class LexicalOnlyRetrievalStore:
    def __init__(self) -> None:
        self.lexical_calls: list[dict[str, object]] = []

    def search_vector_candidates(self, **kwargs):
        raise AssertionError("vector search must not run without an embedding")

    def search_lexical_candidates(self, **kwargs):
        self.lexical_calls.append(dict(kwargs))
        return [
            {
                "id": "lexical-target",
                "memory_type": "event",
                "summary": "部署标识 ZXQ-4917",
                "embedding": None,
                "source_ref": '["session:1:1:9"]#h:lexical-target',
                "extra": {},
                "reinforcement": 1,
                "emotional_weight": 0,
                "updated_at": "2026-07-11T00:00:00",
                "lexical_score": 1.0,
            }
        ]


class OrderedLexicalRetrievalStore:
    def search_vector_candidates(self, **kwargs):
        raise AssertionError("vector search must not run without an embedding")

    def search_lexical_candidates(self, **kwargs):
        return [
            {
                "id": "event-high",
                "memory_type": "event",
                "summary": "ZXQ-4917 首要历史",
                "embedding": None,
                "source_ref": '["session:1:1:10"]#h:event-high',
                "extra": {},
                "reinforcement": 1,
                "emotional_weight": 0,
                "updated_at": "2026-07-11T00:00:00",
                "lexical_score": 1.0,
            },
            {
                "id": "procedure-low",
                "memory_type": "procedure",
                "summary": "ZXQ-4917 次要流程",
                "embedding": None,
                "source_ref": '["session:1:1:11"]#h:procedure-low',
                "extra": {},
                "reinforcement": 1,
                "emotional_weight": 0,
                "updated_at": "2026-07-11T00:00:00",
                "lexical_score": 0.5,
            },
        ]


class VectorSearchFailingStore(LexicalOnlyRetrievalStore):
    def search_vector_candidates(self, **kwargs):
        raise RuntimeError("vector database unavailable")


class LexicalSearchFailingStore:
    def __init__(self) -> None:
        self.lexical_call_count = 0

    def search_vector_candidates(self, **kwargs):
        return [
            {
                "id": "vector-target",
                "memory_type": "event",
                "summary": "vector target",
                "embedding": kwargs["query_embedding"],
                "vector_distance": 0.0,
                "source_ref": '["session:1:1:12"]#h:vector-target',
                "extra": {},
                "reinforcement": 1,
                "emotional_weight": 0,
                "updated_at": "2026-07-11T00:00:00",
            }
        ]

    def search_lexical_candidates(self, **kwargs):
        self.lexical_call_count += 1
        raise RuntimeError("lexical database unavailable")


class ScopedVectorFailureThenGlobalStore:
    def __init__(self) -> None:
        self.vector_scopes: list[str | None] = []
        self.lexical_scopes: list[str | None] = []

    def search_vector_candidates(self, **kwargs):
        scope_channel = kwargs["scope_channel"]
        self.vector_scopes.append(scope_channel)
        if scope_channel is not None:
            raise RuntimeError("scoped vector search unavailable")
        return [
            {
                "id": "global-vector-target",
                "memory_type": "event",
                "summary": "vector target",
                "embedding": kwargs["query_embedding"],
                "vector_distance": 0.0,
                "source_ref": '["session:1:1:13"]#h:global-vector-target',
                "extra": {},
                "reinforcement": 1,
                "emotional_weight": 0,
                "updated_at": "2026-07-11T00:00:00",
            }
        ]

    def search_lexical_candidates(self, **kwargs):
        self.lexical_scopes.append(kwargs["scope_channel"])
        return []


class ScopedLexicalFailureThenGlobalStore(LexicalOnlyRetrievalStore):
    def search_vector_candidates(self, **kwargs):
        return []

    def search_lexical_candidates(self, **kwargs):
        self.lexical_calls.append(dict(kwargs))
        if kwargs["scope_channel"] is not None:
            raise RuntimeError("scoped lexical search unavailable")
        return super().search_lexical_candidates(**kwargs)


@pytest.fixture
def memory_store():
    db = clean_postgres()
    try:
        yield PostgresMemoryStore(user_id=1, db=db)
    finally:
        db.close()


def test_retriever_prefers_scope_matched_procedure_then_preference(
    memory_store,
) -> None:
    store = memory_store
    memorizer = MemoryMemorizer(
        store=store,
        embedding_provider=StableEmbeddingProvider(),
    )
    asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="部署前先运行 smoke tests",
                memory_type="procedure",
                source_ref='["session:1:1:0"]#h:p',
                scope=MemoryScope(channel="telegram", chat_id="100"),
            )
        )
    )
    asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="用户偏好中文输出",
                memory_type="preference",
                source_ref='["session:1:1:1"]#h:f',
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


def test_lexical_recall_survives_vector_embedding_failure() -> None:
    store = LexicalOnlyRetrievalStore()
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=FailingEmbeddingProvider(),
    )

    result = asyncio.run(
        retriever.recall(MemoryRecallRequest(text="ZXQ-4917", intent="answer", limit=8))
    )

    assert [record.id for record in result.records] == ["lexical-target"]
    assert store.lexical_calls[0]["terms"] == ("ZXQ-4917",)
    assert result.trace["lane_status"] == {
        "vector": "error",
        "lexical": "ok",
    }
    assert result.trace["candidate_counts"] == {
        "vector": 0,
        "lexical": 1,
        "union": 1,
        "final": 1,
    }
    assert result.trace["fallbacks"] == ["vector_retrieval_failed"]
    assert result.trace["errors"] == ["vector_retrieval: RuntimeError"]


def test_raw_query_still_drives_lexical_when_context_adds_vector_queries() -> None:
    store = LexicalOnlyRetrievalStore()
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=FailingEmbeddingProvider(),
    )

    result = asyncio.run(
        retriever.recall(
            MemoryRecallRequest(
                text="ZXQ-4917",
                intent="context",
                context={"queries": ["OTHER-999"]},
            )
        )
    )

    assert result.trace["queries"] == ["ZXQ-4917", "OTHER-999"]
    assert store.lexical_calls[0]["terms"] == ("ZXQ-4917",)
    assert [record.id for record in result.records] == ["lexical-target"]


def test_partial_vector_embedding_failure_marks_lane_degraded() -> None:
    retriever = MemoryRetriever(
        store=LexicalSearchFailingStore(),
        embedding_provider=PartiallyFailingEmbeddingProvider(),
        hypothesis_provider=FakeHypothesisProvider(),
        lexical_retrieval_enabled=False,
    )

    result = asyncio.run(
        retriever.recall(
            MemoryRecallRequest(text="raw vector target", intent="answer", limit=8)
        )
    )

    assert [record.id for record in result.records] == ["vector-target"]
    assert result.trace["lane_status"] == {
        "vector": "degraded",
        "lexical": "disabled",
    }
    assert result.trace["fallbacks"] == ["vector_retrieval_failed"]
    assert result.trace["errors"] == ["vector_retrieval: RuntimeError"]


def test_context_injection_preserves_final_fusion_order() -> None:
    retriever = MemoryRetriever(
        store=OrderedLexicalRetrievalStore(),
        embedding_provider=FailingEmbeddingProvider(),
    )

    result = asyncio.run(
        retriever.build_context(
            MemoryRecallRequest(text="ZXQ-4917", intent="context", limit=8)
        )
    )

    assert result.injected_ids == ["event-high", "procedure-low"]
    assert result.text.index("ZXQ-4917 首要历史") < result.text.index(
        "ZXQ-4917 次要流程"
    )


def test_lexical_recall_survives_vector_search_failure() -> None:
    retriever = MemoryRetriever(
        store=VectorSearchFailingStore(),
        embedding_provider=StableEmbeddingProvider(),
    )

    result = asyncio.run(
        retriever.recall(
            MemoryRecallRequest(text="ZXQ-4917", intent="context", limit=8)
        )
    )

    assert [record.id for record in result.records] == ["lexical-target"]
    assert result.trace["lane_status"] == {
        "vector": "error",
        "lexical": "ok",
    }
    assert result.trace["fallbacks"] == ["vector_retrieval_failed"]
    assert result.trace["errors"] == ["vector_retrieval: RuntimeError"]


def test_vector_recall_survives_lexical_search_failure() -> None:
    store = LexicalSearchFailingStore()
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=StableEmbeddingProvider(),
    )

    result = asyncio.run(
        retriever.recall(
            MemoryRecallRequest(text="vector target", intent="context", limit=8)
        )
    )

    assert [record.id for record in result.records] == ["vector-target"]
    assert result.trace["lane_status"] == {
        "vector": "ok",
        "lexical": "error",
    }
    assert result.trace["fallbacks"] == ["lexical_retrieval_failed"]
    assert result.trace["errors"] == ["lexical_retrieval: RuntimeError"]


def test_disabled_lexical_lane_does_not_query_store() -> None:
    store = LexicalSearchFailingStore()
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=StableEmbeddingProvider(),
        lexical_retrieval_enabled=False,
    )

    result = asyncio.run(
        retriever.recall(
            MemoryRecallRequest(text="vector target", intent="context", limit=8)
        )
    )

    assert [record.id for record in result.records] == ["vector-target"]
    assert store.lexical_call_count == 0
    assert result.trace["lane_status"]["lexical"] == "disabled"
    assert result.trace["fallbacks"] == []
    assert result.trace["errors"] == []


def test_no_lexical_terms_skips_query_and_reports_status() -> None:
    store = LexicalSearchFailingStore()
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=StableEmbeddingProvider(),
    )

    result = asyncio.run(
        retriever.recall(MemoryRecallRequest(text="a 用户", intent="context", limit=8))
    )

    assert [record.id for record in result.records] == ["vector-target"]
    assert store.lexical_call_count == 0
    assert result.trace["lexical_query"] == {"terms": []}
    assert result.trace["lane_status"]["lexical"] == "no_terms"


def test_scope_fallback_preserves_scoped_failure_as_degraded() -> None:
    store = ScopedVectorFailureThenGlobalStore()
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=StableEmbeddingProvider(),
    )

    result = asyncio.run(
        retriever.recall(
            MemoryRecallRequest(
                text="vector target",
                intent="context",
                scope=MemoryScope(channel="telegram"),
                limit=8,
            )
        )
    )

    assert [record.id for record in result.records] == ["global-vector-target"]
    assert result.trace["scope_mode"] == "global-fallback"
    assert result.trace["lane_status"] == {
        "vector": "degraded",
        "lexical": "ok",
    }
    assert result.trace["fallbacks"] == ["vector_retrieval_failed"]
    assert result.trace["errors"] == ["vector_retrieval: RuntimeError"]
    assert store.vector_scopes == ["telegram", None]
    assert store.lexical_scopes == ["telegram", None]


def test_scope_fallback_does_not_relabel_lexical_failure_as_ok() -> None:
    store = ScopedLexicalFailureThenGlobalStore()
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=StableEmbeddingProvider(),
    )

    result = asyncio.run(
        retriever.recall(
            MemoryRecallRequest(
                text="ZXQ-4917",
                intent="context",
                scope=MemoryScope(channel="telegram"),
                limit=8,
            )
        )
    )

    assert [record.id for record in result.records] == ["lexical-target"]
    assert result.trace["scope_mode"] == "global-fallback"
    assert result.trace["lane_status"] == {
        "vector": "ok",
        "lexical": "degraded",
    }
    assert result.trace["fallbacks"] == ["lexical_retrieval_failed"]
    assert result.trace["errors"] == ["lexical_retrieval: RuntimeError"]


def test_answer_retrieval_uses_event_and_general_hypotheses_as_vector_lanes(
    memory_store,
) -> None:
    store = memory_store
    store.upsert_item(
        memory_type="event",
        summary="用户曾经记录过目标事实",
        embedding=pad_embedding([0.0, 1.0, 0.0]),
        source_ref='["session:2:1:0"]#h:event',
    )
    provider = FakeHypothesisProvider()

    retriever = MemoryRetriever(
        store=store,
        embedding_provider=QueryAwareEmbeddingProvider(),
        hypothesis_provider=provider,
        score_threshold=0.8,
    )
    result = asyncio.run(
        retriever.recall(
            MemoryRecallRequest(text="raw wording misses target", intent="answer")
        )
    )

    assert [style for _query, style in provider.calls] == ["event", "general"]
    assert [record.summary for record in result.records] == ["用户曾经记录过目标事实"]
    hypothesis_trace = result.trace["hypothesis_retrieval"]
    assert hypothesis_trace["enabled"] is True
    assert hypothesis_trace["queries"]["event"] == "event-hypothesis memory statement"
    assert (
        hypothesis_trace["queries"]["general"] == "general-hypothesis memory statement"
    )
    assert result.trace["queries"] == [
        "raw wording misses target",
        "event-hypothesis memory statement",
        "general-hypothesis memory statement",
    ]
    assert result.records[0].signals["matched_query_indexes"] == ["1", "2"]


def test_context_retrieval_does_not_call_hypothesis_provider(memory_store) -> None:
    store = memory_store
    provider = FakeHypothesisProvider()
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=QueryAwareEmbeddingProvider(),
        hypothesis_provider=provider,
    )

    result = asyncio.run(
        retriever.recall(MemoryRecallRequest(text="raw context", intent="context"))
    )

    assert provider.calls == []
    assert result.trace["queries"] == ["raw context"]
    assert result.trace["hypothesis_retrieval"]["enabled"] is False
    assert result.trace["hypothesis_retrieval"]["reason"] == "intent_context"


def test_generated_hypotheses_do_not_create_lexical_hits(memory_store) -> None:
    store = memory_store
    store.upsert_item(
        memory_type="event",
        summary="rarelexical phrase exists only in generated hypothesis text",
        embedding=pad_embedding([0.0, 1.0, 0.0]),
        source_ref='["session:2:1:1"]#h:lexical',
    )
    provider = FakeHypothesisProvider(
        event="rarelexical generated phrase",
        general="another rarelexical generated phrase",
    )
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=QueryAwareEmbeddingProvider(),
        hypothesis_provider=provider,
        score_threshold=0.99,
    )

    result = asyncio.run(
        retriever.recall(MemoryRecallRequest(text="raw wording", intent="answer"))
    )

    assert result.records == []
    assert result.trace["lane_counts"]["rarelexical generated phrase"] == {
        "vector": 0,
        "lexical": 0,
    }


def test_hypothesis_failures_fall_back_to_raw_query(memory_store) -> None:
    store = memory_store
    store.upsert_item(
        memory_type="event",
        summary="raw fallback memory",
        embedding=pad_embedding([1.0, 0.0, 0.0]),
        source_ref='["session:2:1:2"]#h:raw',
    )
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=QueryAwareEmbeddingProvider(),
        hypothesis_provider=FakeHypothesisProvider(fail_styles={"event", "general"}),
        score_threshold=0.8,
    )

    result = asyncio.run(
        retriever.recall(MemoryRecallRequest(text="raw fallback", intent="answer"))
    )

    assert [record.summary for record in result.records] == ["raw fallback memory"]
    assert result.trace["queries"] == ["raw fallback"]
    assert result.trace["hypothesis_retrieval"]["queries"] == {}
    assert result.trace["hypothesis_retrieval"]["fallbacks"] == [
        "hypothesis_event_failed",
        "hypothesis_general_failed",
    ]
    assert len(result.trace["hypothesis_retrieval"]["errors"]) == 2


def test_hypothesis_timeout_falls_back_to_raw_query(memory_store) -> None:
    store = memory_store
    store.upsert_item(
        memory_type="event",
        summary="raw timeout memory",
        embedding=pad_embedding([1.0, 0.0, 0.0]),
        source_ref='["session:2:1:3"]#h:timeout',
    )
    provider = SlowHypothesisProvider()
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=QueryAwareEmbeddingProvider(),
        hypothesis_provider=provider,
        hypothesis_timeout_seconds=0.001,
        score_threshold=0.8,
    )

    result = asyncio.run(
        retriever.recall(MemoryRecallRequest(text="raw timeout", intent="answer"))
    )

    assert [record.summary for record in result.records] == ["raw timeout memory"]
    assert result.trace["queries"] == ["raw timeout"]
    assert result.trace["hypothesis_retrieval"]["fallbacks"] == [
        "hypothesis_event_failed",
        "hypothesis_general_failed",
    ]


def test_empty_hypotheses_fall_back_and_are_not_persisted(memory_store) -> None:
    store = memory_store
    store.upsert_item(
        memory_type="event",
        summary="raw persisted memory",
        embedding=pad_embedding([1.0, 0.0, 0.0]),
        source_ref='["session:2:1:5"]#h:empty',
    )
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=QueryAwareEmbeddingProvider(),
        hypothesis_provider=FakeHypothesisProvider(event="", general=""),
        score_threshold=0.8,
    )

    result = asyncio.run(
        retriever.recall(MemoryRecallRequest(text="raw persisted", intent="answer"))
    )

    assert [record.summary for record in result.records] == ["raw persisted memory"]
    assert result.trace["queries"] == ["raw persisted"]
    assert result.trace["hypothesis_retrieval"]["queries"] == {}
    assert result.trace["hypothesis_retrieval"]["fallbacks"] == [
        "hypothesis_event_empty",
        "hypothesis_general_empty",
    ]
    assert [item["summary"] for item in store.list_active_items()] == [
        "raw persisted memory"
    ]


def test_hypothesis_trace_does_not_render_into_context_text(memory_store) -> None:
    store = memory_store
    store.upsert_item(
        memory_type="event",
        summary="用户真正存储的事实",
        embedding=pad_embedding([0.0, 1.0, 0.0]),
        source_ref='["session:2:1:4"]#h:render',
    )
    hypothesis = "event-hypothesis text must stay out of rendered memory"
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=QueryAwareEmbeddingProvider(),
        hypothesis_provider=FakeHypothesisProvider(event=hypothesis),
        score_threshold=0.8,
    )

    result = asyncio.run(
        retriever.build_context(
            MemoryRecallRequest(text="raw wording misses target", intent="answer")
        )
    )

    assert "用户真正存储的事实" in result.text
    assert hypothesis not in result.text
    assert result.trace["hypothesis_retrieval"]["queries"]["event"] == hypothesis
