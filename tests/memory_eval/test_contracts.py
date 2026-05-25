from amadeus.memory_eval.contracts import (
    CommonEvalCase,
    MemoryArtifact,
    MemoryStrategyResult,
)


def test_common_eval_case_preserves_native_payload() -> None:
    native = {"dataset_specific": {"nested": ["keep-me"]}}

    case = CommonEvalCase(
        dataset_name="example",
        case_id="case-1",
        task_type="qa",
        query="What should be remembered?",
        gold_answer="The specific answer",
        gold_evidence_ids=("D1:3",),
        memory_artifacts=(
            MemoryArtifact(
                artifact_id="turn:D1:3",
                text="Caroline went to the LGBTQ support group on 7 May 2023.",
                kind="dialog_turn",
                source_ref="D1:3",
            ),
        ),
        scoring_spec={"metric": "f1"},
        native_payload=native,
    )

    assert case.native_payload is native
    assert case.memory_artifacts[0].source_ref == "D1:3"


def test_strategy_result_exposes_trace_and_injected_ids() -> None:
    result = MemoryStrategyResult(
        retrieved_memory_ids=("turn:D1:3",),
        injected_memory_ids=("turn:D1:3",),
        injected_context="Caroline went on 7 May 2023.",
        trace={"stage": "unit"},
    )

    assert result.trace["stage"] == "unit"
    assert result.injected_memory_ids == ("turn:D1:3",)
