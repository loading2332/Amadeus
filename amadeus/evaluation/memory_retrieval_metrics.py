from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import fmean
from typing import Any

from amadeus.evaluation.memory_retrieval_benchmark import RetrievalBenchmarkQuery


class UnknownRetrievalJudgmentError(ValueError):
    def __init__(self, query_id: str, memory_keys: tuple[str, ...]) -> None:
        self.query_id = query_id
        self.memory_keys = memory_keys
        super().__init__(
            f"{query_id}: formal top results contain unknown memories: "
            + ", ".join(memory_keys)
        )


@dataclass(frozen=True)
class RetrievalObservation:
    query_id: str
    final_memory_keys: tuple[str, ...]
    candidate_memory_keys: dict[str, tuple[str, ...]] = field(default_factory=dict)
    record_lanes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    hard_gate_failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryRetrievalMetrics:
    query_id: str
    family_id: str
    split: str
    product_scenario: str
    memory_capability: str
    language: str
    strata: tuple[str, ...]
    candidate_recall: dict[str, float | None]
    candidate_recall_any: dict[str, bool | None]
    candidate_recall_all: dict[str, bool | None]
    recall_at_8: float | None
    precision_at_8: float | None
    returned_precision_at_8: float | None
    mrr_at_8: float | None
    ndcg_at_8: float | None
    all_required_recalled_at_8: bool | None
    strict_lexical_only_recall_at_8: float | None
    dangerous_hit_at_8: bool
    no_answer_false_positive: bool | None
    hotness_pair_accuracy: float | None
    hard_gate_passed: bool
    hard_gate_failures: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalMetricSummary:
    family_count: int
    variant_count: int
    values: dict[str, float]


@dataclass(frozen=True)
class RetrievalAggregateReport:
    overall: RetrievalMetricSummary
    strata: dict[str, RetrievalMetricSummary]


def evaluate_retrieval_observation(
    query: RetrievalBenchmarkQuery,
    observation: RetrievalObservation,
    *,
    cutoff: int = 8,
) -> QueryRetrievalMetrics:
    if observation.query_id != query.id:
        raise ValueError(
            f"observation query {observation.query_id!r} does not match {query.id!r}"
        )
    if isinstance(cutoff, bool) or not isinstance(cutoff, int) or cutoff <= 0:
        raise ValueError("cutoff must be a positive integer")
    _require_unique(observation.final_memory_keys, label="final memory keys")
    for lane, keys in observation.candidate_memory_keys.items():
        _require_unique(keys, label=f"{lane} candidate memory keys")

    final_keys = observation.final_memory_keys[:cutoff]
    judgment_by_key = query.judgment_by_key
    unknown = tuple(sorted(set(final_keys) - set(judgment_by_key)))
    if unknown:
        raise UnknownRetrievalJudgmentError(query.id, unknown)

    relevant = query.relevant_memory_keys
    candidate_lanes = _candidate_lanes(observation.candidate_memory_keys)
    candidate_recall: dict[str, float | None] = {}
    candidate_recall_any: dict[str, bool | None] = {}
    candidate_recall_all: dict[str, bool | None] = {}
    all_targets = set(query.required_memory_keys) or relevant
    for lane, keys in candidate_lanes.items():
        candidate_set = set(keys)
        if query.expected_abstention or not relevant:
            candidate_recall[lane] = None
            candidate_recall_any[lane] = None
            candidate_recall_all[lane] = None
            continue
        candidate_recall[lane] = len(relevant & candidate_set) / len(relevant)
        candidate_recall_any[lane] = bool(relevant & candidate_set)
        candidate_recall_all[lane] = all_targets <= candidate_set

    dangerous_hit = bool(query.dangerous_memory_keys & set(final_keys))
    hard_gate_failures = tuple(dict.fromkeys(observation.hard_gate_failures))
    if dangerous_hit and "dangerous_hit" not in hard_gate_failures:
        hard_gate_failures = (*hard_gate_failures, "dangerous_hit")

    if query.expected_abstention:
        return QueryRetrievalMetrics(
            query_id=query.id,
            family_id=query.family_id,
            split=query.split,
            product_scenario=query.product_scenario,
            memory_capability=query.memory_capability,
            language=query.language,
            strata=query.strata,
            candidate_recall=candidate_recall,
            candidate_recall_any=candidate_recall_any,
            candidate_recall_all=candidate_recall_all,
            recall_at_8=None,
            precision_at_8=None,
            returned_precision_at_8=None,
            mrr_at_8=None,
            ndcg_at_8=None,
            all_required_recalled_at_8=None,
            strict_lexical_only_recall_at_8=None,
            dangerous_hit_at_8=dangerous_hit,
            no_answer_false_positive=bool(final_keys),
            hotness_pair_accuracy=_hotness_pair_accuracy(query, final_keys),
            hard_gate_passed=not hard_gate_failures,
            hard_gate_failures=hard_gate_failures,
        )

    final_set = set(final_keys)
    relevant_hits = relevant & final_set
    recall = len(relevant_hits) / len(relevant) if relevant else None
    precision = len(relevant_hits) / cutoff
    returned_precision = len(relevant_hits) / len(final_keys) if final_keys else 0.0
    first_relevant_rank = next(
        (index for index, key in enumerate(final_keys, start=1) if key in relevant),
        None,
    )
    mrr = 1.0 / first_relevant_rank if first_relevant_rank is not None else 0.0
    required = set(query.required_memory_keys)
    all_required = required <= final_set if required else None

    lexical_targets = {
        judgment.memory_key
        for judgment in query.judgments
        if judgment.relevance >= 2
        and not judgment.dangerous
        and set(judgment.expected_lanes) == {"lexical"}
    }
    strict_lexical_hits = {
        key
        for key in lexical_targets & final_set
        if set(observation.record_lanes.get(key, ())) == {"lexical"}
    }
    strict_lexical_recall = (
        len(strict_lexical_hits) / len(lexical_targets) if lexical_targets else None
    )

    return QueryRetrievalMetrics(
        query_id=query.id,
        family_id=query.family_id,
        split=query.split,
        product_scenario=query.product_scenario,
        memory_capability=query.memory_capability,
        language=query.language,
        strata=query.strata,
        candidate_recall=candidate_recall,
        candidate_recall_any=candidate_recall_any,
        candidate_recall_all=candidate_recall_all,
        recall_at_8=recall,
        precision_at_8=precision,
        returned_precision_at_8=returned_precision,
        mrr_at_8=mrr,
        ndcg_at_8=_ndcg(query, final_keys, cutoff=cutoff),
        all_required_recalled_at_8=all_required,
        strict_lexical_only_recall_at_8=strict_lexical_recall,
        dangerous_hit_at_8=dangerous_hit,
        no_answer_false_positive=None,
        hotness_pair_accuracy=_hotness_pair_accuracy(query, final_keys),
        hard_gate_passed=not hard_gate_failures,
        hard_gate_failures=hard_gate_failures,
    )


def aggregate_retrieval_metrics(
    metrics: list[QueryRetrievalMetrics],
) -> RetrievalAggregateReport:
    overall = _summarize(metrics)
    stratum_metrics: dict[str, list[QueryRetrievalMetrics]] = defaultdict(list)
    for metric in metrics:
        dimensions = {
            *metric.strata,
            f"split:{metric.split}",
            f"scenario:{metric.product_scenario}",
            f"capability:{metric.memory_capability}",
            f"language:{metric.language}",
        }
        for dimension in dimensions:
            stratum_metrics[dimension].append(metric)
    return RetrievalAggregateReport(
        overall=overall,
        strata={
            stratum: _summarize(items)
            for stratum, items in sorted(stratum_metrics.items())
        },
    )


def _summarize(metrics: list[QueryRetrievalMetrics]) -> RetrievalMetricSummary:
    by_family: dict[str, list[QueryRetrievalMetrics]] = defaultdict(list)
    for metric in metrics:
        by_family[metric.family_id].append(metric)

    family_values: dict[str, dict[str, float]] = {}
    for family_id, family_metrics in by_family.items():
        values: dict[str, list[float]] = defaultdict(list)
        for metric in family_metrics:
            for name, value in _scalar_metrics(metric).items():
                if value is not None:
                    values[name].append(float(value))
            for lane, value in metric.candidate_recall.items():
                if value is not None:
                    values[f"candidate_recall:{lane}"].append(float(value))
        family_values[family_id] = {
            name: fmean(items) for name, items in values.items() if items
        }

    metric_names = sorted(
        {name for values in family_values.values() for name in values}
    )
    overall_values = {
        name: fmean(
            values[name] for values in family_values.values() if name in values
        )
        for name in metric_names
    }
    return RetrievalMetricSummary(
        family_count=len(by_family),
        variant_count=len(metrics),
        values=overall_values,
    )


def _scalar_metrics(metric: QueryRetrievalMetrics) -> dict[str, float | bool | None]:
    return {
        "recall_at_8": metric.recall_at_8,
        "precision_at_8": metric.precision_at_8,
        "returned_precision_at_8": metric.returned_precision_at_8,
        "mrr_at_8": metric.mrr_at_8,
        "ndcg_at_8": metric.ndcg_at_8,
        "all_required_recalled_at_8": metric.all_required_recalled_at_8,
        "strict_lexical_only_recall_at_8": (
            metric.strict_lexical_only_recall_at_8
        ),
        "dangerous_hit_at_8": metric.dangerous_hit_at_8,
        "no_answer_false_positive": metric.no_answer_false_positive,
        "hotness_pair_accuracy": metric.hotness_pair_accuracy,
        "hard_gate_passed": metric.hard_gate_passed,
    }


def _candidate_lanes(
    candidate_memory_keys: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    lanes = dict(candidate_memory_keys)
    if "union" not in lanes:
        union: list[str] = []
        seen: set[str] = set()
        for keys in lanes.values():
            for key in keys:
                if key not in seen:
                    seen.add(key)
                    union.append(key)
        lanes["union"] = tuple(union)
    return lanes


def _ndcg(
    query: RetrievalBenchmarkQuery,
    final_keys: tuple[str, ...],
    *,
    cutoff: int,
) -> float:
    judgment_by_key = query.judgment_by_key
    gains = [
        0
        if judgment_by_key[key].dangerous
        else (2 ** judgment_by_key[key].relevance) - 1
        for key in final_keys[:cutoff]
    ]
    dcg = sum(
        gain / math.log2(rank + 1)
        for rank, gain in enumerate(gains, start=1)
    )
    ideal_gains = sorted(
        (
            0 if judgment.dangerous else (2**judgment.relevance) - 1
            for judgment in query.judgments
        ),
        reverse=True,
    )[:cutoff]
    ideal_dcg = sum(
        gain / math.log2(rank + 1)
        for rank, gain in enumerate(ideal_gains, start=1)
    )
    return dcg / ideal_dcg if ideal_dcg > 0.0 else 0.0


def _hotness_pair_accuracy(
    query: RetrievalBenchmarkQuery,
    final_keys: tuple[str, ...],
) -> float | None:
    if not query.hotness_pairs:
        return None
    ranks = {key: rank for rank, key in enumerate(final_keys, start=1)}
    scores: list[float] = []
    for pair in query.hotness_pairs:
        preferred_rank = ranks.get(pair.preferred_memory_key)
        other_rank = ranks.get(pair.other_memory_key)
        if preferred_rank is None:
            scores.append(0.0)
        elif other_rank is None or preferred_rank < other_rank:
            scores.append(1.0)
        else:
            scores.append(0.0)
    return fmean(scores)


def _require_unique(values: tuple[str, ...], *, label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must not contain duplicates")


def metrics_to_record(metrics: QueryRetrievalMetrics) -> dict[str, Any]:
    return {
        "query_id": metrics.query_id,
        "family_id": metrics.family_id,
        "split": metrics.split,
        "product_scenario": metrics.product_scenario,
        "memory_capability": metrics.memory_capability,
        "language": metrics.language,
        "strata": list(metrics.strata),
        "candidate_recall": dict(metrics.candidate_recall),
        "candidate_recall_any": dict(metrics.candidate_recall_any),
        "candidate_recall_all": dict(metrics.candidate_recall_all),
        **_scalar_metrics(metrics),
        "hard_gate_failures": list(metrics.hard_gate_failures),
    }
