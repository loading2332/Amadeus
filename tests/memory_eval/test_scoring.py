from dataclasses import replace

from amadeus.memory_eval.contracts import MemoryEvalTrace
from amadeus.memory_eval.scoring import aggregate_trace_scores, score_trace


def test_score_trace_scores_locomo_answer_f1_and_evidence_recall() -> None:
    trace = _trace(
        dataset_name="locomo",
        final_answer="7 May 2023",
        gold_answer="May 7, 2023",
        gold_evidence_ids=("D1:3", "D2:4"),
        retrieved_memory_ids=("conv-26:D1:3", "conv-26:D9:9"),
        scoring_spec={"metric": "locomo_qa_f1"},
    )

    scored = score_trace(trace)

    assert scored.score == 1.0
    assert scored.score_details["scorer"] == "locomo_qa_f1_approx"
    assert scored.score_details["answer_f1"] == 1.0
    assert scored.score_details["evidence_recall"] == 0.5


def test_score_trace_scores_personamem_multiple_choice_accuracy() -> None:
    trace = _trace(
        dataset_name="personamem",
        final_answer="<final_answer> Option (B) </final_answer>",
        gold_answer="(b)",
        scoring_spec={"metric": "multiple_choice_accuracy"},
    )

    scored = score_trace(trace)

    assert scored.score == 1.0
    assert scored.score_details["scorer"] == "personamem_mcq_approx"
    assert scored.score_details["predicted_options"] == ["b"]


def test_score_trace_preserves_unscored_trace_when_no_gold_answer() -> None:
    trace = _trace(
        dataset_name="example",
        final_answer="",
        gold_answer=None,
        scoring_spec={"metric": "manual"},
    )

    scored = score_trace(trace)

    assert scored.score is None
    assert scored.score_details["scorer"] == "unscored"
    assert scored.score_details["reason"] == "missing_gold_answer"


def test_aggregate_trace_scores_computes_primary_and_detail_means() -> None:
    traces = (
        replace(_trace(case_id="case-1"), score=1.0, score_details={"answer_f1": 1.0, "evidence_recall": 0.5}),
        replace(_trace(case_id="case-2"), score=0.0, score_details={"answer_f1": 0.0, "evidence_recall": 1.0}),
        replace(_trace(case_id="case-3"), score=None, score_details={"scorer": "unscored"}),
    )

    aggregate = aggregate_trace_scores(traces)

    assert aggregate["scored_count"] == 2
    assert aggregate["unscored_count"] == 1
    assert aggregate["mean_score"] == 0.5
    assert aggregate["mean_score_details"]["answer_f1"] == 0.5
    assert aggregate["mean_score_details"]["evidence_recall"] == 0.75


def _trace(
    *,
    dataset_name: str = "locomo",
    case_id: str = "case-1",
    final_answer: str = "7 May 2023",
    gold_answer: str | None = "7 May 2023",
    gold_evidence_ids: tuple[str, ...] = ("D1:3",),
    retrieved_memory_ids: tuple[str, ...] = ("conv-26:D1:3",),
    scoring_spec: dict[str, object] | None = None,
) -> MemoryEvalTrace:
    return MemoryEvalTrace(
        dataset_name=dataset_name,
        group_id="group-1",
        case_id=case_id,
        task_type="qa",
        query="When did Caroline go?",
        gold_answer=gold_answer,
        gold_evidence_ids=gold_evidence_ids,
        scoring_spec=scoring_spec or {"metric": "locomo_qa_f1"},
        memory_strategy="lexical",
        artifact_ids_seen=(),
        artifact_ids_indexed=(),
        retrieved_memory_ids=retrieved_memory_ids,
        retrieval_scores={},
        injected_memory_ids=retrieved_memory_ids,
        injected_context="",
        final_answer=final_answer,
        score=None,
        latency_ms=0.0,
        token_count=None,
        cost_estimate=None,
        strategy_trace={},
        native_payload={},
    )
