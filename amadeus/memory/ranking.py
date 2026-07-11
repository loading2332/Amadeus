from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from amadeus.memory.engine import MemoryRecord
from amadeus.memory.source_refs import evidence_from_source_ref

_RRF_K = 60
_KEYWORD_RRF_WEIGHT = 0.5
_LEXICAL_RRF_WEIGHT = 1.0
_HOTNESS_ALPHA = 0.20
_HOTNESS_HALF_LIFE_DAYS = 14.0

_CJK_STOPWORDS = {
    "用户",
    "助手",
    "我们",
    "他们",
    "这个",
    "那个",
    "什么",
    "如何",
    "是否",
    "有没",
    "没有",
    "有过",
    "做过",
    "进行",
    "完成",
    "包括",
    "通过",
    "实现",
    "行为",
    "内容",
    "相关",
    "情况",
    "问题",
    "方式",
    "时候",
    "时间",
    "目前",
    "当前",
    "最近",
    "之前",
    "以前",
    "后来",
    "然后",
    "因为",
    "所以",
    "但是",
    "用户在",
    "用户对",
    "的行为吗",
    "进行了",
}


@dataclass(frozen=True)
class QueryPlan:
    queries: tuple[str, ...]
    memory_types: tuple[str, ...]
    use_hypotheses: bool = False


@dataclass(frozen=True)
class MemoryCandidateLanes:
    """Candidate rows kept in the lanes that actually recalled them."""

    vector_groups: tuple[tuple[dict[str, Any], ...], ...]
    lexical: tuple[dict[str, Any], ...]
    lexical_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalLaneTrace:
    candidate_counts: dict[str, int]
    lane_counts: dict[str, dict[str, int]]


def build_query_plan(
    *,
    text: str,
    intent: str,
    memory_types: tuple[str, ...],
    context: dict[str, Any],
) -> QueryPlan:
    normalized = " ".join(text.split())
    if intent == "procedure":
        return QueryPlan(
            queries=tuple(_build_procedure_queries(normalized)),
            memory_types=memory_types or ("procedure", "preference"),
        )
    raw_queries = context.get("queries")
    if intent == "context" and isinstance(raw_queries, list):
        queries = dedupe_texts([normalized, *(str(item) for item in raw_queries)])
        if queries:
            return QueryPlan(queries=tuple(queries), memory_types=memory_types)
    return QueryPlan(
        queries=(normalized,),
        memory_types=memory_types,
        use_hypotheses=intent == "answer",
    )


def rank_rows(
    rows: list[dict[str, Any]],
    query_vector: list[float],
    query_text: str,
    *,
    limit: int,
    threshold: float,
    lexical_enabled: bool = True,
) -> list[MemoryRecord]:
    terms = extract_terms(query_text) if lexical_enabled else []
    vector_scored: list[tuple[str, float]] = []
    keyword_scored: list[tuple[str, float]] = []
    semantic_scores: dict[str, float] = {}
    final_vector_scores: dict[str, float] = {}
    hotness_signals: dict[str, dict[str, float | int | str]] = {}
    row_map: dict[str, dict[str, Any]] = {}

    for row in rows:
        row_id = str(row["id"])
        row_map[row_id] = row
        semantic_score = cosine(query_vector, row["embedding"]) if query_vector else 0.0
        keyword_score = keyword_score_for_summary(row["summary"], terms)
        hotness_signal = hotness_signal_for_row(row)
        hotness_signals[row_id] = hotness_signal

        if semantic_score >= threshold:
            final_vector_score = hotness_fused_score(
                semantic_score,
                float(hotness_signal["hotness_score"]),
            )
            semantic_scores[row_id] = semantic_score
            final_vector_scores[row_id] = final_vector_score
            vector_scored.append((row_id, final_vector_score))
        if lexical_enabled and keyword_score > 0:
            keyword_scored.append((row_id, keyword_score))

    top_ids = rrf_merge(
        vector_scored,
        keyword_scored,
        row_map=row_map,
        top_n=max(1, int(limit)),
    )
    kw_scores = dict(keyword_scored)

    return [
        MemoryRecord(
            id=item_id,
            kind=str(row_map[item_id]["kind"]),
            summary=str(row_map[item_id]["summary"]),
            score=rrf_score,
            source_ref=str(row_map[item_id]["source_ref"]),
            evidence=evidence_from_source_ref(str(row_map[item_id]["source_ref"])),
            signals={
                "lanes": [
                    lane
                    for lane, score in (
                        ("vector", final_vector_scores.get(item_id, 0.0)),
                        ("lexical", kw_scores.get(item_id, 0.0)),
                    )
                    if score > 0
                ],
                "vector_score": semantic_scores.get(item_id, 0.0),
                "final_vector_score": final_vector_scores.get(item_id, 0.0),
                "lexical_score": kw_scores.get(item_id, 0.0),
                "rrf_score": rrf_score,
                "reinforcement": int(row_map[item_id].get("reinforcement") or 1),
                "emotional_weight": coerce_emotional_weight(
                    row_map[item_id].get("emotional_weight")
                ),
                "hotness_score": hotness_signals.get(item_id, {}).get(
                    "hotness_score", 0.0
                ),
                "hotness_alpha": _HOTNESS_ALPHA,
                "hotness_half_life_days": _HOTNESS_HALF_LIFE_DAYS,
                "hotness_recency": hotness_signals.get(item_id, {}).get("recency", 0.0),
                "hotness_frequency": hotness_signals.get(item_id, {}).get(
                    "frequency", 0.0
                ),
                "hotness_effective_half_life_days": hotness_signals.get(
                    item_id, {}
                ).get(
                    "effective_half_life_days",
                    _HOTNESS_HALF_LIFE_DAYS,
                ),
                "hotness_age_days": hotness_signals.get(item_id, {}).get(
                    "age_days", 0.0
                ),
                "hotness_updated_at": hotness_signals.get(item_id, {}).get(
                    "updated_at", ""
                ),
                "reinforcement_boost": reinforcement_boost(row_map[item_id]),
                "extra": dict(row_map[item_id].get("extra") or {}),
            },
        )
        for item_id, rrf_score, _boost in top_ids
        if item_id in row_map
    ]


def rank_multi_query_rows(
    rows: list[dict[str, Any]],
    query_vectors: list[list[float]],
    query_texts: list[str],
    *,
    limit: int,
    threshold: float,
) -> tuple[list[MemoryRecord], dict[str, dict[str, int]]]:
    if limit <= 0 or not query_texts:
        return [], {}

    raw_terms = extract_terms(query_texts[0])
    row_map: dict[str, dict[str, Any]] = {}
    hotness_signals: dict[str, dict[str, float | int | str]] = {}
    vector_best_scores: dict[str, float] = {}
    vector_semantic_scores: dict[str, float] = {}
    vector_query_indexes: dict[str, list[str]] = {}
    keyword_scores: dict[str, float] = {}
    lane_counts: dict[str, dict[str, int]] = {
        query_text: {"vector": 0, "lexical": 0} for query_text in query_texts
    }

    for row in rows:
        row_id = str(row["id"])
        row_map[row_id] = row
        hotness_signal = hotness_signal_for_row(row)
        hotness_signals[row_id] = hotness_signal

        keyword_score = keyword_score_for_summary(row["summary"], raw_terms)
        if keyword_score > 0:
            keyword_scores[row_id] = keyword_score
            lane_counts[query_texts[0]]["lexical"] += 1

        for query_index, query_vector in enumerate(query_vectors):
            if not query_vector:
                continue
            semantic_score = cosine(query_vector, row["embedding"])
            if semantic_score < threshold:
                continue
            final_vector_score = hotness_fused_score(
                semantic_score,
                float(hotness_signal["hotness_score"]),
            )
            lane_counts[query_texts[query_index]]["vector"] += 1
            vector_query_indexes.setdefault(row_id, []).append(str(query_index))
            current_score = vector_best_scores.get(row_id)
            if current_score is None or final_vector_score > current_score:
                vector_best_scores[row_id] = final_vector_score
                vector_semantic_scores[row_id] = semantic_score

    top_ids = rrf_merge(
        list(vector_best_scores.items()),
        list(keyword_scores.items()),
        row_map=row_map,
        top_n=max(1, int(limit)),
    )

    records = [
        MemoryRecord(
            id=item_id,
            kind=str(row_map[item_id]["kind"]),
            summary=str(row_map[item_id]["summary"]),
            score=rrf_score,
            source_ref=str(row_map[item_id]["source_ref"]),
            evidence=evidence_from_source_ref(str(row_map[item_id]["source_ref"])),
            signals={
                "lanes": [
                    lane
                    for lane, score in (
                        ("vector", vector_best_scores.get(item_id, 0.0)),
                        ("lexical", keyword_scores.get(item_id, 0.0)),
                    )
                    if score > 0
                ],
                "matched_query_indexes": vector_query_indexes.get(item_id, []),
                "vector_score": vector_semantic_scores.get(item_id, 0.0),
                "final_vector_score": vector_best_scores.get(item_id, 0.0),
                "lexical_score": keyword_scores.get(item_id, 0.0),
                "rrf_score": rrf_score,
                "reinforcement": int(row_map[item_id].get("reinforcement") or 1),
                "emotional_weight": coerce_emotional_weight(
                    row_map[item_id].get("emotional_weight")
                ),
                "hotness_score": hotness_signals.get(item_id, {}).get(
                    "hotness_score", 0.0
                ),
                "hotness_alpha": _HOTNESS_ALPHA,
                "hotness_half_life_days": _HOTNESS_HALF_LIFE_DAYS,
                "hotness_recency": hotness_signals.get(item_id, {}).get("recency", 0.0),
                "hotness_frequency": hotness_signals.get(item_id, {}).get(
                    "frequency", 0.0
                ),
                "hotness_effective_half_life_days": hotness_signals.get(
                    item_id, {}
                ).get(
                    "effective_half_life_days",
                    _HOTNESS_HALF_LIFE_DAYS,
                ),
                "hotness_age_days": hotness_signals.get(item_id, {}).get(
                    "age_days", 0.0
                ),
                "hotness_updated_at": hotness_signals.get(item_id, {}).get(
                    "updated_at", ""
                ),
                "reinforcement_boost": reinforcement_boost(row_map[item_id]),
                "extra": dict(row_map[item_id].get("extra") or {}),
            },
        )
        for item_id, rrf_score, _boost in top_ids
        if item_id in row_map
    ]
    return records, lane_counts


def rank_candidate_lanes(
    candidates: MemoryCandidateLanes,
    query_vectors: list[list[float]],
    query_texts: list[str],
    *,
    limit: int,
    threshold: float,
    lexical_weight: float = _LEXICAL_RRF_WEIGHT,
) -> tuple[list[MemoryRecord], RetrievalLaneTrace]:
    """Rank independently recalled vector and lexical candidate lanes."""

    if len(candidates.vector_groups) != len(query_texts):
        raise ValueError("vector_groups must align with query_texts")
    if len(query_vectors) != len(query_texts):
        raise ValueError("query_vectors must align with query_texts")
    if not math.isfinite(lexical_weight) or lexical_weight < 0:
        raise ValueError("lexical_weight must be a finite non-negative number")

    vector_candidate_ids = {
        row_id
        for group in candidates.vector_groups
        for row in group
        if (row_id := _candidate_id(row))
    }
    lexical_candidate_ids = {
        row_id for row in candidates.lexical if (row_id := _candidate_id(row))
    }
    lane_counts = {
        query_text: {"vector": 0, "lexical": 0} for query_text in query_texts
    }
    candidate_counts = {
        "vector": len(vector_candidate_ids),
        "lexical": len(lexical_candidate_ids),
        "union": len(vector_candidate_ids | lexical_candidate_ids),
        "final": 0,
    }

    row_map: dict[str, dict[str, Any]] = {}
    lexical_scores: dict[str, float] = {}
    for row in candidates.lexical:
        row_id = _candidate_id(row)
        if not row_id:
            continue
        row_map.setdefault(row_id, row)
        lexical_score = _finite_float(row.get("lexical_score"))
        if lexical_score is None or lexical_score <= 0:
            continue
        previous_score = lexical_scores.get(row_id)
        if previous_score is None or lexical_score > previous_score:
            lexical_scores[row_id] = lexical_score

    if query_texts:
        lane_counts[query_texts[0]]["lexical"] = len(lexical_scores)

    vector_best_scores: dict[str, float] = {}
    vector_semantic_scores: dict[str, float] = {}
    vector_query_indexes: dict[str, list[str]] = {}
    hotness_signals: dict[str, dict[str, float | int | str]] = {}
    ranking_now = datetime.now().astimezone()
    for query_index, (group, query_vector) in enumerate(
        zip(candidates.vector_groups, query_vectors, strict=True)
    ):
        group_hits: set[str] = set()
        for row in group:
            row_id = _candidate_id(row)
            if not row_id:
                continue
            row_map[row_id] = row
            semantic_score = _semantic_score_for_vector_row(row, query_vector)
            if semantic_score < threshold:
                continue

            group_hits.add(row_id)
            matched_indexes = vector_query_indexes.setdefault(row_id, [])
            query_index_text = str(query_index)
            if query_index_text not in matched_indexes:
                matched_indexes.append(query_index_text)

            row_hotness_signal = hotness_signal_for_row(row, now=ranking_now)
            final_vector_score = hotness_fused_score(
                semantic_score,
                float(row_hotness_signal["hotness_score"]),
            )
            current_score = vector_best_scores.get(row_id)
            if current_score is None or final_vector_score > current_score:
                vector_best_scores[row_id] = final_vector_score
                vector_semantic_scores[row_id] = semantic_score
                hotness_signals[row_id] = row_hotness_signal
                row_map[row_id] = row
        lane_counts[query_texts[query_index]]["vector"] = len(group_hits)

    vector_scored = list(vector_best_scores.items())
    lexical_scored = list(lexical_scores.items())
    vector_ranks = _lane_rank_map(vector_scored, row_map)
    lexical_ranks = _lane_rank_map(lexical_scored, row_map)
    top_ids = rrf_merge(
        vector_scored,
        lexical_scored,
        row_map=row_map,
        top_n=max(0, int(limit)),
        keyword_weight=lexical_weight,
    )

    records: list[MemoryRecord] = []
    for item_id, rrf_score, _boost in top_ids:
        row = row_map[item_id]
        record_hotness_signal = hotness_signals.get(item_id)
        if record_hotness_signal is None:
            record_hotness_signal = hotness_signal_for_row(row, now=ranking_now)
        vector_rank = vector_ranks.get(item_id)
        lexical_rank = lexical_ranks.get(item_id)
        vector_contribution = (
            1.0 / (_RRF_K + vector_rank) if vector_rank is not None else 0.0
        )
        lexical_contribution = (
            lexical_weight / (_RRF_K + lexical_rank)
            if lexical_rank is not None
            else 0.0
        )
        source_ref = str(row.get("source_ref") or "")
        records.append(
            MemoryRecord(
                id=item_id,
                kind=str(row.get("kind") or row.get("memory_type") or "event"),
                summary=str(row.get("summary") or ""),
                score=rrf_score,
                source_ref=source_ref,
                evidence=evidence_from_source_ref(source_ref),
                signals={
                    "lanes": [
                        lane
                        for lane, rank in (
                            ("vector", vector_rank),
                            ("lexical", lexical_rank),
                        )
                        if rank is not None
                    ],
                    "matched_query_indexes": vector_query_indexes.get(item_id, []),
                    "vector_rank": vector_rank,
                    "lexical_rank": lexical_rank,
                    "vector_rrf_contribution": vector_contribution,
                    "lexical_rrf_contribution": lexical_contribution,
                    "vector_score": vector_semantic_scores.get(item_id, 0.0),
                    "final_vector_score": vector_best_scores.get(item_id, 0.0),
                    "lexical_score": lexical_scores.get(item_id, 0.0),
                    "rrf_score": rrf_score,
                    "reinforcement": int(row.get("reinforcement") or 1),
                    "emotional_weight": coerce_emotional_weight(
                        row.get("emotional_weight")
                    ),
                    "hotness_score": record_hotness_signal.get("hotness_score", 0.0),
                    "hotness_alpha": _HOTNESS_ALPHA,
                    "hotness_half_life_days": _HOTNESS_HALF_LIFE_DAYS,
                    "hotness_recency": record_hotness_signal.get("recency", 0.0),
                    "hotness_frequency": record_hotness_signal.get("frequency", 0.0),
                    "hotness_effective_half_life_days": record_hotness_signal.get(
                        "effective_half_life_days",
                        _HOTNESS_HALF_LIFE_DAYS,
                    ),
                    "hotness_age_days": record_hotness_signal.get("age_days", 0.0),
                    "hotness_updated_at": record_hotness_signal.get("updated_at", ""),
                    "reinforcement_boost": reinforcement_boost(row),
                    "extra": dict(row.get("extra") or {}),
                },
            )
        )

    candidate_counts["final"] = len(records)
    return records, RetrievalLaneTrace(
        candidate_counts=candidate_counts,
        lane_counts=lane_counts,
    )


def trace_record(record: MemoryRecord, *, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "id": record.id,
        "kind": record.kind,
        "score": record.score,
        "source_ref": record.source_ref,
        "signals": dict(record.signals),
    }


def format_context_record(record: MemoryRecord) -> str:
    return (
        f"- [{record.id}] ({record.kind}, confidence={record.score:.3f}) "
        f"{record.summary} source_ref={record.source_ref}"
    )


def normalize_datetime(value: datetime) -> str:
    normalized = (
        value.astimezone(UTC).replace(tzinfo=None)
        if value.tzinfo
        else value.replace(tzinfo=None)
    )
    return normalized.replace(microsecond=0).isoformat()


def extract_terms(text: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_.-]{2,}", text)
    for chunk in re.findall(r"[\u4e00-\u9fff\u3040-\u30ff]{2,}", text):
        if len(chunk) <= 4:
            if chunk not in _CJK_STOPWORDS:
                terms.append(chunk)
            continue
        terms.extend(
            bigram
            for index in range(len(chunk) - 1)
            if (bigram := chunk[index : index + 2]) not in _CJK_STOPWORDS
        )
    return dedupe_texts(terms)[:20]


def dedupe_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").split())
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _candidate_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or "")


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _semantic_score_for_vector_row(
    row: dict[str, Any],
    query_vector: list[float],
) -> float:
    vector_distance = _finite_float(row.get("vector_distance"))
    if vector_distance is not None:
        return 1.0 - vector_distance
    embedding = row.get("embedding")
    if not isinstance(embedding, list):
        return 0.0
    return cosine(query_vector, embedding)


def _lane_rank_map(
    scored: list[tuple[str, float]],
    row_map: dict[str, dict[str, Any]],
) -> dict[str, int]:
    return {
        item_id: index + 1
        for index, (item_id, _score) in enumerate(
            sorted(
                scored,
                key=lambda item: (
                    -item[1],
                    -int(row_map.get(item[0], {}).get("reinforcement") or 1),
                    item[0],
                ),
            )
        )
    }


def rrf_merge(
    vector_scored: list[tuple[str, float]],
    keyword_scored: list[tuple[str, float]],
    *,
    row_map: dict[str, dict[str, Any]] | None = None,
    top_n: int,
    keyword_weight: float = _KEYWORD_RRF_WEIGHT,
) -> list[tuple[str, float, float]]:
    if top_n <= 0 or (not vector_scored and not keyword_scored):
        return []

    metadata = row_map or {}
    vec_rank: dict[str, int] = {
        item_id: index + 1
        for index, (item_id, _) in enumerate(
            sorted(
                vector_scored,
                key=lambda item: (
                    -item[1],
                    -int(metadata.get(item[0], {}).get("reinforcement") or 1),
                    item[0],
                ),
            )
        )
    }
    kw_rank: dict[str, int] = {
        item_id: index + 1
        for index, (item_id, _) in enumerate(
            sorted(
                keyword_scored,
                key=lambda item: (
                    -item[1],
                    -int(metadata.get(item[0], {}).get("reinforcement") or 1),
                    item[0],
                ),
            )
        )
    }

    all_ids = sorted(set(vec_rank) | set(kw_rank))
    scored: list[tuple[str, float, float]] = []
    for item_id in all_ids:
        rrf = 0.0
        if item_id in vec_rank:
            rrf += 1.0 / (_RRF_K + vec_rank[item_id])
        if item_id in kw_rank:
            rrf += keyword_weight / (_RRF_K + kw_rank[item_id])
        if rrf <= 0:
            continue
        scored.append((item_id, rrf, reinforcement_boost(metadata.get(item_id, {}))))

    scored.sort(key=lambda item: (-item[1], -item[2], item[0]))
    return scored[:top_n]


def reinforcement_boost(row: dict[str, Any]) -> float:
    reinforcement = max(1, int(row.get("reinforcement") or 1))
    return math.log1p(reinforcement - 1) * 0.001


def hotness_fused_score(semantic_score: float, hotness_score: float) -> float:
    return (1.0 - _HOTNESS_ALPHA) * semantic_score + _HOTNESS_ALPHA * hotness_score


def hotness_signal_for_row(
    row: dict[str, Any],
    *,
    now: datetime | None = None,
    half_life_days: float = _HOTNESS_HALF_LIFE_DAYS,
) -> dict[str, float | int | str]:
    if now is None:
        now = datetime.now().astimezone()
    updated_at_text = str(row.get("updated_at") or row.get("created_at") or "").strip()
    updated_at = parse_datetime(updated_at_text)
    reinforcement = max(0, coerce_int(row.get("reinforcement"), default=1))
    emotional_weight = coerce_emotional_weight(row.get("emotional_weight"))
    effective_half_life = max(
        half_life_days * (1.0 + 0.5 * emotional_weight / 10.0),
        0.1,
    )
    freq = 1.0 / (1.0 + math.exp(-math.log1p(reinforcement)))
    if updated_at is None:
        age_d = 0.0
        recency = 0.0
    else:
        comparable_now = now
        if updated_at.tzinfo is None and comparable_now.tzinfo is not None:
            comparable_now = comparable_now.replace(tzinfo=None)
        elif updated_at.tzinfo is not None and comparable_now.tzinfo is None:
            comparable_now = comparable_now.replace(tzinfo=updated_at.tzinfo)
        elif updated_at.tzinfo is not None and comparable_now.tzinfo is not None:
            comparable_now = comparable_now.astimezone(updated_at.tzinfo)
        age_d = max((comparable_now - updated_at).total_seconds() / 86400.0, 0.0)
        recency = math.exp(-math.log(2) / effective_half_life * age_d)
    hotness = freq * recency
    return {
        "reinforcement": reinforcement,
        "emotional_weight": emotional_weight,
        "updated_at": updated_at_text,
        "age_days": age_d,
        "frequency": freq,
        "recency": recency,
        "effective_half_life_days": effective_half_life,
        "hotness_score": hotness,
    }


def parse_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def coerce_int(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, (float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default


def coerce_emotional_weight(value: Any) -> int:
    if isinstance(value, bool) or value is None or value == "":
        return 0
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return max(0, min(10, int(value)))
    except (TypeError, ValueError):
        return 0


def record_sort_key(record: MemoryRecord) -> tuple[float, float, str]:
    boost = float(record.signals.get("reinforcement_boost", 0.0) or 0.0)
    return (-record.score, -boost, record.id)


def keyword_score_for_summary(summary: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    lowered = summary.lower()
    hits = sum(1 for term in terms if term.lower() in lowered)
    return hits / len(terms)


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / left_norm / right_norm


def content_hash(summary: str, memory_type: str) -> str:
    normalized = " ".join(summary.lower().split())
    return hashlib.sha256(f"{memory_type}:{normalized}".encode()).hexdigest()[:16]


def _build_procedure_queries(text: str) -> list[str]:
    normalized = " ".join(text.split())
    variants = [normalized]
    for prefix in ("如何", "怎么", "怎样"):
        if normalized.startswith(prefix):
            subject = normalized[len(prefix) :].strip()
            if subject:
                variants.extend((f"执行{subject}的步骤", f"{subject}流程"))
            break
    return dedupe_texts(variants)
