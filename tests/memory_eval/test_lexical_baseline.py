from amadeus.memory_eval.contracts import CommonEvalCase, MemoryArtifact, MemoryEvalGroup
from amadeus.memory_eval.harness import run_memory_use_group
from amadeus.memory_eval.strategies.lexical import LexicalMemoryStrategy


def test_lexical_strategy_retrieves_group_artifacts_by_token_overlap() -> None:
    group = MemoryEvalGroup(
        dataset_name="example",
        group_id="profile-1",
        memory_artifacts=(
            MemoryArtifact(
                artifact_id="a1",
                text="The user likes quiet museums and modern art.",
                kind="fact",
            ),
            MemoryArtifact(
                artifact_id="a2",
                text="The user dislikes crowded beaches.",
                kind="fact",
            ),
        ),
        cases=(
            CommonEvalCase(
                dataset_name="example",
                group_id="profile-1",
                case_id="case-1",
                task_type="qa",
                query="Which museum should we choose for the user?",
            ),
        ),
    )

    traces = run_memory_use_group(group, LexicalMemoryStrategy(top_k=1))

    trace = traces[0]
    assert trace.memory_strategy == "lexical"
    assert trace.retrieved_memory_ids == ("a1",)
    assert trace.injected_memory_ids == ("a1",)
    assert "quiet museums" in trace.injected_context
    assert trace.strategy_trace["prepared_group_id"] == "profile-1"


def test_lexical_strategy_replaces_index_when_preparing_next_group() -> None:
    strategy = LexicalMemoryStrategy(top_k=1)
    first_group = MemoryEvalGroup(
        dataset_name="example",
        group_id="profile-1",
        memory_artifacts=(MemoryArtifact(artifact_id="a1", text="The user likes museums.", kind="fact"),),
        cases=(
            CommonEvalCase(
                dataset_name="example",
                group_id="profile-1",
                case_id="case-1",
                task_type="qa",
                query="museum",
            ),
        ),
    )
    second_group = MemoryEvalGroup(
        dataset_name="example",
        group_id="profile-2",
        memory_artifacts=(MemoryArtifact(artifact_id="b1", text="The user likes gardens.", kind="fact"),),
        cases=(
            CommonEvalCase(
                dataset_name="example",
                group_id="profile-2",
                case_id="case-2",
                task_type="qa",
                query="gardens",
            ),
        ),
    )

    run_memory_use_group(first_group, strategy)
    traces = run_memory_use_group(second_group, strategy)

    assert traces[0].retrieved_memory_ids == ("b1",)
    assert traces[0].artifact_ids_indexed == ("b1",)
