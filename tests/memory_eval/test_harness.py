from amadeus.memory_eval.contracts import CommonEvalCase, MemoryArtifact
from amadeus.memory_eval.harness import run_memory_use_case
from amadeus.memory_eval.strategies.noop import NoopMemoryStrategy


def test_harness_runs_strategy_and_records_trace() -> None:
    case = CommonEvalCase(
        dataset_name="example",
        case_id="case-1",
        task_type="qa",
        query="What did the user prefer?",
        gold_answer="museums",
        memory_artifacts=(
            MemoryArtifact(
                artifact_id="a1",
                text="The user prefers museums.",
                kind="fact",
                source_ref="turn-1",
            ),
        ),
        scoring_spec={"metric": "manual"},
        native_payload={"raw": True},
    )

    trace = run_memory_use_case(case, NoopMemoryStrategy())

    assert trace.dataset_name == "example"
    assert trace.case_id == "case-1"
    assert trace.memory_strategy == "noop"
    assert trace.artifact_ids_seen == ("a1",)
    assert trace.final_answer == ""
    assert trace.score is None
    assert trace.strategy_trace["omitted_reason"] == "noop_strategy"
