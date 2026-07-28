from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, cast

from psycopg import errors
from psycopg.types.json import Jsonb

from amadeus.db import PostgresConfig, PostgresDatabase, normalize_psycopg_dsn
from amadeus.session.titles import title_from_first_message
from amadeus.turns.store import (
    TURN_CANCELLED,
    TURN_DONE,
    TURN_FAILED,
    TURN_FINALIZING,
    TURN_PENDING,
    TURN_PROCESSING,
    ActiveTurnExists,
    InvalidTurnTransition,
    Turn,
    TurnError,
    TurnEvent,
    TurnExecutionResult,
)

_TURN_COLUMNS = """
    id, user_id, session_id, content, status, answer, error,
    error_code, error_message, error_retryable, metadata_json, attempts,
    created_at, updated_at, started_at, completed_at, partial_answer,
    stream_version, next_event_seq, cancel_requested_at, heartbeat_at,
    lease_id, retry_of_turn_id
"""


class PostgresTurnStore:
    """Durable turn state machine shared by API and worker processes."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        db: PostgresDatabase | None = None,
        post_response_memory_enabled: bool = False,
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
        self.post_response_memory_enabled = bool(post_response_memory_enabled)

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
        retry_of_turn_id: str | None = None,
    ) -> Turn:
        turn_id = str(uuid.uuid4())
        try:
            with self.db.connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO conversation_turns (
                            id, user_id, session_id, content, status,
                            metadata_json, retry_of_turn_id, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                        """,
                        (
                            turn_id,
                            int(user_id),
                            int(session_id),
                            content,
                            TURN_PENDING,
                            Jsonb(metadata or {}),
                            retry_of_turn_id,
                        ),
                    )
                    self._insert_event(
                        cursor,
                        turn_id,
                        "turn_status",
                        {"status": TURN_PENDING},
                    )
                    if retry_of_turn_id is None:
                        cursor.execute(
                            """
                            UPDATE conversation_sessions AS session
                            SET title = %s, updated_at = now()
                            WHERE session.id = %s
                              AND session.user_id = %s
                              AND (session.title IS NULL OR btrim(session.title) = '')
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM conversation_turns AS earlier
                                  WHERE earlier.user_id = %s
                                    AND earlier.session_id = %s
                                    AND earlier.id <> %s
                              )
                            """,
                            (
                                title_from_first_message(content),
                                int(session_id),
                                int(user_id),
                                int(user_id),
                                int(session_id),
                                turn_id,
                            ),
                        )
                conn.commit()
        except errors.UniqueViolation as error:
            raise ActiveTurnExists(
                "An active turn already exists for this session"
            ) from error
        return self._require_turn(turn_id)

    def retry_turn(self, *, turn_id: str, user_id: int) -> Turn:
        original = self.get_turn(turn_id)
        if original is None or original.user_id != int(user_id):
            raise InvalidTurnTransition("Turn is not retryable")
        if original.status not in {TURN_FAILED, TURN_CANCELLED}:
            raise InvalidTurnTransition("Only failed or cancelled turns can be retried")
        metadata = dict(original.metadata)
        metadata["retry_of_turn_id"] = original.id
        return self.create_turn(
            user_id=original.user_id,
            session_id=original.session_id,
            content=original.content,
            metadata=metadata,
            retry_of_turn_id=original.id,
        )

    def get_turn(self, turn_id: str) -> Turn | None:
        parsed_turn_id = _uuid_or_none(turn_id)
        if parsed_turn_id is None:
            return None
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_TURN_COLUMNS} FROM conversation_turns WHERE id = %s",
                    (parsed_turn_id,),
                )
                row = cursor.fetchone()
        return _row_to_turn(row) if row is not None else None

    def list_turns(self, *, user_id: int, session_id: int) -> list[Turn]:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_TURN_COLUMNS}
                    FROM conversation_turns
                    WHERE user_id = %s AND session_id = %s
                    ORDER BY created_at ASC, id ASC
                    """,
                    (int(user_id), int(session_id)),
                )
                rows = cursor.fetchall()
        return [_row_to_turn(row) for row in rows]

    def claim_next_pending(self) -> Turn | None:
        lease_id = str(uuid.uuid4())
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    WITH candidate AS (
                      SELECT id
                      FROM conversation_turns
                      WHERE status = %s
                      ORDER BY created_at ASC, id ASC
                      FOR UPDATE SKIP LOCKED
                      LIMIT 1
                    )
                    UPDATE conversation_turns AS turn
                    SET status = %s,
                        attempts = attempts + 1,
                        lease_id = %s,
                        heartbeat_at = now(),
                        started_at = COALESCE(started_at, now()),
                        updated_at = now()
                    FROM candidate
                    WHERE turn.id = candidate.id
                    RETURNING {_prefixed_columns("turn")}
                    """,
                    (TURN_PENDING, TURN_PROCESSING, lease_id),
                )
                row = cursor.fetchone()
                if row is not None:
                    self._insert_event(
                        cursor,
                        str(row["id"]),
                        "turn_status",
                        {"status": TURN_PROCESSING},
                    )
            conn.commit()
        return _row_to_turn(row) if row is not None else None

    def heartbeat(self, turn_id: str, lease_id: str) -> bool:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE conversation_turns
                    SET heartbeat_at = now(), updated_at = now()
                    WHERE id = %s
                      AND status IN (%s, %s)
                      AND lease_id = %s
                    RETURNING cancel_requested_at
                    """,
                    (turn_id, TURN_PROCESSING, TURN_FINALIZING, lease_id),
                )
                row = cursor.fetchone()
            conn.commit()
        if row is None:
            raise InvalidTurnTransition("Turn lease is no longer active")
        return row["cancel_requested_at"] is not None

    def cancel_requested(self, turn_id: str, lease_id: str) -> bool:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT cancel_requested_at
                    FROM conversation_turns
                    WHERE id = %s
                      AND status IN (%s, %s)
                      AND lease_id = %s
                    """,
                    (turn_id, TURN_PROCESSING, TURN_FINALIZING, lease_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise InvalidTurnTransition("Turn lease is no longer active")
        return row["cancel_requested_at"] is not None

    def begin_finalization(self, turn_id: str, lease_id: str) -> Turn | None:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, lease_id, cancel_requested_at
                    FROM conversation_turns
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (turn_id,),
                )
                row = cursor.fetchone()
                if (
                    row is None
                    or str(row["lease_id"]) != str(lease_id)
                    or str(row["status"])
                    not in {TURN_PROCESSING, TURN_FINALIZING}
                ):
                    raise InvalidTurnTransition("Turn lease is no longer active")
                if str(row["status"]) == TURN_PROCESSING:
                    if row["cancel_requested_at"] is not None:
                        conn.commit()
                        return None
                    cursor.execute(
                        """
                        UPDATE conversation_turns
                        SET status = %s, updated_at = now()
                        WHERE id = %s
                        """,
                        (TURN_FINALIZING, turn_id),
                    )
                    self._insert_event(
                        cursor,
                        turn_id,
                        "turn_status",
                        {"status": TURN_FINALIZING},
                    )
            conn.commit()
        return self._require_turn(turn_id)

    def append_content_snapshot(
        self,
        turn_id: str,
        lease_id: str,
        content: str,
    ) -> TurnEvent:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                row = self._lock_active(cursor, turn_id, lease_id)
                version = int(row["stream_version"] or 0) + 1
                cursor.execute(
                    """
                    UPDATE conversation_turns
                    SET partial_answer = %s, stream_version = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (content, version, turn_id),
                )
                event = self._insert_event(
                    cursor,
                    turn_id,
                    "content_snapshot",
                    {"content": content, "version": version},
                )
            conn.commit()
        return event

    def append_tool_activity(
        self,
        turn_id: str,
        lease_id: str,
        *,
        activity_id: str,
        tool_name: str,
        state: str,
    ) -> TurnEvent:
        if state not in {"started", "completed", "failed"}:
            raise ValueError("tool activity state must be started/completed/failed")
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                self._lock_active(cursor, turn_id, lease_id)
                event = self._insert_event(
                    cursor,
                    turn_id,
                    "tool_activity",
                    {
                        "activity_id": activity_id,
                        "tool_name": tool_name,
                        "state": state,
                    },
                )
            conn.commit()
        return event

    def request_cancel(self, turn_id: str) -> Turn:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT status FROM conversation_turns WHERE id = %s FOR UPDATE",
                    (turn_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise InvalidTurnTransition("Turn not found")
                status = str(row["status"])
                if status == TURN_PENDING:
                    cursor.execute(
                        """
                        UPDATE conversation_turns
                        SET status = %s, cancel_requested_at = now(),
                            completed_at = now(), updated_at = now()
                        WHERE id = %s
                        """,
                        (TURN_CANCELLED, turn_id),
                    )
                    self._insert_event(
                        cursor,
                        turn_id,
                        "turn_terminal",
                        {"status": TURN_CANCELLED},
                    )
                elif status == TURN_PROCESSING:
                    cursor.execute(
                        """
                        UPDATE conversation_turns
                        SET cancel_requested_at = COALESCE(cancel_requested_at, now()),
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (turn_id,),
                    )
                else:
                    raise InvalidTurnTransition("Terminal turns cannot be cancelled")
            conn.commit()
        return self._require_turn(turn_id)

    def mark_done(self, turn_id: str, lease_id: str, answer: str) -> Turn:
        return self._mark_terminal(
            turn_id,
            lease_id,
            status=TURN_DONE,
            answer=answer,
            error=None,
        )

    def complete_success(
        self,
        turn_id: str,
        lease_id: str,
        result: TurnExecutionResult,
    ) -> Turn:
        return self._mark_terminal(
            turn_id,
            lease_id,
            status=TURN_DONE,
            answer=result.answer,
            error=None,
            execution_result=result,
        )

    def mark_failed(self, turn_id: str, lease_id: str, error: TurnError) -> Turn:
        return self._mark_terminal(
            turn_id,
            lease_id,
            status=TURN_FAILED,
            answer=None,
            error=error,
        )

    def mark_cancelled(self, turn_id: str, lease_id: str) -> Turn:
        return self._mark_terminal(
            turn_id,
            lease_id,
            status=TURN_CANCELLED,
            answer=None,
            error=None,
        )

    def list_events(self, turn_id: str, *, after_seq: int = 0) -> list[TurnEvent]:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT turn_id, seq, event_type, payload_json, created_at
                    FROM conversation_turn_events
                    WHERE turn_id = %s AND seq > %s
                    ORDER BY seq ASC
                    """,
                    (turn_id, int(after_seq)),
                )
                rows = cursor.fetchall()
        return [_row_to_event(row) for row in rows]

    def list_stale_processing(self, *, stale_after_seconds: float) -> list[Turn]:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_TURN_COLUMNS}
                    FROM conversation_turns
                    WHERE status IN (%s, %s)
                      AND heartbeat_at < now() - make_interval(secs => %s)
                    ORDER BY heartbeat_at ASC, id ASC
                    """,
                    (
                        TURN_PROCESSING,
                        TURN_FINALIZING,
                        float(stale_after_seconds),
                    ),
                )
                rows = cursor.fetchall()
        return [_row_to_turn(row) for row in rows]

    def reconcile_interrupted(
        self,
        turn_id: str,
        *,
        lease_id: str,
        stale_after_seconds: float,
        assistant_answer: str | None,
    ) -> Turn:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, partial_answer, stream_version
                    FROM conversation_turns
                    WHERE id = %s
                      AND status IN (%s, %s)
                      AND lease_id = %s
                      AND heartbeat_at < now() - make_interval(secs => %s)
                    FOR UPDATE
                    """,
                    (
                        turn_id,
                        TURN_PROCESSING,
                        TURN_FINALIZING,
                        lease_id,
                        float(stale_after_seconds),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    conn.commit()
                    return self._require_turn(turn_id)
                if assistant_answer is not None:
                    partial = str(row["partial_answer"] or "")
                    if not partial:
                        version = int(row["stream_version"] or 0) + 1
                        cursor.execute(
                            """
                            UPDATE conversation_turns
                            SET partial_answer = %s, stream_version = %s
                            WHERE id = %s
                            """,
                            (assistant_answer, version, turn_id),
                        )
                        self._insert_event(
                            cursor,
                            turn_id,
                            "content_snapshot",
                            {"content": assistant_answer, "version": version},
                        )
                    cursor.execute(
                        """
                        UPDATE conversation_turns
                        SET status = %s, answer = %s, completed_at = now(),
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (TURN_DONE, assistant_answer, turn_id),
                    )
                    terminal: dict[str, Any] = {"status": TURN_DONE}
                else:
                    error = TurnError(
                        code="interrupted",
                        message="处理进程意外中断，请重试",
                        retryable=True,
                    )
                    cursor.execute(
                        """
                        UPDATE conversation_turns
                        SET status = %s, error = %s, error_code = %s,
                            error_message = %s, error_retryable = %s,
                            completed_at = now(), updated_at = now()
                        WHERE id = %s
                        """,
                        (
                            TURN_FAILED,
                            error.message,
                            error.code,
                            error.message,
                            error.retryable,
                            turn_id,
                        ),
                    )
                    terminal = {
                        "status": TURN_FAILED,
                        "error": {
                            "error_code": error.code,
                            "message": error.message,
                            "retryable": error.retryable,
                        },
                    }
                self._insert_event(cursor, turn_id, "turn_terminal", terminal)
                if (
                    assistant_answer is not None
                    and self.post_response_memory_enabled
                ):
                    self._insert_recovered_post_response_job(
                        cursor,
                        turn_id=turn_id,
                    )
            conn.commit()
        return self._require_turn(turn_id)

    def _mark_terminal(
        self,
        turn_id: str,
        lease_id: str,
        *,
        status: str,
        answer: str | None,
        error: TurnError | None,
        execution_result: TurnExecutionResult | None = None,
    ) -> Turn:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                allowed_statuses = (
                    {TURN_PROCESSING, TURN_FINALIZING}
                    if status in {TURN_DONE, TURN_FAILED}
                    else {TURN_PROCESSING}
                )
                row = self._lock_leased(
                    cursor,
                    turn_id,
                    lease_id,
                    allowed_statuses=allowed_statuses,
                )
                if status == TURN_DONE and row["cancel_requested_at"] is not None:
                    raise InvalidTurnTransition("Cancellation was requested before done")
                if (
                    execution_result is not None
                    and self.post_response_memory_enabled
                    and execution_result.enqueue_post_response_memory
                ):
                    self._validate_success_messages(
                        cursor,
                        turn_id=turn_id,
                        user_id=int(row["user_id"]),
                        session_id=int(row["session_id"]),
                        result=execution_result,
                    )
                partial = str(row["partial_answer"] or "")
                if status == TURN_DONE and answer is not None and not partial:
                    version = int(row["stream_version"] or 0) + 1
                    cursor.execute(
                        """
                        UPDATE conversation_turns
                        SET partial_answer = %s, stream_version = %s
                        WHERE id = %s
                        """,
                        (answer, version, turn_id),
                    )
                    self._insert_event(
                        cursor,
                        turn_id,
                        "content_snapshot",
                        {"content": answer, "version": version},
                    )
                cursor.execute(
                    """
                    UPDATE conversation_turns
                    SET status = %s, answer = %s, error = %s,
                        error_code = %s, error_message = %s,
                        error_retryable = %s, completed_at = now(),
                        heartbeat_at = now(), updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        status,
                        answer,
                        error.message if error else None,
                        error.code if error else None,
                        error.message if error else None,
                        error.retryable if error else None,
                        turn_id,
                    ),
                )
                terminal: dict[str, Any] = {"status": status}
                if error is not None:
                    terminal["error"] = {
                        "error_code": error.code,
                        "message": error.message,
                        "retryable": error.retryable,
                    }
                self._insert_event(cursor, turn_id, "turn_terminal", terminal)
                if (
                    status == TURN_DONE
                    and execution_result is not None
                    and self.post_response_memory_enabled
                    and execution_result.enqueue_post_response_memory
                ):
                    self._insert_post_response_job(
                        cursor,
                        turn_id=turn_id,
                        user_id=int(row["user_id"]),
                        session_id=int(row["session_id"]),
                        result=execution_result,
                    )
            conn.commit()
        return self._require_turn(turn_id)

    @staticmethod
    def _validate_success_messages(
        cursor: Any,
        *,
        turn_id: str,
        user_id: int,
        session_id: int,
        result: TurnExecutionResult,
    ) -> None:
        cursor.execute(
            """
            SELECT id, user_id, session_id, role, turn_id
            FROM conversation_messages
            WHERE id = ANY(%s)
            """,
            ([result.user_message_id, result.assistant_message_id],),
        )
        messages = {str(row["id"]): row for row in cursor.fetchall()}
        expected = {
            result.user_message_id: "user",
            result.assistant_message_id: "assistant",
        }
        if set(messages) != set(expected):
            raise InvalidTurnTransition(
                "Successful turn messages were not durably persisted"
            )
        for message_id, role in expected.items():
            message = messages[message_id]
            if (
                int(message["user_id"]) != user_id
                or int(message["session_id"]) != session_id
                or str(message["role"]) != role
                or str(message["turn_id"]) != str(turn_id)
            ):
                raise InvalidTurnTransition(
                    "Successful turn messages do not match the active turn"
                )

    @staticmethod
    def _insert_post_response_job(
        cursor: Any,
        *,
        turn_id: str,
        user_id: int,
        session_id: int,
        result: TurnExecutionResult,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO post_response_memory_jobs (
                id, turn_id, user_id, session_id, user_message_id,
                assistant_message_id, explicit_memory_ids, status, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (turn_id) DO NOTHING
            """,
            (
                str(uuid.uuid4()),
                turn_id,
                user_id,
                session_id,
                result.user_message_id,
                result.assistant_message_id,
                Jsonb(list(result.explicit_memory_ids)),
                "pending",
            ),
        )

    def _insert_recovered_post_response_job(
        self,
        cursor: Any,
        *,
        turn_id: str,
    ) -> None:
        cursor.execute(
            """
            SELECT id, user_id, session_id, role
            FROM conversation_messages
            WHERE turn_id = %s AND role IN ('user', 'assistant')
            """,
            (turn_id,),
        )
        messages = {str(row["role"]): row for row in cursor.fetchall()}
        if set(messages) != {"user", "assistant"}:
            raise InvalidTurnTransition(
                "Recovered turn messages were not durably persisted"
            )
        user_message = messages["user"]
        assistant_message = messages["assistant"]
        if (
            int(user_message["user_id"]) != int(assistant_message["user_id"])
            or int(user_message["session_id"])
            != int(assistant_message["session_id"])
        ):
            raise InvalidTurnTransition(
                "Recovered turn messages do not share one session boundary"
            )
        result = TurnExecutionResult(
            answer="",
            user_message_id=str(user_message["id"]),
            assistant_message_id=str(assistant_message["id"]),
            enqueue_post_response_memory=True,
        )
        self._insert_post_response_job(
            cursor,
            turn_id=turn_id,
            user_id=int(user_message["user_id"]),
            session_id=int(user_message["session_id"]),
            result=result,
        )

    @staticmethod
    def _lock_active(cursor: Any, turn_id: str, lease_id: str) -> Mapping[str, Any]:
        return PostgresTurnStore._lock_leased(
            cursor,
            turn_id,
            lease_id,
            allowed_statuses={TURN_PROCESSING},
        )

    @staticmethod
    def _lock_leased(
        cursor: Any,
        turn_id: str,
        lease_id: str,
        *,
        allowed_statuses: set[str],
    ) -> Mapping[str, Any]:
        cursor.execute(
            """
            SELECT status, lease_id, stream_version, partial_answer,
                   cancel_requested_at, user_id, session_id
            FROM conversation_turns
            WHERE id = %s
            FOR UPDATE
            """,
            (turn_id,),
        )
        row = cursor.fetchone()
        if (
            row is None
            or str(row["status"]) not in allowed_statuses
            or str(row["lease_id"]) != str(lease_id)
        ):
            raise InvalidTurnTransition("Turn lease is no longer active")
        return cast(Mapping[str, Any], row)

    @staticmethod
    def _insert_event(
        cursor: Any,
        turn_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> TurnEvent:
        cursor.execute(
            """
            UPDATE conversation_turns
            SET next_event_seq = next_event_seq + 1
            WHERE id = %s
            RETURNING next_event_seq
            """,
            (turn_id,),
        )
        seq_row = cursor.fetchone()
        if seq_row is None:  # pragma: no cover - protected by owning transaction
            raise RuntimeError("Cannot allocate turn event sequence")
        seq = int(seq_row["next_event_seq"])
        cursor.execute(
            """
            INSERT INTO conversation_turn_events (
                turn_id, seq, event_type, payload_json
            )
            VALUES (%s, %s, %s, %s)
            RETURNING created_at
            """,
            (turn_id, seq, event_type, Jsonb(payload)),
        )
        created = cursor.fetchone()
        return TurnEvent(
            turn_id=turn_id,
            seq=seq,
            type=event_type,
            data=dict(payload),
            occurred_at=_ts(created["created_at"]) or "",
        )

    def _require_turn(self, turn_id: str) -> Turn:
        turn = self.get_turn(turn_id)
        if turn is None:  # pragma: no cover - defensive invariant
            raise RuntimeError(f"Turn not found: {turn_id}")
        return turn


def _prefixed_columns(alias: str) -> str:
    return ", ".join(
        f"{alias}.{column.strip()}"
        for column in _TURN_COLUMNS.replace("\n", " ").split(",")
        if column.strip()
    )


def _row_to_turn(row: Mapping[str, Any]) -> Turn:
    return Turn(
        id=str(row["id"]),
        user_id=int(row["user_id"]),
        session_id=int(row["session_id"]),
        content=str(row["content"]),
        status=str(row["status"]),
        answer=row["answer"],
        error=row["error"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        error_retryable=row["error_retryable"],
        metadata=dict(row["metadata_json"] or {}),
        attempts=int(row["attempts"] or 0),
        created_at=_ts(row["created_at"]),
        updated_at=_ts(row["updated_at"]),
        started_at=_ts(row["started_at"]),
        finished_at=_ts(row["completed_at"]),
        partial_answer=str(row["partial_answer"] or ""),
        stream_version=int(row["stream_version"] or 0),
        next_event_seq=int(row["next_event_seq"] or 0),
        cancel_requested_at=_ts(row["cancel_requested_at"]),
        heartbeat_at=_ts(row["heartbeat_at"]),
        lease_id=str(row["lease_id"]) if row["lease_id"] is not None else None,
        retry_of_turn_id=(
            str(row["retry_of_turn_id"])
            if row["retry_of_turn_id"] is not None
            else None
        ),
    )


def _row_to_event(row: Mapping[str, Any]) -> TurnEvent:
    return TurnEvent(
        turn_id=str(row["turn_id"]),
        seq=int(row["seq"]),
        type=str(row["event_type"]),
        data=dict(row["payload_json"] or {}),
        occurred_at=_ts(row["created_at"]) or "",
    )


def _uuid_or_none(value: object) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return None


def _ts(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)
