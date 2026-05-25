from __future__ import annotations

from dataclasses import replace
from time import perf_counter

from .contracts import (
    CommonEvalCase,
    MemoryArtifact,
    MemoryEvalGroup,
    MemoryEvalTrace,
    MemoryStrategyAdapter,
)


def run_memory_use_case(
    case: CommonEvalCase,
    strategy: MemoryStrategyAdapter,
) -> MemoryEvalTrace:
    return _run_memory_use_case(
        case=case,
        strategy=strategy,
        indexed_artifacts=case.memory_artifacts,
    )


def run_memory_use_group(
    group: MemoryEvalGroup,
    strategy: MemoryStrategyAdapter,
) -> tuple[MemoryEvalTrace, ...]:
    prepare_group = getattr(strategy, "prepare_group", None)
    prepared = callable(prepare_group)
    if prepared:
        prepare_group(group)

    traces: list[MemoryEvalTrace] = []
    for case in group.cases:
        grouped_case = replace(case, group_id=case.group_id or group.group_id)
        if not prepared and not grouped_case.memory_artifacts:
            grouped_case = replace(grouped_case, memory_artifacts=group.memory_artifacts)
        traces.append(
            _run_memory_use_case(
                case=grouped_case,
                strategy=strategy,
                indexed_artifacts=group.memory_artifacts,
            )
        )
    return tuple(traces)


def _run_memory_use_case(
    *,
    case: CommonEvalCase,
    strategy: MemoryStrategyAdapter,
    indexed_artifacts: tuple[MemoryArtifact, ...],
) -> MemoryEvalTrace:
    started = perf_counter()
    result = strategy.run(case)
    latency_ms = (perf_counter() - started) * 1000

    return MemoryEvalTrace(
        dataset_name=case.dataset_name,
        group_id=case.group_id,
        case_id=case.case_id,
        task_type=case.task_type,
        query=case.query,
        gold_answer=case.gold_answer,
        gold_evidence_ids=case.gold_evidence_ids,
        memory_strategy=strategy.strategy_name,
        artifact_ids_seen=tuple(artifact.artifact_id for artifact in indexed_artifacts),
        artifact_ids_indexed=tuple(artifact.artifact_id for artifact in indexed_artifacts),
        retrieved_memory_ids=result.retrieved_memory_ids,
        retrieval_scores=result.retrieval_scores,
        injected_memory_ids=result.injected_memory_ids,
        injected_context=result.injected_context,
        final_answer=result.final_answer,
        score=None,
        latency_ms=latency_ms,
        token_count=None,
        cost_estimate=None,
        strategy_trace=result.trace,
        native_payload=case.native_payload,
        scoring_spec=case.scoring_spec,
    )
