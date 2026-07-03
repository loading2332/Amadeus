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


class QueryAwareEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        if "event-hypothesis" in lowered:
            return [0.0, 1.0, 0.0]
        if "general-hypothesis" in lowered:
            return [0.0, 0.95, 0.0]
        if "rarelexical" in lowered:
            return [0.0, 0.0, 1.0]
        if "raw" in lowered:
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]


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


def test_answer_retrieval_uses_event_and_general_hypotheses_as_vector_lanes(
    tmp_path,
) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
    store.upsert_item(
        memory_type="event",
        summary="用户曾经记录过目标事实",
        embedding=[0.0, 1.0, 0.0],
        source_ref='["chat:2:0"]#h:event',
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
    assert hypothesis_trace["queries"]["general"] == "general-hypothesis memory statement"
    assert result.trace["queries"] == [
        "raw wording misses target",
        "event-hypothesis memory statement",
        "general-hypothesis memory statement",
    ]
    assert result.records[0].signals["matched_query_indexes"] == ["1", "2"]


def test_context_retrieval_does_not_call_hypothesis_provider(tmp_path) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
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


def test_generated_hypotheses_do_not_create_lexical_hits(tmp_path) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
    store.upsert_item(
        memory_type="event",
        summary="rarelexical phrase exists only in generated hypothesis text",
        embedding=[0.0, 1.0, 0.0],
        source_ref='["chat:2:1"]#h:lexical',
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


def test_hypothesis_failures_fall_back_to_raw_query(tmp_path) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
    store.upsert_item(
        memory_type="event",
        summary="raw fallback memory",
        embedding=[1.0, 0.0, 0.0],
        source_ref='["chat:2:2"]#h:raw',
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


def test_hypothesis_timeout_falls_back_to_raw_query(tmp_path) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
    store.upsert_item(
        memory_type="event",
        summary="raw timeout memory",
        embedding=[1.0, 0.0, 0.0],
        source_ref='["chat:2:3"]#h:timeout',
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


def test_empty_hypotheses_fall_back_and_are_not_persisted(tmp_path) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
    store.upsert_item(
        memory_type="event",
        summary="raw persisted memory",
        embedding=[1.0, 0.0, 0.0],
        source_ref='["chat:2:5"]#h:empty',
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


def test_hypothesis_trace_does_not_render_into_context_text(tmp_path) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
    store.upsert_item(
        memory_type="event",
        summary="用户真正存储的事实",
        embedding=[0.0, 1.0, 0.0],
        source_ref='["chat:2:4"]#h:render',
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
