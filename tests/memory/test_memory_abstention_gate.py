from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from amadeus.memory.engine import MemoryRecallRequest
from amadeus.memory.retrieval_parameters import MemoryRetrievalParameters
from amadeus.memory.retriever import MemoryRetriever

from tests.db.pgvector_helpers import pad_embedding


class FixedEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return pad_embedding([1.0, 0.0, 0.0])


class FailingEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


def _vector_row(item_id: str, *, distance: float) -> dict[str, object]:
    return {
        "id": item_id,
        "memory_type": "event",
        "summary": f"记忆内容 {item_id}",
        "vector_distance": distance,
        "source_ref": f'["session:1:1:1"]#h:{item_id}',
        "extra": {},
        "reinforcement": 1,
        "emotional_weight": 0,
        "updated_at": "2026-07-11T00:00:00",
    }


def _lexical_row(item_id: str, *, lexical_score: float = 1.0) -> dict[str, object]:
    return {
        "id": item_id,
        "memory_type": "event",
        "summary": f"部署标识 {item_id}",
        "embedding": None,
        "source_ref": f'["session:1:1:2"]#h:{item_id}',
        "extra": {},
        "reinforcement": 1,
        "emotional_weight": 0,
        "updated_at": "2026-07-11T00:00:00",
        "lexical_score": lexical_score,
    }


class ThreeBandVectorStore:
    """Vector-only rows at semantic scores 0.90 / 0.60 / 0.40."""

    def search_vector_candidates(self, **kwargs):
        return [
            _vector_row("confident-item", distance=0.10),
            _vector_row("gray-item", distance=0.40),
            _vector_row("weak-item", distance=0.60),
        ]

    def search_lexical_candidates(self, **kwargs):
        return []


class WeakOnlyVectorStore:
    def search_vector_candidates(self, **kwargs):
        return [
            _vector_row("weak-a", distance=0.60),
            _vector_row("weak-b", distance=0.62),
        ]

    def search_lexical_candidates(self, **kwargs):
        return []


class BoundaryVectorStore:
    """Vector-only rows exactly at confident (0.75) and floor (0.50)."""

    def search_vector_candidates(self, **kwargs):
        return [
            _vector_row("at-confident", distance=0.25),
            _vector_row("at-floor", distance=0.50),
        ]

    def search_lexical_candidates(self, **kwargs):
        return []


class LexicalOnlyStore:
    def search_vector_candidates(self, **kwargs):
        raise AssertionError("vector search must not run without an embedding")

    def search_lexical_candidates(self, **kwargs):
        return [_lexical_row("lexical-target")]


def _gated_parameters(
    floor: float = 0.5,
    confident: float = 0.8,
) -> MemoryRetrievalParameters:
    return MemoryRetrievalParameters(
        abstention_semantic_floor=floor,
        abstention_confident_semantic=confident,
    )


def _recall(
    store,
    *,
    parameters: MemoryRetrievalParameters | None = None,
    intent: str = "answer",
    embedding_provider=None,
):
    retriever = MemoryRetriever(
        store=store,
        embedding_provider=embedding_provider or FixedEmbeddingProvider(),
        parameters=parameters,
    )
    return asyncio.run(
        retriever.recall(MemoryRecallRequest(text="记忆检索", intent=intent, limit=8))
    )


def test_zero_floor_disables_gate_and_keeps_pre_gate_behavior() -> None:
    result = _recall(
        ThreeBandVectorStore(),
        parameters=_gated_parameters(floor=0.0, confident=1.0),
    )

    assert [record.id for record in result.records] == [
        "confident-item",
        "gray-item",
        "weak-item",
    ]
    assert all("uncertain" not in record.signals for record in result.records)
    assert result.trace["record_count"] == 3
    assert result.trace["abstention"] == {
        "enabled": False,
        "outcome": "disabled",
        "reason": "disabled",
        "top_semantic": 0.9,
        "dropped_count": 0,
        "uncertain_count": 0,
        "lexical_anchor_count": 0,
        "semantic_floor": 0.0,
        "confident_semantic": 1.0,
    }


def test_default_parameters_enable_calibrated_gate() -> None:
    result = _recall(ThreeBandVectorStore())

    assert [record.id for record in result.records] == [
        "confident-item",
        "gray-item",
    ]
    assert result.trace["abstention"]["enabled"] is True
    assert result.trace["abstention"]["semantic_floor"] == 0.5
    assert result.trace["abstention"]["confident_semantic"] == 0.7


def test_records_below_floor_without_lexical_source_are_dropped() -> None:
    result = _recall(ThreeBandVectorStore(), parameters=_gated_parameters())

    assert [record.id for record in result.records] == [
        "confident-item",
        "gray-item",
    ]
    gate = result.trace["abstention"]
    assert gate["enabled"] is True
    assert gate["outcome"] == "partial"
    assert gate["reason"] == "below_floor"
    assert gate["dropped_count"] == 1
    assert gate["top_semantic"] == 0.9
    assert gate["lexical_anchor_count"] == 0
    assert gate["semantic_floor"] == 0.5
    assert gate["confident_semantic"] == 0.8
    assert result.trace["record_count"] == 2


def test_gray_band_records_are_kept_with_uncertain_signal() -> None:
    result = _recall(ThreeBandVectorStore(), parameters=_gated_parameters())

    by_id = {record.id: record for record in result.records}
    assert by_id["gray-item"].signals["uncertain"] is True
    assert "uncertain" not in by_id["confident-item"].signals
    assert result.trace["abstention"]["uncertain_count"] == 1


def test_boundary_scores_belong_to_upper_bands() -> None:
    """score == confident 归高置信带；score == floor 归灰区带（两界均为闭下界）。"""
    result = _recall(
        BoundaryVectorStore(),
        parameters=_gated_parameters(floor=0.5, confident=0.75),
    )

    by_id = {record.id: record for record in result.records}
    assert set(by_id) == {"at-confident", "at-floor"}
    assert by_id["at-confident"].signals["vector_score"] == 0.75
    assert by_id["at-floor"].signals["vector_score"] == 0.5
    assert "uncertain" not in by_id["at-confident"].signals
    assert by_id["at-floor"].signals["uncertain"] is True
    gate = result.trace["abstention"]
    assert gate["outcome"] == "pass"
    assert gate["dropped_count"] == 0
    assert gate["uncertain_count"] == 1


def test_lexical_source_bypasses_floor_even_with_low_vector_score() -> None:
    result = _recall(
        LexicalOnlyStore(),
        parameters=_gated_parameters(),
        embedding_provider=FailingEmbeddingProvider(),
    )

    assert [record.id for record in result.records] == ["lexical-target"]
    record = result.records[0]
    assert record.signals["lanes"] == ["lexical"]
    assert record.signals["vector_score"] < 0.5
    assert "uncertain" not in record.signals
    gate = result.trace["abstention"]
    assert gate["outcome"] == "pass"
    assert gate["dropped_count"] == 0
    assert gate["uncertain_count"] == 0


def test_all_records_below_floor_returns_empty_records() -> None:
    result = _recall(WeakOnlyVectorStore(), parameters=_gated_parameters())

    assert result.records == []
    gate = result.trace["abstention"]
    assert gate["outcome"] == "all_dropped"
    assert gate["reason"] == "below_floor"
    assert gate["dropped_count"] == 2
    assert gate["top_semantic"] == 0.4
    assert gate["uncertain_count"] == 0
    assert result.trace["record_count"] == 0


def test_non_answer_intent_is_exempt_from_gate() -> None:
    result = _recall(
        ThreeBandVectorStore(),
        parameters=_gated_parameters(),
        intent="context",
    )

    assert [record.id for record in result.records] == [
        "confident-item",
        "gray-item",
        "weak-item",
    ]
    assert all("uncertain" not in record.signals for record in result.records)
    gate = result.trace["abstention"]
    assert gate["outcome"] == "intent_exempt"
    assert gate["reason"] == "intent_exempt"
    assert gate["dropped_count"] == 0
    assert gate["uncertain_count"] == 0


@pytest.mark.parametrize(
    ("floor", "confident"),
    [
        (-0.1, 1.0),
        (1.1, 1.0),
        (0.5, -0.1),
        (0.5, 1.1),
        (0.6, 0.5),
    ],
)
def test_abstention_parameters_reject_invalid_values(
    floor: float,
    confident: float,
) -> None:
    with pytest.raises(ValueError):
        replace(
            MemoryRetrievalParameters(),
            abstention_semantic_floor=floor,
            abstention_confident_semantic=confident,
        )


def test_uncertain_records_render_with_annotation() -> None:
    retriever = MemoryRetriever(
        store=ThreeBandVectorStore(),
        embedding_provider=FixedEmbeddingProvider(),
        parameters=_gated_parameters(),
    )

    result = asyncio.run(
        retriever.build_context(
            MemoryRecallRequest(text="记忆检索", intent="answer", limit=8)
        )
    )

    lines = result.text.splitlines()
    gray_lines = [line for line in lines if "gray-item" in line]
    confident_lines = [line for line in lines if "confident-item" in line]
    assert len(gray_lines) == 1
    assert gray_lines[0].endswith("（可能相关，不确定）")
    assert len(confident_lines) == 1
    assert "（可能相关，不确定）" not in confident_lines[0]
    assert result.text.count("（可能相关，不确定）") == 1
