from __future__ import annotations

import math
from dataclasses import replace

import pytest
from amadeus.evaluation.memory_retrieval_benchmark import (
    FixedRetrievalHypotheses,
    RetrievalBenchmarkQuery,
    RetrievalHotnessPair,
    RetrievalJudgment,
)
from amadeus.evaluation.memory_retrieval_metrics import (
    RetrievalObservation,
    UnknownRetrievalJudgmentError,
    aggregate_retrieval_metrics,
    evaluate_retrieval_observation,
)


def _query(
    *,
    judgments: tuple[RetrievalJudgment, ...] | None = None,
    expected_abstention: bool = False,
    required: tuple[str, ...] = ("a", "b"),
) -> RetrievalBenchmarkQuery:
    return RetrievalBenchmarkQuery(
        id="query-1",
        family_id="family-1",
        corpus_id="corpus-1",
        split="development",
        review_status="approved",
        review_batch=1,
        product_scenario="project_assistant",
        memory_capability="information_extraction",
        language="mixed",
        raw_query="ZXQ-4917 deployment",
        fixed_hypotheses=FixedRetrievalHypotheses(),
        strata=("mixed", "both-lanes"),
        judgments=judgments
        or (
            RetrievalJudgment("a", 3, False, "direct answer"),
            RetrievalJudgment(
                "b",
                2,
                False,
                "required support",
                expected_lanes=("lexical",),
            ),
            RetrievalJudgment("c", 1, False, "related but insufficient"),
            RetrievalJudgment(
                "d",
                1,
                True,
                "obsolete",
                danger_reasons=("superseded",),
            ),
            RetrievalJudgment("e", 0, False, "irrelevant"),
        ),
        required_memory_keys=required,
        expected_abstention=expected_abstention,
        hotness_pairs=(RetrievalHotnessPair("a", "c", "a should rank first"),),
        rationale="metric fixture",
    )


def test_metrics_distinguish_relevance_noise_danger_and_lanes() -> None:
    query = _query()
    observation = RetrievalObservation(
        query_id=query.id,
        final_memory_keys=("a", "c", "d", "b"),
        candidate_memory_keys={
            "raw-vector": ("a",),
            "lexical": ("b",),
            "union": ("a", "b", "c", "d"),
        },
        record_lanes={
            "a": ("vector",),
            "b": ("lexical",),
            "c": ("vector",),
            "d": ("lexical",),
        },
    )

    metrics = evaluate_retrieval_observation(query, observation)

    assert metrics.candidate_recall == {
        "raw-vector": 0.5,
        "lexical": 0.5,
        "union": 1.0,
    }
    assert metrics.candidate_recall_any == {
        "raw-vector": True,
        "lexical": True,
        "union": True,
    }
    assert metrics.candidate_recall_all == {
        "raw-vector": False,
        "lexical": False,
        "union": True,
    }
    assert metrics.recall_at_8 == 1.0
    assert metrics.precision_at_8 == 0.25
    assert metrics.returned_precision_at_8 == 0.5
    assert metrics.mrr_at_8 == 1.0
    expected_dcg = 7.0 + (1.0 / math.log2(3)) + (3.0 / math.log2(5))
    ideal_dcg = 7.0 + (3.0 / math.log2(3)) + (1.0 / math.log2(4))
    assert metrics.ndcg_at_8 == pytest.approx(expected_dcg / ideal_dcg)
    assert metrics.all_required_recalled_at_8 is True
    assert metrics.strict_lexical_only_recall_at_8 == 1.0
    assert metrics.dangerous_hit_at_8 is True
    assert metrics.hotness_pair_accuracy == 1.0
    assert metrics.hard_gate_passed is False
    assert metrics.hard_gate_failures == ("dangerous_hit",)


def test_unknown_top_result_requires_adjudication() -> None:
    query = _query()

    with pytest.raises(UnknownRetrievalJudgmentError) as exc_info:
        evaluate_retrieval_observation(
            query,
            RetrievalObservation(
                query_id=query.id,
                final_memory_keys=("unknown",),
            ),
        )

    assert exc_info.value.memory_keys == ("unknown",)


def test_abstention_uses_false_positive_instead_of_recall() -> None:
    query = _query(
        judgments=(RetrievalJudgment("e", 0, False, "irrelevant"),),
        expected_abstention=True,
        required=(),
    )

    metrics = evaluate_retrieval_observation(
        query,
        RetrievalObservation(query_id=query.id, final_memory_keys=("e",)),
    )

    assert metrics.recall_at_8 is None
    assert metrics.precision_at_8 is None
    assert metrics.no_answer_false_positive is True


def test_rank_eight_counts_and_rank_nine_does_not() -> None:
    judgments = tuple(
        [RetrievalJudgment(f"decoy-{index}", 0, False, "irrelevant") for index in range(8)]
        + [RetrievalJudgment("target", 3, False, "answer")]
    )
    query = _query(judgments=judgments, required=("target",))

    rank_eight = evaluate_retrieval_observation(
        query,
        RetrievalObservation(
            query_id=query.id,
            final_memory_keys=tuple(f"decoy-{index}" for index in range(7))
            + ("target",),
        ),
    )
    rank_nine = evaluate_retrieval_observation(
        query,
        RetrievalObservation(
            query_id=query.id,
            final_memory_keys=tuple(f"decoy-{index}" for index in range(8))
            + ("target",),
        ),
    )

    assert rank_eight.recall_at_8 == 1.0
    assert rank_eight.mrr_at_8 == 1.0 / 8
    assert rank_nine.recall_at_8 == 0.0
    assert rank_nine.mrr_at_8 == 0.0


def test_aggregate_metrics_weights_families_not_variant_count() -> None:
    base = evaluate_retrieval_observation(
        _query(),
        RetrievalObservation(query_id="query-1", final_memory_keys=("a", "b")),
    )
    metrics = [
        replace(base, query_id="family-1-a", recall_at_8=1.0),
        replace(base, query_id="family-1-b", recall_at_8=0.0),
        replace(
            base,
            query_id="family-2-a",
            family_id="family-2",
            recall_at_8=1.0,
        ),
    ]

    report = aggregate_retrieval_metrics(metrics)

    assert report.overall.family_count == 2
    assert report.overall.variant_count == 3
    assert report.overall.values["recall_at_8"] == 0.75
    assert report.strata["split:development"].values["recall_at_8"] == 0.75


def test_duplicate_ranked_ids_are_rejected() -> None:
    query = _query()

    with pytest.raises(ValueError, match="duplicates"):
        evaluate_retrieval_observation(
            query,
            RetrievalObservation(
                query_id=query.id,
                final_memory_keys=("a", "a"),
            ),
        )


def test_empty_result_is_an_explicit_zero_not_a_missing_metric() -> None:
    query = _query()

    metrics = evaluate_retrieval_observation(
        query,
        RetrievalObservation(query_id=query.id, final_memory_keys=()),
    )

    assert metrics.recall_at_8 == 0.0
    assert metrics.precision_at_8 == 0.0
    assert metrics.returned_precision_at_8 == 0.0
    assert metrics.mrr_at_8 == 0.0
    assert metrics.all_required_recalled_at_8 is False
