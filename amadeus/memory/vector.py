from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import sqlite3
import threading
from datetime import UTC
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from openai import AsyncOpenAI

from amadeus.memory.engine import (
    EvidenceRef,
    MemoryIngestRequest,
    MemoryIngestResult,
    MemoryMutation,
    MemoryMutationResult,
    MemoryQuery,
    MemoryQueryResult,
    MemoryRecord,
)

_TIME_PREFIX_RE = re.compile(
    r"^\[(?P<date>\d{4}-\d{2}-\d{2})(?:[ T](?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?)?\]"
)


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class HypothesisProvider(Protocol):
    async def generate(self, query: str, *, style: str) -> str: ...


@dataclass(frozen=True)
class LLMHypothesisProvider:
    provider: Any
    model: str | None = None

    async def generate(self, query: str, *, style: str) -> str:
        instruction = (
            "把查询改写成一条可能存在于历史记忆中的具体事件陈述。"
            if style == "event"
            else "把查询改写成一条语义完整、便于检索的用户事实陈述。"
        )
        response = await self.provider.chat(
            [
                {
                    "role": "user",
                    "content": f"{instruction}\n只输出陈述句，不要解释。\n查询：{query}",
                }
            ],
            model=self.model,
            max_tokens=80,
            tools=[],
            disable_thinking=True,
        )
        return str(response.content or "").strip()


@dataclass(frozen=True)
class _QueryPlan:
    queries: tuple[str, ...]
    kinds: tuple[str, ...]
    use_hypotheses: bool = False


@dataclass(frozen=True)
class OpenAIEmbeddingConfig:
    api_key: str
    model: str
    base_url: str | None = None
    timeout_seconds: float = 90


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        config: OpenAIEmbeddingConfig,
        *,
        client: Any | None = None,
    ) -> None:
        self.config = config
        self._client = client or AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self.config.model,
            input=text,
        )
        return list(response.data[0].embedding)


class VectorMemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    happened_at TEXT,
                    extra_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'active',
                    reinforcement INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(content_hash, kind),
                    UNIQUE(source_ref, kind)
                );
                CREATE INDEX IF NOT EXISTS ix_memory_items_status
                    ON memory_items(status);
                CREATE INDEX IF NOT EXISTS ix_memory_items_kind
                    ON memory_items(kind);
                """
            )
            self._conn.commit()

    def upsert_item(
        self,
        *,
        kind: str,
        summary: str,
        embedding: list[float],
        source_ref: str,
        happened_at: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        normalized_kind = kind.strip() or "event"
        text = summary.strip()
        src = source_ref.strip()
        if not text or not src:
            return "", "skipped"
        now = datetime.now().astimezone().isoformat()
        digest = _content_hash(text, normalized_kind)
        item_id = f"mem_{digest}"
        payload = json.dumps([float(value) for value in embedding])
        extra_json = json.dumps(extra or {}, ensure_ascii=False)
        normalized_happened_at = _normalize_timestamp(happened_at)
        with self._lock:
            existing_source = self._conn.execute(
                """
                SELECT id
                FROM memory_items
                WHERE source_ref = ? AND kind = ?
                """,
                (src, normalized_kind),
            ).fetchone()
            if existing_source is not None:
                return str(existing_source["id"]), "skipped"

            existing_hash = self._conn.execute(
                """
                SELECT id
                FROM memory_items
                WHERE content_hash = ? AND kind = ?
                """,
                (digest, normalized_kind),
            ).fetchone()
            if existing_hash is not None:
                reinforced_id = str(existing_hash["id"])
                self._conn.execute(
                    """
                    UPDATE memory_items
                    SET reinforcement = reinforcement + 1,
                        updated_at = ?,
                        happened_at = COALESCE(NULLIF(happened_at, ''), ?)
                    WHERE id = ?
                    """,
                    (now, normalized_happened_at, reinforced_id),
                )
                self._conn.commit()
                return reinforced_id, "reinforced"

            self._conn.execute(
                """
                INSERT INTO memory_items (
                    id, kind, summary, content_hash, embedding, source_ref,
                    happened_at, extra_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    normalized_kind,
                    text,
                    digest,
                    payload,
                    src,
                    normalized_happened_at,
                    extra_json,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return item_id, "new"

    def list_active(
        self,
        *,
        kinds: tuple[str, ...] = (),
        time_start: datetime | None = None,
        time_end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["status = 'active'"]
        params: list[Any] = []
        clean_kinds = tuple(kind.strip() for kind in kinds if kind.strip())
        if clean_kinds:
            placeholders = ",".join("?" for _ in clean_kinds)
            clauses.append(f"kind IN ({placeholders})")
            params.extend(clean_kinds)
        if time_start is not None:
            clauses.append("happened_at IS NOT NULL")
            clauses.append("datetime(happened_at) >= datetime(?)")
            params.append(_normalize_datetime(time_start))
        if time_end is not None:
            clauses.append("happened_at IS NOT NULL")
            clauses.append("datetime(happened_at) <= datetime(?)")
            params.append(_normalize_datetime(time_end))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT *
                FROM memory_items
                WHERE {" AND ".join(clauses)}
                ORDER BY updated_at DESC
                """,
                tuple(params),
            ).fetchall()
        return [_row_to_item(row) for row in rows]

    def get_items_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT *
                FROM memory_items
                WHERE id IN ({placeholders})
                ORDER BY updated_at DESC
                """,
                tuple(ids),
            ).fetchall()
        found = {_row_to_item(row)["id"]: _row_to_item(row) for row in rows}
        return [found[item_id] for item_id in ids if item_id in found]

    def get_item_by_id(self, item_id: str) -> dict[str, Any] | None:
        rows = self.get_items_by_ids([item_id])
        return rows[0] if rows else None

    def mark_superseded_batch(
        self,
        ids: list[str],
        *,
        replacement_id: str | None = None,
        reason: str = "forget",
    ) -> None:
        if not ids:
            return
        now = datetime.now().astimezone().isoformat()
        indexed = {item["id"]: item for item in self.get_items_by_ids(ids)}
        payloads: list[tuple[str, str, str]] = []
        for item_id in ids:
            item = indexed.get(item_id)
            if item is None:
                continue
            extra = dict(item.get("extra") or {})
            extra.update(
                {
                    "superseded_reason": reason,
                    "replacement_id": replacement_id,
                    "superseded_at": now,
                }
            )
            payloads.append((now, json.dumps(extra, ensure_ascii=False), item_id))
        if not payloads:
            return
        with self._lock:
            self._conn.executemany(
                """
                UPDATE memory_items
                SET status = 'superseded',
                    updated_at = ?,
                    extra_json = ?
                WHERE id = ?
                """,
                payloads,
            )
            self._conn.commit()


class VectorMemoryEngine:
    def __init__(
        self,
        *,
        store: VectorMemoryStore,
        embedding_provider: EmbeddingProvider,
        hypothesis_provider: HypothesisProvider | None = None,
        score_threshold: float = 0.35,
        top_k: int = 8,
        context_char_budget: int = 4_000,
    ) -> None:
        self.store = store
        self.embedding_provider = embedding_provider
        self.hypothesis_provider = hypothesis_provider
        self.score_threshold = float(score_threshold)
        self.top_k = max(1, int(top_k))
        self.context_char_budget = max(0, int(context_char_budget))

    async def ingest(self, request: MemoryIngestRequest) -> MemoryIngestResult:
        summary = request.summary.strip()
        source_ref = request.source_ref.strip()
        if not summary or not source_ref:
            return MemoryIngestResult(status="skipped", trace={"reason": "empty_input"})
        embedding = await self.embedding_provider.embed(summary)
        item_id, status = self.store.upsert_item(
            kind=request.kind,
            summary=summary,
            embedding=embedding,
            source_ref=source_ref,
            happened_at=request.happened_at or parse_history_entry_happened_at(summary),
            extra=request.extra,
        )
        return MemoryIngestResult(item_id=item_id or None, status=status)

    async def query(self, query: MemoryQuery) -> MemoryQueryResult:
        text = query.text.strip()
        if not text:
            return MemoryQueryResult(trace={"reason": "empty_query"})
        plan = _build_query_plan(query)
        queries = list(plan.queries)
        fallbacks: list[str] = []
        errors: list[str] = []
        if plan.use_hypotheses and self.hypothesis_provider is not None:
            generated = await asyncio.gather(
                self.hypothesis_provider.generate(text, style="event"),
                self.hypothesis_provider.generate(text, style="general"),
                return_exceptions=True,
            )
            for style, value in zip(("event", "general"), generated, strict=True):
                if isinstance(value, BaseException):
                    errors.append(f"hypothesis_{style}: {value}")
                    fallbacks.append(f"hypothesis_{style}_failed")
                    continue
                queries.append(value)
        queries = _dedupe_texts(queries)

        kinds = query.kinds or plan.kinds
        rows = self.store.list_active(
            kinds=kinds,
            time_start=query.time_start,
            time_end=query.time_end,
        )
        limit = query.limit if query.limit > 0 else self.top_k
        result_sets: list[list[MemoryRecord]] = []
        lane_counts: dict[str, dict[str, int]] = {}
        for active_query in queries:
            try:
                query_vector = await self.embedding_provider.embed(active_query)
            except Exception as error:
                query_vector = []
                errors.append(f"embedding[{active_query}]: {error}")
                fallbacks.append("lexical_only")
            ranked = _rank_rows(
                rows,
                query_vector,
                active_query,
                limit=limit,
                threshold=self.score_threshold,
            )
            result_sets.append(ranked)
            lane_counts[active_query] = {
                "vector": sum(
                    1 for record in ranked if "vector" in record.signals.get("lanes", [])
                ),
                "lexical": sum(
                    1 for record in ranked if "lexical" in record.signals.get("lanes", [])
                ),
            }
        records = _max_pool_records(result_sets, limit=limit)
        trace: dict[str, Any] = {
            "intent": query.intent,
            "queries": queries,
            "time_filters": {
                "start": _normalize_datetime(query.time_start) if query.time_start else None,
                "end": _normalize_datetime(query.time_end) if query.time_end else None,
            },
            "candidate_count": len(rows),
            "lane_counts": lane_counts,
            "fused_count": sum(len(items) for items in result_sets),
            "record_count": len(records),
            "records": [_trace_record(record, rank=index) for index, record in enumerate(records)],
            "fallbacks": _dedupe_texts(fallbacks),
            "errors": errors,
        }
        return MemoryQueryResult(records=records, trace=trace)

    async def mutate(self, request: MemoryMutation) -> MemoryMutationResult:
        if request.kind == "forget":
            return self.forget(list(request.ids))
        if request.kind == "correct":
            return await self._correct(request)
        return MemoryMutationResult(
            accepted=False,
            status="unsupported",
            missing_ids=list(request.ids),
            trace={"reason": "unsupported_mutation", "kind": request.kind},
        )

    def forget(self, ids: list[str]) -> MemoryMutationResult:
        clean_ids = _dedupe_ids(ids)
        items = self.store.get_items_by_ids(clean_ids)
        found_ids = [str(item["id"]) for item in items if str(item.get("id") or "")]
        missing_ids = [item_id for item_id in clean_ids if item_id not in set(found_ids)]
        if found_ids:
            self.store.mark_superseded_batch(found_ids, reason="forget")
        return MemoryMutationResult(
            accepted=bool(found_ids),
            status="superseded" if found_ids else "skipped",
            affected_ids=found_ids,
            missing_ids=missing_ids,
            items=items,
        )

    async def _correct(self, request: MemoryMutation) -> MemoryMutationResult:
        clean_ids = _dedupe_ids(list(request.ids))
        if len(clean_ids) != 1:
            return MemoryMutationResult(
                accepted=False,
                status="invalid",
                missing_ids=clean_ids,
                trace={"reason": "exactly_one_memory_id_required"},
            )
        memory_id = clean_ids[0]
        corrected_summary = request.corrected_summary.strip()
        source_ref = request.source_ref.strip()
        if not corrected_summary or not source_ref:
            return MemoryMutationResult(
                accepted=False,
                status="invalid",
                missing_ids=[],
                trace={"reason": "corrected_summary_and_source_ref_required"},
            )

        target = self.store.get_item_by_id(memory_id)
        if target is None:
            return MemoryMutationResult(
                accepted=False,
                status="missing",
                missing_ids=[memory_id],
                trace={"reason": "memory_id_not_found"},
            )
        if str(target.get("status") or "") != "active":
            return MemoryMutationResult(
                accepted=False,
                status="inactive",
                affected_ids=[memory_id],
                items=[target],
                trace={"reason": "memory_id_not_active"},
            )
        target_source_ref = str(target.get("source_ref") or "").strip()
        if target_source_ref != source_ref:
            return MemoryMutationResult(
                accepted=False,
                status="source_ref_mismatch",
                affected_ids=[memory_id],
                items=[target],
                trace={
                    "reason": "source_ref_mismatch",
                    "expected_source_ref": target_source_ref,
                    "provided_source_ref": source_ref,
                },
            )

        replacement = await self.ingest(
            MemoryIngestRequest(
                summary=corrected_summary,
                kind=request.replacement_kind.strip() or str(target.get("kind") or "event"),
                source_ref=_build_correction_source_ref(source_ref, memory_id),
                happened_at=str(target.get("happened_at") or "").strip() or None,
                extra={
                    **dict(request.extra or {}),
                    "lifecycle": "correction",
                    "corrects": memory_id,
                    "verified_source_ref": source_ref,
                },
            )
        )
        replacement_id = replacement.item_id
        if not replacement_id:
            return MemoryMutationResult(
                accepted=False,
                status="skipped",
                affected_ids=[memory_id],
                items=[target],
                trace={"reason": "replacement_not_created", "replacement_status": replacement.status},
            )
        if replacement_id == memory_id:
            return MemoryMutationResult(
                accepted=False,
                status="conflict",
                affected_ids=[memory_id],
                items=[target],
                trace={"reason": "replacement_reused_target", "replacement_status": replacement.status},
            )

        self.store.mark_superseded_batch(
            [memory_id],
            replacement_id=replacement_id,
            reason="correction",
        )
        items = self.store.get_items_by_ids([memory_id, replacement_id])
        return MemoryMutationResult(
            accepted=True,
            status="corrected",
            affected_ids=[memory_id, replacement_id],
            missing_ids=[],
            items=items,
            trace={
                "superseded_id": memory_id,
                "replacement_id": replacement_id,
                "replacement_status": replacement.status,
            },
        )

    def render_context_block(self, result: MemoryQueryResult) -> str:
        if not result.records:
            result.trace.update(
                {"injected_ids": [], "omitted_ids": [], "injection_char_count": 0}
            )
            return ""
        sections = (
            ("Applicable Procedures", {"procedure", "constraint"}),
            ("User Profile", {"profile", "preference"}),
            ("Relevant History", {"event", "fact"}),
        )
        selected_parts: list[str] = []
        injected_ids: list[str] = []
        omitted_ids: list[str] = []
        handled: set[str] = set()
        for title, kinds in sections:
            entries: list[str] = []
            for record in result.records:
                if record.id in handled or record.kind not in kinds:
                    continue
                handled.add(record.id)
                entry = _format_context_record(record)
                candidate_entries = [*entries, entry]
                candidate_section = f"## {title}\n" + "\n".join(candidate_entries)
                candidate = "\n\n".join([*selected_parts, candidate_section])
                if len(candidate) <= self.context_char_budget:
                    entries.append(entry)
                    injected_ids.append(record.id)
                else:
                    omitted_ids.append(record.id)
            if entries:
                selected_parts.append(f"## {title}\n" + "\n".join(entries))
        for record in result.records:
            if record.id not in handled:
                entry = _format_context_record(record)
                candidate_section = f"## Relevant Memory\n{entry}"
                candidate = "\n\n".join([*selected_parts, candidate_section])
                if len(candidate) <= self.context_char_budget:
                    selected_parts.append(candidate_section)
                    injected_ids.append(record.id)
                else:
                    omitted_ids.append(record.id)
        block = "\n\n".join(selected_parts)
        result.trace.update(
            {
                "injected_ids": injected_ids,
                "omitted_ids": omitted_ids,
                "injection_char_count": len(block),
            }
        )
        return block


def parse_history_entry_happened_at(summary: str) -> str | None:
    match = _TIME_PREFIX_RE.match((summary or "").strip())
    if not match:
        return None
    date = match.group("date")
    hour = match.group("hour") or "00"
    minute = match.group("minute") or "00"
    second = match.group("second") or "00"
    return f"{date}T{hour}:{minute}:{second}"


def build_entry_source_ref(base_source_ref: str, entry: str) -> str:
    base = base_source_ref.strip()
    text = entry.strip()
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12] if text else "empty"
    return f"{base}#h:{digest}" if base else f"#h:{digest}"


def _build_correction_source_ref(source_ref: str, memory_id: str) -> str:
    base = source_ref.strip()
    return f"{base}#corr:{memory_id}" if base else f"#corr:{memory_id}"


def _rank_rows(
    rows: list[dict[str, Any]],
    query_vector: list[float],
    query_text: str,
    *,
    limit: int,
    threshold: float,
) -> list[MemoryRecord]:
    terms = _extract_terms(query_text)

    # 1. 分 lane 打分（每个 row 同时在两路打分）
    vector_scored: list[tuple[str, float]] = []
    keyword_scored: list[tuple[str, float]] = []
    row_map: dict[str, dict[str, Any]] = {}

    for row in rows:
        row_id = str(row["id"])
        row_map[row_id] = row

        vector_score = _cosine(query_vector, row["embedding"]) if query_vector else 0.0
        keyword_score = _keyword_score(row["summary"], terms)

        if vector_score >= threshold:
            vector_scored.append((row_id, vector_score))
        if keyword_score > 0:
            keyword_scored.append((row_id, keyword_score))

    # 2. RRF 融合，reinforcement 参与同 lane 同分时的稳定排序。
    top_ids = _rrf_merge(
        vector_scored,
        keyword_scored,
        row_map=row_map,
        top_n=max(1, int(limit)),
    )

    # 3. 保留两路原始信号，避免 RRF 后丢失“双路命中”证据。
    vec_scores = dict(vector_scored)
    kw_scores = dict(keyword_scored)

    # 4. 构建 MemoryRecord
    return [
        MemoryRecord(
            id=item_id,
            kind=str(row_map[item_id]["kind"]),
            summary=str(row_map[item_id]["summary"]),
            score=rrf_score,
            source_ref=str(row_map[item_id]["source_ref"]),
            evidence=_evidence_from_source_ref(str(row_map[item_id]["source_ref"])),
            signals={
                "lanes": [
                    name
                    for name, score in (
                        ("vector", vec_scores.get(item_id, 0.0)),
                        ("lexical", kw_scores.get(item_id, 0.0)),
                    )
                    if score > 0
                ],
                "vector_score": vec_scores.get(item_id, 0.0),
                "lexical_score": kw_scores.get(item_id, 0.0),
                "rrf_score": rrf_score,
                "reinforcement": int(row_map[item_id].get("reinforcement") or 1),
                "reinforcement_boost": reinforcement_boost,
                "extra": dict(row_map[item_id].get("extra") or {}),
            },
        )
        for item_id, rrf_score, reinforcement_boost in top_ids
        if item_id in row_map
    ]


def _dedupe_ids(ids: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        item_id = str(raw).strip()
        if item_id and item_id not in seen:
            seen.add(item_id)
            result.append(item_id)
    return result


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "kind": str(row["kind"]),
        "summary": str(row["summary"]),
        "embedding": json.loads(row["embedding"]),
        "source_ref": str(row["source_ref"]),
        "happened_at": row["happened_at"],
        "extra": json.loads(row["extra_json"] or "{}"),
        "status": str(row["status"]),
        "reinforcement": int(row["reinforcement"] or 1),
    }


def _content_hash(summary: str, kind: str) -> str:
    normalized = " ".join(summary.lower().split())
    return hashlib.sha256(f"{kind}:{normalized}".encode()).hexdigest()[:16]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / left_norm / right_norm


def _keyword_score(summary: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    lowered = summary.lower()
    hits = sum(1 for term in terms if term in lowered)
    return hits / len(terms)


_RRF_K = 60
_KEYWORD_RRF_WEIGHT = 0.5


def _rrf_merge(
    vector_scored: list[tuple[str, float]],
    keyword_scored: list[tuple[str, float]],
    *,
    row_map: dict[str, dict[str, Any]] | None = None,
    top_n: int,
) -> list[tuple[str, float, float]]:
    """Reciprocal Rank Fusion: \u878d\u5408\u4e24\u8def\u6392\u540d\uff0c\u8fd4\u56de top_n \u7684 (id, rrf_score)\u3002"""
    if top_n <= 0 or (not vector_scored and not keyword_scored):
        return []

    # 1. \u6309 score \u964d\u5e8f\u7f16\u53f7 \u2192 rank
    metadata = row_map or {}
    vec_rank: dict[str, int] = {
        item_id: idx + 1
        for idx, (item_id, _) in enumerate(
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
        item_id: idx + 1
        for idx, (item_id, _) in enumerate(
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

    # 2. \u5e76\u96c6 \u2192 RRF \u5206\u6570
    all_ids = sorted(set(vec_rank) | set(kw_rank))
    scored: list[tuple[str, float, float]] = []
    for item_id in all_ids:
        rrf = 0.0
        if item_id in vec_rank:
            rrf += 1.0 / (_RRF_K + vec_rank[item_id])
        if item_id in kw_rank:
            rrf += _KEYWORD_RRF_WEIGHT / (_RRF_K + kw_rank[item_id])
        scored.append((item_id, rrf, _reinforcement_boost(metadata.get(item_id, {}))))

    # 3. \u53d6 top_n
    scored.sort(key=lambda item: (-item[1], -item[2], item[0]))
    return scored[:top_n]


def _extract_terms(text: str) -> list[str]:
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
    return _dedupe_texts(terms)


def _build_query_plan(query: MemoryQuery) -> _QueryPlan:
    text = " ".join(query.text.split())
    if query.intent == "procedure":
        return _QueryPlan(
            queries=tuple(_build_procedure_queries(text)),
            kinds=query.kinds or ("procedure", "preference"),
        )
    raw_queries = query.context.get("queries")
    if query.intent == "context" and isinstance(raw_queries, list):
        queries = _dedupe_texts([str(item) for item in raw_queries])
        if queries:
            return _QueryPlan(queries=tuple(queries), kinds=query.kinds)
    return _QueryPlan(
        queries=(text,),
        kinds=query.kinds,
        use_hypotheses=query.intent == "answer",
    )


def _build_procedure_queries(text: str) -> list[str]:
    normalized = " ".join(text.split())
    variants = [normalized]
    for prefix in ("如何", "怎么", "怎样"):
        if normalized.startswith(prefix):
            subject = normalized[len(prefix) :].strip()
            if subject:
                variants.extend((f"执行{subject}的步骤", f"{subject}流程"))
            break
    return _dedupe_texts(variants)


def _dedupe_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").split())
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _max_pool_records(
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
            if current is None or _record_sort_key(record) < _record_sort_key(current):
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
    return sorted(merged, key=_record_sort_key)[: max(0, limit)]


def _reinforcement_boost(row: dict[str, Any]) -> float:
    reinforcement = max(1, int(row.get("reinforcement") or 1))
    return math.log1p(reinforcement - 1) * 0.001


def _record_sort_key(record: MemoryRecord) -> tuple[float, float, str]:
    boost = float(record.signals.get("reinforcement_boost", 0.0) or 0.0)
    return (-record.score, -boost, record.id)


def _trace_record(record: MemoryRecord, *, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "id": record.id,
        "kind": record.kind,
        "score": record.score,
        "source_ref": record.source_ref,
        "signals": dict(record.signals),
    }


def _format_context_record(record: MemoryRecord) -> str:
    return (
        f"- [{record.id}] ({record.kind}, confidence={record.score:.3f}) "
        f"{record.summary} source_ref={record.source_ref}"
    )


def _evidence_from_source_ref(source_ref: str) -> list[EvidenceRef]:
    refs = _source_ref_message_ids(source_ref)
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


def _source_ref_message_ids(source_ref: str) -> list[str]:
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


def _normalize_timestamp(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return _normalize_datetime(datetime.fromisoformat(text))


def _normalize_datetime(value: datetime) -> str:
    normalized = value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value.replace(tzinfo=None)
    return normalized.replace(microsecond=0).isoformat()
