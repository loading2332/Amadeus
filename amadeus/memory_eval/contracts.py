from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class MemoryArtifact:
    artifact_id: str
    text: str
    kind: str
    source_ref: str = ""
    timestamp: str | None = None
    scope: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommonEvalCase:
    dataset_name: str
    case_id: str
    task_type: str
    query: str
    group_id: str = ""
    gold_answer: str | None = None
    gold_evidence_ids: tuple[str, ...] = ()
    memory_artifacts: tuple[MemoryArtifact, ...] = ()
    scoring_spec: dict[str, Any] = field(default_factory=dict)
    native_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryEvalGroup:
    dataset_name: str
    group_id: str
    memory_artifacts: tuple[MemoryArtifact, ...]
    cases: tuple[CommonEvalCase, ...]
    native_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryEvalDataset:
    dataset_name: str
    groups: tuple[MemoryEvalGroup, ...]
    native_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryStrategyResult:
    retrieved_memory_ids: tuple[str, ...] = ()
    retrieval_scores: dict[str, float] = field(default_factory=dict)
    injected_memory_ids: tuple[str, ...] = ()
    injected_context: str = ""
    final_answer: str = ""
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryEvalTrace:
    dataset_name: str
    group_id: str
    case_id: str
    task_type: str
    query: str
    gold_answer: str | None
    gold_evidence_ids: tuple[str, ...]
    memory_strategy: str
    artifact_ids_seen: tuple[str, ...]
    artifact_ids_indexed: tuple[str, ...]
    retrieved_memory_ids: tuple[str, ...]
    retrieval_scores: dict[str, float]
    injected_memory_ids: tuple[str, ...]
    injected_context: str
    final_answer: str
    score: float | None
    latency_ms: float
    token_count: int | None
    cost_estimate: float | None
    strategy_trace: dict[str, Any]
    native_payload: dict[str, Any]
    scoring_spec: dict[str, Any] = field(default_factory=dict)
    score_details: dict[str, Any] = field(default_factory=dict)


class MemoryStrategyAdapter(Protocol):
    strategy_name: str

    def run(self, case: CommonEvalCase) -> MemoryStrategyResult:
        """Run a fixed-artifact memory-use case and return traceable output."""
