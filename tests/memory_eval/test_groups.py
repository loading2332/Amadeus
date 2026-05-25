from amadeus.memory_eval.contracts import (
    CommonEvalCase,
    MemoryArtifact,
    MemoryEvalDataset,
    MemoryEvalGroup,
    MemoryStrategyResult,
)
from amadeus.memory_eval.harness import run_memory_use_group


def test_memory_eval_group_collects_shared_artifacts_once() -> None:
    group = MemoryEvalGroup(
        dataset_name="example",
        group_id="conversation-1",
        memory_artifacts=(
            MemoryArtifact(
                artifact_id="turn-1",
                text="The user prefers museums.",
                kind="dialog_turn",
            ),
        ),
        cases=(
            CommonEvalCase(
                dataset_name="example",
                group_id="conversation-1",
                case_id="case-1",
                task_type="qa",
                query="What does the user prefer?",
            ),
        ),
    )
    dataset = MemoryEvalDataset(dataset_name="example", groups=(group,))

    assert dataset.groups[0].group_id == "conversation-1"
    assert dataset.groups[0].cases[0].memory_artifacts == ()


def test_group_harness_prepares_once_and_runs_each_case() -> None:
    strategy = RecordingGroupStrategy()
    group = MemoryEvalGroup(
        dataset_name="example",
        group_id="conversation-1",
        memory_artifacts=(
            MemoryArtifact(
                artifact_id="turn-1",
                text="The user prefers museums.",
                kind="dialog_turn",
            ),
        ),
        cases=(
            CommonEvalCase(
                dataset_name="example",
                group_id="conversation-1",
                case_id="case-1",
                task_type="qa",
                query="What does the user prefer?",
            ),
            CommonEvalCase(
                dataset_name="example",
                group_id="conversation-1",
                case_id="case-2",
                task_type="qa",
                query="Where should we go?",
            ),
        ),
    )

    traces = run_memory_use_group(group, strategy)

    assert strategy.prepared_group_ids == ["conversation-1"]
    assert strategy.run_calls == [
        ("conversation-1", "case-1", ()),
        ("conversation-1", "case-2", ()),
    ]
    assert len(traces) == 2
    assert traces[0].group_id == "conversation-1"
    assert traces[0].artifact_ids_seen == ("turn-1",)
    assert traces[0].artifact_ids_indexed == ("turn-1",)
    assert traces[0].retrieved_memory_ids == ("turn-1",)


def test_group_harness_falls_back_for_case_only_strategies() -> None:
    strategy = RecordingCaseOnlyStrategy()
    group = MemoryEvalGroup(
        dataset_name="example",
        group_id="conversation-1",
        memory_artifacts=(
            MemoryArtifact(
                artifact_id="turn-1",
                text="The user prefers museums.",
                kind="dialog_turn",
            ),
        ),
        cases=(
            CommonEvalCase(
                dataset_name="example",
                group_id="conversation-1",
                case_id="case-1",
                task_type="qa",
                query="What does the user prefer?",
            ),
        ),
    )

    traces = run_memory_use_group(group, strategy)

    assert strategy.run_calls == [("conversation-1", "case-1", ("turn-1",))]
    assert traces[0].group_id == "conversation-1"
    assert traces[0].artifact_ids_indexed == ("turn-1",)


class RecordingGroupStrategy:
    strategy_name = "recording-group"

    def __init__(self) -> None:
        self.prepared_group_ids: list[str] = []
        self.indexed_ids: tuple[str, ...] = ()
        self.run_calls: list[tuple[str, str, tuple[str, ...]]] = []

    def prepare_group(self, group: MemoryEvalGroup) -> None:
        self.prepared_group_ids.append(group.group_id)
        self.indexed_ids = tuple(artifact.artifact_id for artifact in group.memory_artifacts)

    def run(self, case: CommonEvalCase) -> MemoryStrategyResult:
        self.run_calls.append(
            (
                case.group_id,
                case.case_id,
                tuple(artifact.artifact_id for artifact in case.memory_artifacts),
            )
        )
        return MemoryStrategyResult(
            retrieved_memory_ids=self.indexed_ids[:1],
            injected_memory_ids=self.indexed_ids[:1],
            trace={"group_id": case.group_id},
        )


class RecordingCaseOnlyStrategy:
    strategy_name = "recording-case-only"

    def __init__(self) -> None:
        self.run_calls: list[tuple[str, str, tuple[str, ...]]] = []

    def run(self, case: CommonEvalCase) -> MemoryStrategyResult:
        artifact_ids = tuple(artifact.artifact_id for artifact in case.memory_artifacts)
        self.run_calls.append((case.group_id, case.case_id, artifact_ids))
        return MemoryStrategyResult(retrieved_memory_ids=artifact_ids[:1])
