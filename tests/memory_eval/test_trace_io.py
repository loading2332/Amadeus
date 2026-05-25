from pathlib import Path

from amadeus.memory_eval.contracts import MemoryEvalTrace
from amadeus.memory_eval.trace_io import load_trace_jsonl, write_trace_jsonl


def test_trace_jsonl_round_trips_trace_records(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    trace = MemoryEvalTrace(
        dataset_name="example",
        group_id="group-1",
        case_id="case-1",
        task_type="qa",
        query="What does the user prefer?",
        gold_answer="museums",
        gold_evidence_ids=("turn-1",),
        memory_strategy="baseline",
        artifact_ids_seen=("turn-1", "turn-2"),
        artifact_ids_indexed=("turn-1", "turn-2"),
        retrieved_memory_ids=("turn-1",),
        retrieval_scores={"turn-1": 0.75},
        injected_memory_ids=("turn-1",),
        injected_context="user: I prefer museums.",
        final_answer="museums",
        score=1.0,
        scoring_spec={"metric": "manual"},
        score_details={"answer_f1": 1.0, "scorer": "unit"},
        latency_ms=12.5,
        token_count=42,
        cost_estimate=0.001,
        strategy_trace={"ranked_ids": ["turn-1"]},
        native_payload={"raw": True},
    )

    write_trace_jsonl(path, [trace])

    lines = path.read_text(encoding="utf-8").splitlines()
    loaded = list(load_trace_jsonl(path))
    assert len(lines) == 1
    assert loaded == [trace]


def test_trace_jsonl_can_append_records(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    first = _trace("case-1")
    second = _trace("case-2")

    write_trace_jsonl(path, [first])
    write_trace_jsonl(path, [second], append=True)

    assert [trace.case_id for trace in load_trace_jsonl(path)] == ["case-1", "case-2"]


def _trace(case_id: str) -> MemoryEvalTrace:
    return MemoryEvalTrace(
        dataset_name="example",
        group_id="group-1",
        case_id=case_id,
        task_type="qa",
        query="What does the user prefer?",
        gold_answer=None,
        gold_evidence_ids=(),
        memory_strategy="baseline",
        artifact_ids_seen=(),
        artifact_ids_indexed=(),
        retrieved_memory_ids=(),
        retrieval_scores={},
        injected_memory_ids=(),
        injected_context="",
        final_answer="",
        score=None,
        scoring_spec={},
        score_details={},
        latency_ms=0.0,
        token_count=None,
        cost_estimate=None,
        strategy_trace={},
        native_payload={},
    )
