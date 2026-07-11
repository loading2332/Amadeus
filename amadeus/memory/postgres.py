from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pgvector import Vector  # type: ignore[import-untyped]
from psycopg.types.json import Jsonb

from amadeus.db import PostgresConfig, PostgresDatabase, normalize_psycopg_dsn
from amadeus.memory.store import _content_hash, _normalize_datetime

_MAX_LEXICAL_TERMS = 20


class PostgresMemoryStore:
    """PostgreSQL + pgvector-backed long-term memory store.

    Scopes every read/write by ``user_id``. Semantic candidate retrieval uses
    the pgvector distance operator ``<=>`` instead of a Python full-table scan.

    Embeddings are passed as Python ``list[float]`` parameters through the
    pgvector psycopg adapter (registered on the shared connection pool) — no
    hand-formatted ``[v1,v2,...]::vector`` string literals. The store is bound
    to a single ``user_id`` at construction time; production bootstrap composes
    one store per active user. Cross-user isolation is enforced by SQL
    ``WHERE user_id = %s`` on every query, never by client-side filtering.
    """

    def __init__(
        self,
        user_id: int,
        *,
        dsn: str | None = None,
        db: PostgresDatabase | None = None,
    ) -> None:
        if db is None:
            if dsn is None:
                raise ValueError("Missing Amadeus runtime config: AMADEUS_POSTGRES_DSN")
            db = PostgresDatabase(PostgresConfig(dsn=normalize_psycopg_dsn(dsn)))
            db.open()
            self._owns_db = True
        else:
            self._owns_db = False
        self.db = db
        self.user_id = int(user_id)
        self.ensure_user(self.user_id)

    def close(self) -> None:
        if self._owns_db:
            self.db.close()

    def ensure_user(self, user_id: int) -> None:
        """Make sure the ``users`` row backing this store exists.

        ``memory_items.user_id`` references ``users.id``; a standalone store
        must satisfy that foreign key before writing. The session store does
        the same upsert, so when both share a pool this is a cheap no-op.
        """
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (id, metadata, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (id) DO UPDATE SET updated_at = now()
                    """,
                    (int(user_id), Jsonb({})),
                )
            conn.commit()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def insert_item(
        self,
        *,
        item_id: str,
        memory_type: str,
        summary: str,
        content_hash: str,
        embedding: list[float],
        source_ref: str,
        happened_at: str | None,
        scope_channel: str | None,
        scope_chat_id: str | None,
        emotional_weight: float,
        extra: dict[str, Any],
    ) -> None:
        extra_payload = self._merge_scope(extra, scope_channel, scope_chat_id)
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO memory_items (
                        id, user_id, memory_type, summary, content_hash,
                        embedding, source_ref, happened_at, status,
                        reinforcement, emotional_weight, extra_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', 1, %s, %s)
                    """,
                    (
                        item_id,
                        self.user_id,
                        memory_type,
                        summary,
                        content_hash,
                        Vector(embedding),
                        source_ref,
                        happened_at,
                        float(emotional_weight),
                        Jsonb(extra_payload),
                    ),
                )
            conn.commit()

    def upsert_item(
        self,
        *,
        memory_type: str,
        summary: str,
        embedding: list[float],
        source_ref: str,
        happened_at: str | None = None,
        scope_channel: str | None = None,
        scope_chat_id: str | None = None,
        emotional_weight: float = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        normalized_type = memory_type.strip() or "event"
        text = summary.strip()
        src = source_ref.strip()
        if not text or not src:
            return "", "invalid"
        digest = _content_hash(text, normalized_type)
        item_id = f"mem_{digest}"
        extra_payload = self._merge_scope(extra or {}, scope_channel, scope_chat_id)
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                # Skip duplicate writes by source_ref + memory_type within this user.
                cursor.execute(
                    """
                    SELECT id
                    FROM memory_items
                    WHERE user_id = %s AND source_ref = %s AND memory_type = %s
                    """,
                    (self.user_id, src, normalized_type),
                )
                existing_source = cursor.fetchone()
                if existing_source is not None:
                    conn.commit()
                    return str(existing_source["id"]), "skipped"

                # Reinforce an existing same-content row instead of duplicating it.
                cursor.execute(
                    """
                    SELECT id
                    FROM memory_items
                    WHERE user_id = %s AND content_hash = %s AND memory_type = %s
                    """,
                    (self.user_id, digest, normalized_type),
                )
                existing_hash = cursor.fetchone()
                if existing_hash is not None:
                    reinforced_id = str(existing_hash["id"])
                    cursor.execute(
                        """
                        UPDATE memory_items
                        SET reinforcement = reinforcement + 1,
                            updated_at = now(),
                            happened_at = COALESCE(happened_at, %s),
                            emotional_weight = GREATEST(emotional_weight, %s)
                        WHERE user_id = %s AND id = %s
                        """,
                        (
                            happened_at,
                            float(emotional_weight),
                            self.user_id,
                            reinforced_id,
                        ),
                    )
                    conn.commit()
                    return reinforced_id, "reinforced"

                cursor.execute(
                    """
                    INSERT INTO memory_items (
                        id, user_id, memory_type, summary, content_hash,
                        embedding, source_ref, happened_at, status,
                        reinforcement, emotional_weight, extra_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', 1, %s, %s)
                    """,
                    (
                        item_id,
                        self.user_id,
                        normalized_type,
                        text,
                        digest,
                        Vector(embedding),
                        src,
                        happened_at,
                        float(emotional_weight),
                        Jsonb(extra_payload),
                    ),
                )
            conn.commit()
        return item_id, "new"

    def record_replacement(
        self,
        old_item_id: str,
        new_item_id: str,
        source_ref: str,
    ) -> None:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO memory_replacements (
                        old_item_id, new_item_id, user_id, source_ref
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (old_item_id, new_item_id, self.user_id, source_ref),
                )
            conn.commit()

    def mark_items_status(
        self,
        ids: list[str],
        *,
        status: str,
        extra_patch: dict[str, Any],
    ) -> None:
        if not ids:
            return
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, extra_json
                    FROM memory_items
                    WHERE user_id = %s AND id = ANY(%s)
                    """,
                    (self.user_id, list(ids)),
                )
                rows = cursor.fetchall()
                for row in rows:
                    merged = dict(row["extra_json"] or {})
                    merged.update(extra_patch)
                    cursor.execute(
                        """
                        UPDATE memory_items
                        SET status = %s,
                            updated_at = now(),
                            extra_json = %s
                        WHERE user_id = %s AND id = %s
                        """,
                        (status, Jsonb(merged), self.user_id, row["id"]),
                    )
            conn.commit()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_replacements_for(self, old_item_id: str) -> list[dict[str, str]]:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT old_item_id, new_item_id
                    FROM memory_replacements
                    WHERE user_id = %s AND old_item_id = %s
                    ORDER BY created_at ASC
                    """,
                    (self.user_id, old_item_id),
                )
                rows = cursor.fetchall()
        return [
            {
                "old_item_id": str(row["old_item_id"]),
                "new_item_id": str(row["new_item_id"]),
            }
            for row in rows
        ]

    def find_replacements_by_source_ref(self, source_ref: str) -> list[dict[str, str]]:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT old_item_id, new_item_id, source_ref
                    FROM memory_replacements
                    WHERE user_id = %s AND source_ref = %s
                    ORDER BY created_at ASC
                    """,
                    (self.user_id, source_ref),
                )
                rows = cursor.fetchall()
        return [
            {
                "old_item_id": str(row["old_item_id"]),
                "new_item_id": str(row["new_item_id"]),
                "source_ref": str(row["source_ref"]),
            }
            for row in rows
        ]

    def list_active_items(
        self,
        *,
        memory_types: tuple[str, ...] = (),
        scope_channel: str | None = None,
        scope_chat_id: str | None = None,
        time_start: datetime | None = None,
        time_end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses, params = self._active_candidate_filters(
            memory_types=memory_types,
            scope_channel=scope_channel,
            scope_chat_id=scope_chat_id,
            time_start=time_start,
            time_end=time_end,
        )
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, memory_type, summary, content_hash, embedding,
                           source_ref, happened_at, status, reinforcement,
                           emotional_weight, created_at, updated_at, extra_json
                    FROM memory_items
                    WHERE {" AND ".join(clauses)}
                    ORDER BY updated_at DESC
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()
        return [_row_to_item(row) for row in rows]

    def search_vector_candidates(
        self,
        *,
        query_embedding: list[float],
        memory_types: tuple[str, ...] = (),
        scope_channel: str | None = None,
        scope_chat_id: str | None = None,
        time_start: datetime | None = None,
        time_end: datetime | None = None,
        limit: int = 32,
    ) -> list[dict[str, Any]]:
        """Return active pgvector candidates ordered by cosine distance.

        This method is the vector-lane store boundary. It intentionally rejects
        rows without an embedding; the independent lexical method does not.
        """
        clauses, where_params = self._active_candidate_filters(
            memory_types=memory_types,
            scope_channel=scope_channel,
            scope_chat_id=scope_chat_id,
            time_start=time_start,
            time_end=time_end,
        )
        clauses.append("embedding IS NOT NULL")
        sql_distance_clause = "embedding <=> %s::vector AS distance"
        select_params: list[Any] = [Vector(query_embedding)]
        params = select_params + where_params + [Vector(query_embedding), int(limit)]
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, memory_type, summary, content_hash, embedding,
                           source_ref, happened_at, status, reinforcement,
                           emotional_weight, created_at, updated_at, extra_json,
                           {sql_distance_clause}
                    FROM memory_items
                    WHERE {" AND ".join(clauses)}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()
        results = [_row_to_item(row) for row in rows]
        for row, item in zip(rows, results, strict=True):
            distance = row.get("distance")
            item["vector_distance"] = float(distance) if distance is not None else None
        return results

    def search_active_items(
        self,
        *,
        query_embedding: list[float],
        memory_types: tuple[str, ...] = (),
        scope_channel: str | None = None,
        scope_chat_id: str | None = None,
        time_start: datetime | None = None,
        time_end: datetime | None = None,
        limit: int = 32,
    ) -> list[dict[str, Any]]:
        """Compatibility alias for the explicitly named vector lane."""
        return self.search_vector_candidates(
            query_embedding=query_embedding,
            memory_types=memory_types,
            scope_channel=scope_channel,
            scope_chat_id=scope_chat_id,
            time_start=time_start,
            time_end=time_end,
            limit=limit,
        )

    def search_lexical_candidates(
        self,
        *,
        terms: tuple[str, ...],
        memory_types: tuple[str, ...] = (),
        scope_channel: str | None = None,
        scope_chat_id: str | None = None,
        time_start: datetime | None = None,
        time_end: datetime | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Return independent substring candidates with matched-term coverage."""
        clean_terms = _stable_lexical_terms(terms)
        if not clean_terms or limit <= 0:
            return []

        patterns = [_literal_ilike_pattern(term) for term in clean_terms]
        match_parts = [
            "CASE WHEN summary ILIKE %s ESCAPE '!' THEN 1 ELSE 0 END" for _ in patterns
        ]
        match_count_sql = " + ".join(match_parts)
        match_any_sql = " OR ".join("summary ILIKE %s ESCAPE '!'" for _ in patterns)
        clauses, filter_params = self._active_candidate_filters(
            memory_types=memory_types,
            scope_channel=scope_channel,
            scope_chat_id=scope_chat_id,
            time_start=time_start,
            time_end=time_end,
        )
        params: list[Any] = [len(clean_terms)]
        params.extend(patterns)
        params.extend(filter_params)
        params.extend(patterns)
        params.append(int(limit))

        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, memory_type, summary, content_hash, embedding,
                           source_ref, happened_at, status, reinforcement,
                           emotional_weight, created_at, updated_at, extra_json,
                           lexical_matched_terms,
                           lexical_matched_terms::double precision / %s
                               AS lexical_score
                    FROM (
                        SELECT id, memory_type, summary, content_hash, embedding,
                               source_ref, happened_at, status, reinforcement,
                               emotional_weight, created_at, updated_at, extra_json,
                               ({match_count_sql}) AS lexical_matched_terms
                        FROM memory_items
                        WHERE {" AND ".join(clauses)}
                          AND ({match_any_sql})
                    ) AS lexical_candidates
                    ORDER BY lexical_score DESC, reinforcement DESC, id ASC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()

        results = [_row_to_item(row) for row in rows]
        for row, item in zip(rows, results, strict=True):
            item["lexical_matched_terms"] = int(row["lexical_matched_terms"])
            item["lexical_score"] = float(row["lexical_score"])
        return results

    def find_items_by_source_ref(self, source_ref: str) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, memory_type, summary, content_hash, embedding,
                           source_ref, happened_at, status, reinforcement,
                           emotional_weight, created_at, updated_at, extra_json
                    FROM memory_items
                    WHERE user_id = %s AND source_ref = %s
                    ORDER BY updated_at DESC
                    """,
                    (self.user_id, source_ref),
                )
                rows = cursor.fetchall()
        return [_row_to_item(row) for row in rows]

    def get_items_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, memory_type, summary, content_hash, embedding,
                           source_ref, happened_at, status, reinforcement,
                           emotional_weight, created_at, updated_at, extra_json
                    FROM memory_items
                    WHERE user_id = %s AND id = ANY(%s)
                    """,
                    (self.user_id, list(ids)),
                )
                rows = cursor.fetchall()
        found = {item["id"]: item for item in (_row_to_item(row) for row in rows)}
        return [found[item_id] for item_id in ids if item_id in found]

    def get_item_by_id(self, item_id: str) -> dict[str, Any] | None:
        items = self.get_items_by_ids([item_id])
        return items[0] if items else None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _active_candidate_filters(
        self,
        *,
        memory_types: tuple[str, ...],
        scope_channel: str | None,
        scope_chat_id: str | None,
        time_start: datetime | None,
        time_end: datetime | None,
    ) -> tuple[list[str], list[Any]]:
        clauses = ["user_id = %s", "status = 'active'"]
        params: list[Any] = [self.user_id]
        clean_types = tuple(value.strip() for value in memory_types if value.strip())
        if clean_types:
            clauses.append("memory_type = ANY(%s)")
            params.append(list(clean_types))
        if scope_channel is not None:
            clauses.append("extra_json->>'scope_channel' = %s")
            params.append(scope_channel)
        if scope_chat_id is not None:
            clauses.append("extra_json->>'scope_chat_id' = %s")
            params.append(scope_chat_id)
        if time_start is not None:
            clauses.append("happened_at IS NOT NULL")
            clauses.append("happened_at >= %s::timestamptz")
            params.append(_normalize_datetime(time_start))
        if time_end is not None:
            clauses.append("happened_at IS NOT NULL")
            clauses.append("happened_at <= %s::timestamptz")
            params.append(_normalize_datetime(time_end))
        return clauses, params

    @staticmethod
    def _merge_scope(
        extra: dict[str, Any],
        scope_channel: str | None,
        scope_chat_id: str | None,
    ) -> dict[str, Any]:
        payload = dict(extra)
        payload["scope_channel"] = scope_channel
        payload["scope_chat_id"] = scope_chat_id
        return payload


def _row_to_item(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "memory_type": str(row["memory_type"]),
        "summary": str(row["summary"]),
        "content_hash": str(row["content_hash"]),
        "embedding": _coerce_embedding(row["embedding"]),
        "source_ref": str(row["source_ref"]),
        "happened_at": _iso(row["happened_at"]),
        "status": str(row["status"]),
        "reinforcement": int(row["reinforcement"] or 1),
        "emotional_weight": float(row["emotional_weight"] or 0.0),
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
        "extra": dict(row["extra_json"] or {}),
    }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _coerce_embedding(value: Any) -> list[float]:
    """Normalize a pgvector column value into a plain ``list[float]``.

    The pgvector psycopg adapter decodes columns into ``numpy.ndarray``; the
    ranking layer and existing tests expect ``list[float]``. ``None`` (a null
    embedding) decodes to an empty list, matching the SQLite store shape.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [float(v) for v in value]
    # numpy ndarray or other sequence-like container
    if hasattr(value, "tolist"):
        return [float(v) for v in value.tolist()]
    return [float(v) for v in value]


def _stable_lexical_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    clean: list[str] = []
    seen: set[str] = set()
    for raw_term in terms:
        term = raw_term.strip()
        if len(term) < 2 or term in seen:
            continue
        clean.append(term)
        seen.add(term)
        if len(clean) == _MAX_LEXICAL_TERMS:
            break
    return tuple(clean)


def _literal_ilike_pattern(term: str) -> str:
    escaped = term.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{escaped}%"
