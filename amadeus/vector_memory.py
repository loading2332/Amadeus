from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from openai import AsyncOpenAI

from amadeus.memory_engine import (
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
                    (now, happened_at, reinforced_id),
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
                    happened_at,
                    extra_json,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return item_id, "new"

    def list_active(self, *, kinds: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        clauses = ["status = 'active'"]
        params: list[Any] = []
        clean_kinds = tuple(kind.strip() for kind in kinds if kind.strip())
        if clean_kinds:
            placeholders = ",".join("?" for _ in clean_kinds)
            clauses.append(f"kind IN ({placeholders})")
            params.extend(clean_kinds)
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

    def mark_superseded_batch(self, ids: list[str]) -> None:
        if not ids:
            return
        now = datetime.now().astimezone().isoformat()
        with self._lock:
            self._conn.executemany(
                """
                UPDATE memory_items
                SET status = 'superseded',
                    updated_at = ?
                WHERE id = ?
                """,
                [(now, item_id) for item_id in ids],
            )
            self._conn.commit()


class VectorMemoryEngine:
    def __init__(
        self,
        *,
        store: VectorMemoryStore,
        embedding_provider: EmbeddingProvider,
        score_threshold: float = 0.35,
        top_k: int = 8,
    ) -> None:
        self.store = store
        self.embedding_provider = embedding_provider
        self.score_threshold = float(score_threshold)
        self.top_k = max(1, int(top_k))

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
        trace: dict[str, Any] = {}
        try:
            query_vector = await self.embedding_provider.embed(text)
        except Exception as error:
            query_vector = []
            trace["vector_error"] = str(error)

        rows = self.store.list_active(kinds=query.kinds)
        limit = query.limit if query.limit > 0 else self.top_k
        records = _rank_rows(
            rows,
            query_vector,
            text,
            limit=limit,
            threshold=self.score_threshold,
        )
        trace.update({"candidate_count": len(rows), "record_count": len(records)})
        return MemoryQueryResult(records=records, trace=trace)

    async def mutate(self, request: MemoryMutation) -> MemoryMutationResult:
        if request.kind != "forget":
            return MemoryMutationResult(
                accepted=False,
                status="unsupported",
                missing_ids=list(request.ids),
                trace={"reason": "unsupported_mutation", "kind": request.kind},
            )
        return self.forget(list(request.ids))

    def forget(self, ids: list[str]) -> MemoryMutationResult:
        clean_ids = _dedupe_ids(ids)
        items = self.store.get_items_by_ids(clean_ids)
        found_ids = [str(item["id"]) for item in items if str(item.get("id") or "")]
        missing_ids = [item_id for item_id in clean_ids if item_id not in set(found_ids)]
        if found_ids:
            self.store.mark_superseded_batch(found_ids)
        return MemoryMutationResult(
            accepted=bool(found_ids),
            status="superseded" if found_ids else "skipped",
            affected_ids=found_ids,
            missing_ids=missing_ids,
            items=items,
        )

    def render_context_block(self, result: MemoryQueryResult) -> str:
        if not result.records:
            return ""
        lines = ["## Retrieved Memory"]
        for record in result.records:
            lines.append(
                f"- [{record.id}] ({record.kind}, score={record.score:.3f}) "
                f"{record.summary} source_ref={record.source_ref}"
            )
        return "\n".join(lines)


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


def _rank_rows(
    rows: list[dict[str, Any]],
    query_vector: list[float],
    query_text: str,
    *,
    limit: int,
    threshold: float,
) -> list[MemoryRecord]:
    terms = _extract_terms(query_text)
    ranked: list[tuple[float, dict[str, Any], str]] = []
    for row in rows:
        keyword_score = _keyword_score(row["summary"], terms)
        vector_score = _cosine(query_vector, row["embedding"]) if query_vector else 0.0
        score = max(vector_score, keyword_score)
        if score < threshold and keyword_score <= 0:
            continue
        lane = "vector" if vector_score >= keyword_score else "keyword"
        ranked.append((score, row, lane))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        MemoryRecord(
            id=str(row["id"]),
            kind=str(row["kind"]),
            summary=str(row["summary"]),
            score=float(score),
            source_ref=str(row["source_ref"]),
            evidence=_evidence_from_source_ref(str(row["source_ref"])),
            signals={"lane": lane},
        )
        for score, row, lane in ranked[: max(1, int(limit))]
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


def _extract_terms(text: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]+", text) if term.strip()]


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
