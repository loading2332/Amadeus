from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from psycopg.types.json import Jsonb

from amadeus.db import PostgresConfig, PostgresDatabase, normalize_psycopg_dsn
from amadeus.turns.store import (
    TURN_DONE,
    TURN_FAILED,
    TURN_PENDING,
    TURN_PROCESSING,
    Turn,
)


class PostgresTurnStore:
    """PostgreSQL-backed turn queue with same-session serialization."""

    def __init__(self, dsn: str | None = None, *, db: PostgresDatabase | None = None) -> None:
        if db is None:
            if dsn is None:
                raise ValueError("Missing Amadeus runtime config: AMADEUS_POSTGRES_DSN")
            db = PostgresDatabase(PostgresConfig(dsn=normalize_psycopg_dsn(dsn)))
            db.open()
            self._owns_db = True
        else:
            self._owns_db = False
        self.db = db

    def close(self) -> None:
        if self._owns_db:
            self.db.close()

    def create_turn(
        self,
        *,
        user_id: int,
        session_id: int,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Turn:
        turn_id = str(uuid.uuid4())
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversation_turns (
                        id, user_id, session_id, content, status, metadata_json, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        turn_id,
                        int(user_id),
                        int(session_id),
                        content,
                        TURN_PENDING,
                        Jsonb(metadata or {}),
                    ),
                )
            conn.commit()
        turn = self.get_turn(turn_id)
        if turn is None:  # pragma: no cover - defensive invariant
            raise RuntimeError(f"Created turn not found: {turn_id}")
        return turn

    def get_turn(self, turn_id: str) -> Turn | None:
        try:
            parsed_turn_id = str(uuid.UUID(str(turn_id)))
        except (TypeError, ValueError):
            return None
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, session_id, content, status, answer, error,
                           metadata_json, attempts, created_at, updated_at,
                           started_at, completed_at
                    FROM conversation_turns
                    WHERE id = %s
                    """,
                    (parsed_turn_id,),
                )
                row = cursor.fetchone()
        return _row_to_turn(row) if row is not None else None

    def claim_next_pending(self) -> Turn | None:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    WITH candidate AS (
                      SELECT id
                      FROM conversation_turns AS pending
                      WHERE pending.status = %s
                        AND NOT EXISTS (
                          SELECT 1
                          FROM conversation_turns AS active
                          WHERE active.status = %s
                            AND active.user_id = pending.user_id
                            AND active.session_id = pending.session_id
                        )
                      ORDER BY pending.created_at ASC, pending.id ASC
                      FOR UPDATE SKIP LOCKED
                      LIMIT 1
                    )
                    UPDATE conversation_turns AS turn
                    SET status = %s,
                        attempts = attempts + 1,
                        started_at = COALESCE(started_at, now()),
                        updated_at = now()
                    FROM candidate
                    WHERE turn.id = candidate.id
                    RETURNING turn.id, turn.user_id, turn.session_id, turn.content,
                              turn.status, turn.answer, turn.error, turn.metadata_json,
                              turn.attempts, turn.created_at, turn.updated_at,
                              turn.started_at, turn.completed_at
                    """,
                    (TURN_PENDING, TURN_PROCESSING, TURN_PROCESSING),
                )
                row = cursor.fetchone()
            conn.commit()
        return _row_to_turn(row) if row is not None else None

    def mark_done(self, turn_id: str, answer: str) -> Turn:
        return self._mark_terminal(turn_id, status=TURN_DONE, answer=answer, error=None)

    def mark_failed(self, turn_id: str, error: str) -> Turn:
        return self._mark_terminal(turn_id, status=TURN_FAILED, answer=None, error=error)

    def _mark_terminal(
        self,
        turn_id: str,
        *,
        status: str,
        answer: str | None,
        error: str | None,
    ) -> Turn:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE conversation_turns
                    SET status = %s,
                        answer = %s,
                        error = %s,
                        completed_at = now(),
                        updated_at = now()
                    WHERE id = %s AND status = %s
                    """,
                    (status, answer, error, turn_id, TURN_PROCESSING),
                )
            conn.commit()
        turn = self.get_turn(turn_id)
        if turn is None:  # pragma: no cover - defensive invariant
            raise RuntimeError(f"Turn not found after terminal update: {turn_id}")
        return turn


def _row_to_turn(row: Mapping[str, Any]) -> Turn:
    user_id = int(row["user_id"])
    session_id = int(row["session_id"])
    return Turn(
        id=str(row["id"]),
        user_id=user_id,
        session_id=session_id,
        content=str(row["content"]),
        status=str(row["status"]),
        answer=row["answer"],
        error=row["error"],
        metadata=dict(row["metadata_json"] or {}),
        attempts=int(row["attempts"] or 0),
        created_at=_ts(row["created_at"]),
        updated_at=_ts(row["updated_at"]),
        started_at=_ts(row["started_at"]),
        finished_at=_ts(row["completed_at"]),
    )


def _ts(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)
