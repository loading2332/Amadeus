from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from amadeus.memory.engine import EvidenceRef, MemoryRecord

_RRF_K = 60
_KEYWORD_RRF_WEIGHT = 0.5
_HOTNESS_ALPHA = 0.20
_HOTNESS_HALF_LIFE_DAYS = 14.0


@dataclass(frozen=True)
class QueryPlan:
    queries: tuple[str, ...]
    memory_types: tuple[str, ...]
    use_hypotheses: bool = False


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
        queries = dedupe_texts([str(item) for item in raw_queries])
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
) -> list[MemoryRecord]:
    terms = extract_terms(query_text)
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
        if keyword_score > 0:
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
                "hotness_score": hotness_signals.get(item_id, {}).get("hotness_score", 0.0),
                "hotness_alpha": _HOTNESS_ALPHA,
                "hotness_half_life_days": _HOTNESS_HALF_LIFE_DAYS,
                "hotness_recency": hotness_signals.get(item_id, {}).get("recency", 0.0),
                "hotness_frequency": hotness_signals.get(item_id, {}).get("frequency", 0.0),
                "hotness_effective_half_life_days": hotness_signals.get(item_id, {}).get(
                    "effective_half_life_days",
                    _HOTNESS_HALF_LIFE_DAYS,
                ),
                "hotness_age_days": hotness_signals.get(item_id, {}).get("age_days", 0.0),
                "hotness_updated_at": hotness_signals.get(item_id, {}).get("updated_at", ""),
                "reinforcement_boost": reinforcement_boost(row_map[item_id]),
                "extra": dict(row_map[item_id].get("extra") or {}),
            },
        )
        for item_id, rrf_score, _boost in top_ids
        if item_id in row_map
    ]


def max_pool_records(
    result_sets: list[list[MemoryRecord]],
    *,
    limit: int,
) -> list[MemoryRecord]:
    pooled: dict[str, MemoryRecord] = {}
    matched_queries: dict[str, list[str]] = {}
    for query_index, records in enumerate(result_sets):
        for record in records:
            matched_queries.setdefault(record.id, []).append(str(query_index))
            current = pooled.get(record.id)
            if current is None or record_sort_key(record) < record_sort_key(current):
                pooled[record.id] = record
    merged: list[MemoryRecord] = []
    for item_id, record in pooled.items():
        signals = dict(record.signals)
        signals["matched_query_indexes"] = matched_queries[item_id]
        merged.append(
            MemoryRecord(
                id=record.id,
                kind=record.kind,
                summary=record.summary,
                score=record.score,
                source_ref=record.source_ref,
                evidence=record.evidence,
                signals=signals,
            )
        )
    return sorted(merged, key=record_sort_key)[: max(0, limit)]


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
    stop_words = {"我", "你", "他", "她", "它", "的", "了", "过", "之前", "关于", "什么"}
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text.lower()):
        if not token or token in stop_words:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) <= 2:
                terms.append(token)
            else:
                terms.extend(token[index : index + 2] for index in range(len(token) - 1))
        else:
            terms.append(token)
    return dedupe_texts(terms)


def dedupe_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").split())
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def rrf_merge(
    vector_scored: list[tuple[str, float]],
    keyword_scored: list[tuple[str, float]],
    *,
    row_map: dict[str, dict[str, Any]] | None = None,
    top_n: int,
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
            rrf += _KEYWORD_RRF_WEIGHT / (_RRF_K + kw_rank[item_id])
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
    # Akashic hotness: bounded frequency times exponential recency decay.
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
    hits = sum(1 for term in terms if term in lowered)
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


def evidence_from_source_ref(source_ref: str) -> list[EvidenceRef]:
    refs = source_ref_message_ids(source_ref)
    if not refs:
        return []
    return [
        EvidenceRef(
            kind="session_messages",
            refs=refs,
            resolver="amadeus.session.fetch_messages",
            source_ref=source_ref,
            metadata={},
        )
    ]


def source_ref_message_ids(source_ref: str) -> list[str]:
    base = source_ref.split("#", 1)[0].strip()
    if not base:
        return []
    try:
        loaded = json.loads(base)
    except json.JSONDecodeError:
        return [base]
    if isinstance(loaded, list):
        return [str(item).strip() for item in loaded if str(item).strip()]
    text = str(loaded).strip()
    return [text] if text else []


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
