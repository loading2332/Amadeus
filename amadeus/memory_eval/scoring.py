from __future__ import annotations

import re
import string
from collections import Counter, defaultdict
from dataclasses import replace
from typing import Any

from .contracts import MemoryEvalTrace


def score_trace(trace: MemoryEvalTrace) -> MemoryEvalTrace:
    if trace.gold_answer is None:
        return replace(
            trace,
            score=None,
            score_details={"scorer": "unscored", "reason": "missing_gold_answer"},
        )

    metric = str(trace.scoring_spec.get("metric", ""))
    if trace.dataset_name == "personamem" or metric == "multiple_choice_accuracy":
        return _score_personamem(trace)
    if trace.dataset_name == "locomo" or metric == "locomo_qa_f1":
        return _score_locomo(trace)
    return _score_basic_answer(trace)


def score_traces(traces: tuple[MemoryEvalTrace, ...]) -> tuple[MemoryEvalTrace, ...]:
    return tuple(score_trace(trace) for trace in traces)


def aggregate_trace_scores(traces: tuple[MemoryEvalTrace, ...]) -> dict[str, Any]:
    scored = [trace for trace in traces if trace.score is not None]
    detail_values: dict[str, list[float]] = defaultdict(list)
    for trace in scored:
        for key, value in trace.score_details.items():
            if isinstance(value, bool):
                detail_values[key].append(1.0 if value else 0.0)
            elif isinstance(value, (int, float)):
                detail_values[key].append(float(value))

    return {
        "trace_count": len(traces),
        "scored_count": len(scored),
        "unscored_count": len(traces) - len(scored),
        "mean_score": _mean([float(trace.score) for trace in scored]),
        "mean_score_details": {
            key: _mean(values)
            for key, values in sorted(detail_values.items())
            if values
        },
    }


def _score_locomo(trace: MemoryEvalTrace) -> MemoryEvalTrace:
    answer_f1 = _answer_f1(trace.final_answer, trace.gold_answer or "")
    evidence_recall = _evidence_recall(trace.retrieved_memory_ids, trace.gold_evidence_ids)
    exact_match = _normalized_answer(trace.final_answer) == _normalized_answer(trace.gold_answer or "")
    return replace(
        trace,
        score=answer_f1,
        score_details={
            "scorer": "locomo_qa_f1_approx",
            "answer_f1": answer_f1,
            "exact_match": exact_match,
            "evidence_recall": evidence_recall,
        },
    )


def _score_personamem(trace: MemoryEvalTrace) -> MemoryEvalTrace:
    predicted_options = _extract_options(trace.final_answer)
    gold_options = _extract_options(trace.gold_answer or "")
    is_correct = bool(predicted_options) and predicted_options == gold_options
    return replace(
        trace,
        score=1.0 if is_correct else 0.0,
        score_details={
            "scorer": "personamem_mcq_approx",
            "accuracy": 1.0 if is_correct else 0.0,
            "predicted_options": sorted(predicted_options),
            "gold_options": sorted(gold_options),
        },
    )


def _score_basic_answer(trace: MemoryEvalTrace) -> MemoryEvalTrace:
    answer_f1 = _answer_f1(trace.final_answer, trace.gold_answer or "")
    exact_match = _normalized_answer(trace.final_answer) == _normalized_answer(trace.gold_answer or "")
    return replace(
        trace,
        score=answer_f1,
        score_details={
            "scorer": "basic_answer_f1_approx",
            "answer_f1": answer_f1,
            "exact_match": exact_match,
        },
    )


def _answer_f1(prediction: str, gold_answer: str) -> float:
    prediction_tokens = _normalized_answer(prediction).split()
    gold_tokens = _normalized_answer(gold_answer).split()
    if not prediction_tokens or not gold_tokens:
        return 0.0
    common = Counter(prediction_tokens) & Counter(gold_tokens)
    same = sum(common.values())
    if same == 0:
        return 0.0
    precision = same / len(prediction_tokens)
    recall = same / len(gold_tokens)
    return (2 * precision * recall) / (precision + recall)


def _evidence_recall(retrieved_memory_ids: tuple[str, ...], gold_evidence_ids: tuple[str, ...]) -> float | None:
    if not gold_evidence_ids:
        return None
    retrieved_refs = {_source_ref(memory_id) for memory_id in retrieved_memory_ids}
    gold_refs = set(gold_evidence_ids)
    return len(gold_refs & retrieved_refs) / len(gold_refs)


def _source_ref(memory_id: str) -> str:
    if ":" not in memory_id:
        return memory_id
    return memory_id.rsplit(":", 1)[-1] if memory_id.count(":") == 1 else ":".join(memory_id.split(":")[-2:])


def _extract_options(text: str) -> set[str]:
    lowered = text.lower()
    in_parens = set(re.findall(r"\(([a-d])\)", lowered))
    if in_parens:
        return in_parens
    return set(re.findall(r"\b([a-d])\b", lowered))


def _normalized_answer(text: str) -> str:
    lowered = text.lower().replace(",", "")
    no_punc = "".join(ch for ch in lowered if ch not in string.punctuation)
    without_articles = re.sub(r"\b(a|an|the|and)\b", " ", no_punc)
    return " ".join(without_articles.split())


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
