from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from amadeus.db import PostgresConfig, PostgresDatabase, normalize_psycopg_dsn

MEMORY_JOB_PENDING = "pending"
MEMORY_JOB_PROCESSING = "processing"
MEMORY_JOB_DONE = "done"
MEMORY_JOB_FAILED = "failed"

_JOB_COLUMN_NAMES = (
    "id",
    "turn_id",
    "user_id",
    "session_id",
    "user_message_id",
    "assistant_message_id",
    "explicit_memory_ids",
    "status",
    "attempts",
    "lease_id",
    "heartbeat_at",
    "result_json",
    "error_code",
    "error_message",
    "created_at",
    "started_at",
    "completed_at",
    "updated_at",
)
_JOB_COLUMNS = ", ".join(_JOB_COLUMN_NAMES)


class InvalidMemoryJobTransition(RuntimeError):
    """Raised when a memory job mutation no longer owns the active lease."""


@dataclass(frozen=True)
class PostResponseMemoryJob:
    id: str
    turn_id: str
    user_id: int
    session_id: int
    user_message_id: str
    assistant_message_id: str
    explicit_memory_ids: tuple[str, ...]
    status: str
    attempts: int
    lease_id: str | None
    heartbeat_at: str | None
    result: dict[str, Any]
    error_code: str | None
    error_message: str | None
    created_at: str | None
    started_at: str | None
    completed_at: str | None
    updated_at: str | None


class PostgresPostResponseMemoryJobStore:
    """PostgreSQL-backed queue for post-response memory work."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
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

    def close(self) -> None:
        if self._owns_db:
            self.db.close()

    def get_job(self, job_id: str) -> PostResponseMemoryJob | None:
        parsed_id = _uuid_or_none(job_id)
        if parsed_id is None:
            return None
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_JOB_COLUMNS} FROM post_response_memory_jobs WHERE id = %s",
                    (parsed_id,),
                )
                row = cursor.fetchone()
        return _row_to_job(row) if row is not None else None

    def get_job_by_turn(self, turn_id: str) -> PostResponseMemoryJob | None:
        parsed_turn_id = _uuid_or_none(turn_id)
        if parsed_turn_id is None:
            return None
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_JOB_COLUMNS}
                    FROM post_response_memory_jobs
                    WHERE turn_id = %s
                    """,
                    (parsed_turn_id,),
                )
                row = cursor.fetchone()
        return _row_to_job(row) if row is not None else None

    def claim_next_pending(self) -> PostResponseMemoryJob | None:
        lease_id = str(uuid.uuid4())
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    WITH candidate AS (
                        SELECT job.id
                        FROM post_response_memory_jobs AS job
                        WHERE job.status = %s
                          AND NOT EXISTS (
                              SELECT 1
                              FROM post_response_memory_jobs AS active
                              WHERE active.user_id = job.user_id
                                AND active.session_id = job.session_id
                                AND active.status = %s
                          )
                          AND NOT EXISTS (
                              SELECT 1
                              FROM post_response_memory_jobs AS earlier
                              WHERE earlier.user_id = job.user_id
                                AND earlier.session_id = job.session_id
                                AND earlier.status = %s
                                AND (earlier.created_at, earlier.id)
                                    < (job.created_at, job.id)
                          )
                        ORDER BY job.created_at ASC, job.id ASC
                        FOR UPDATE OF job SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE post_response_memory_jobs AS job
                    SET status = %s,
                        attempts = job.attempts + 1,
                        lease_id = %s,
                        started_at = COALESCE(job.started_at, now()),
                        heartbeat_at = now(),
                        updated_at = now()
                    FROM candidate
                    WHERE job.id = candidate.id
                    RETURNING {_qualified_job_columns("job")}
                    """,
                    (
                        MEMORY_JOB_PENDING,
                        MEMORY_JOB_PROCESSING,
                        MEMORY_JOB_PENDING,
                        MEMORY_JOB_PROCESSING,
                        lease_id,
                    ),
                )
                row = cursor.fetchone()
            conn.commit()
        return _row_to_job(row) if row is not None else None

    def heartbeat(self, job_id: str, lease_id: str) -> bool:
        parsed_job_id = _require_uuid(job_id)
        parsed_lease_id = _require_uuid(lease_id)
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE post_response_memory_jobs
                    SET heartbeat_at = now(), updated_at = now()
                    WHERE id = %s AND status = %s AND lease_id = %s
                    """,
                    (parsed_job_id, MEMORY_JOB_PROCESSING, parsed_lease_id),
                )
                updated = cursor.rowcount == 1
            conn.commit()
        if not updated:
            raise InvalidMemoryJobTransition("Memory job lease is no longer active")
        return True

    def mark_done(
        self,
        job_id: str,
        lease_id: str,
        trace: dict[str, Any],
    ) -> PostResponseMemoryJob:
        return self._mark_terminal(
            job_id,
            lease_id,
            status=MEMORY_JOB_DONE,
            result=trace,
            error_code=None,
            error_message=None,
        )

    def mark_failed(
        self,
        job_id: str,
        lease_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> PostResponseMemoryJob:
        return self._mark_terminal(
            job_id,
            lease_id,
            status=MEMORY_JOB_FAILED,
            result={},
            error_code=error_code,
            error_message=error_message,
        )

    def recover_stale(self, *, stale_after_seconds: float) -> int:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE post_response_memory_jobs
                    SET status = %s, lease_id = NULL, heartbeat_at = NULL,
                        updated_at = now()
                    WHERE status = %s
                      AND heartbeat_at < now() - (%s * interval '1 second')
                    """,
                    (
                        MEMORY_JOB_PENDING,
                        MEMORY_JOB_PROCESSING,
                        float(stale_after_seconds),
                    ),
                )
                recovered = int(cursor.rowcount)
            conn.commit()
        return recovered

    def _mark_terminal(
        self,
        job_id: str,
        lease_id: str,
        *,
        status: str,
        result: dict[str, Any],
        error_code: str | None,
        error_message: str | None,
    ) -> PostResponseMemoryJob:
        parsed_job_id = _require_uuid(job_id)
        parsed_lease_id = _require_uuid(lease_id)
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE post_response_memory_jobs
                    SET status = %s, result_json = %s, error_code = %s,
                        error_message = %s, completed_at = now(),
                        heartbeat_at = now(), updated_at = now()
                    WHERE id = %s AND status = %s AND lease_id = %s
                    """,
                    (
                        status,
                        Jsonb(result),
                        error_code,
                        error_message,
                        parsed_job_id,
                        MEMORY_JOB_PROCESSING,
                        parsed_lease_id,
                    ),
                )
                updated = cursor.rowcount == 1
            conn.commit()
        if not updated:
            raise InvalidMemoryJobTransition("Memory job lease is no longer active")
        job = self.get_job(job_id)
        if job is None:  # pragma: no cover - defensive invariant
            raise RuntimeError("Memory job disappeared after terminal update")
        return job


def _qualified_job_columns(alias: str) -> str:
    return ", ".join(f"{alias}.{column}" for column in _JOB_COLUMN_NAMES)


def _row_to_job(row: Mapping[str, Any]) -> PostResponseMemoryJob:
    explicit = row.get("explicit_memory_ids")
    result = row.get("result_json")
    return PostResponseMemoryJob(
        id=str(row["id"]),
        turn_id=str(row["turn_id"]),
        user_id=int(row["user_id"]),
        session_id=int(row["session_id"]),
        user_message_id=str(row["user_message_id"]),
        assistant_message_id=str(row["assistant_message_id"]),
        explicit_memory_ids=tuple(str(item) for item in explicit if str(item))
        if isinstance(explicit, list)
        else (),
        status=str(row["status"]),
        attempts=int(row["attempts"] or 0),
        lease_id=str(row["lease_id"]) if row.get("lease_id") is not None else None,
        heartbeat_at=_timestamp(row.get("heartbeat_at")),
        result=dict(result) if isinstance(result, dict) else {},
        error_code=(
            str(row["error_code"]) if row.get("error_code") is not None else None
        ),
        error_message=(
            str(row["error_message"])
            if row.get("error_message") is not None
            else None
        ),
        created_at=_timestamp(row.get("created_at")),
        started_at=_timestamp(row.get("started_at")),
        completed_at=_timestamp(row.get("completed_at")),
        updated_at=_timestamp(row.get("updated_at")),
    )


def _uuid_or_none(value: str) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return None


def _require_uuid(value: str) -> str:
    parsed = _uuid_or_none(value)
    if parsed is None:
        raise InvalidMemoryJobTransition("Memory job lease is no longer active")
    return parsed


def _timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
