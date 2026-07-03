from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

TURN_PENDING = "pending"
TURN_PROCESSING = "processing"
TURN_DONE = "done"
TURN_FAILED = "failed"
TERMINAL_TURN_STATUSES = {TURN_DONE, TURN_FAILED}


@dataclass(frozen=True)
class Turn:
    id: str
    session_key: str
    content: str
    status: str
    answer: str | None
    error: str | None
    metadata: dict[str, Any]
    attempts: int
    created_at: str | None
    updated_at: str | None
    started_at: str | None
    finished_at: str | None


class TurnStore:
    """SQLite-backed reliable queue for Web chat turns.

    The API deliberately mirrors the future PostgreSQL queue shape:
    create, claim, mark terminal, and read by id.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def create_turn(
        self,
        *,
        session_key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Turn:
        turn_id = str(uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_turns (
                    id,
                    session_key,
                    content,
                    status,
                    metadata_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    turn_id,
                    session_key,
                    content,
                    TURN_PENDING,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
        turn = self.get_turn(turn_id)
        if turn is None:  # pragma: no cover - defensive invariant
            raise RuntimeError(f"Created turn not found: {turn_id}")
        return turn

    def get_turn(self, turn_id: str) -> Turn | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_key, content, status, answer, error,
                       metadata_json, attempts, created_at, updated_at,
                       started_at, finished_at
                FROM conversation_turns
                WHERE id = ?
                """,
                (turn_id,),
            ).fetchone()
        return _row_to_turn(row) if row is not None else None

    def claim_next_pending(self) -> Turn | None:
        """Claim the oldest pending turn whose session is not already active."""

        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT id
                    FROM conversation_turns AS candidate
                    WHERE candidate.status = ?
                      AND NOT EXISTS (
                          SELECT 1
                          FROM conversation_turns AS active
                          WHERE active.status = ?
                            AND active.session_key = candidate.session_key
                      )
                    ORDER BY candidate.created_at ASC, candidate.rowid ASC
                    LIMIT 1
                    """,
                    (TURN_PENDING, TURN_PROCESSING),
                ).fetchone()
                if row is None:
                    conn.rollback()
                    return None
                turn_id = str(row["id"])
                conn.execute(
                    """
                    UPDATE conversation_turns
                    SET status = ?,
                        attempts = attempts + 1,
                        started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = ?
                    """,
                    (TURN_PROCESSING, turn_id, TURN_PENDING),
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()
        return self.get_turn(turn_id)

    def mark_done(self, turn_id: str, answer: str) -> Turn:
        return self._mark_terminal(
            turn_id,
            status=TURN_DONE,
            answer=answer,
            error=None,
        )

    def mark_failed(self, turn_id: str, error: str) -> Turn:
        return self._mark_terminal(
            turn_id,
            status=TURN_FAILED,
            answer=None,
            error=error,
        )

    def _mark_terminal(
        self,
        turn_id: str,
        *,
        status: str,
        answer: str | None,
        error: str | None,
    ) -> Turn:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE conversation_turns
                SET status = ?,
                    answer = ?,
                    error = ?,
                    finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ?
                """,
                (status, answer, error, turn_id, TURN_PROCESSING),
            )
            conn.commit()
        turn = self.get_turn(turn_id)
        if turn is None:  # pragma: no cover - defensive invariant
            raise RuntimeError(f"Turn not found after terminal update: {turn_id}")
        return turn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    answer TEXT,
                    error TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE INDEX IF NOT EXISTS ix_conversation_turns_status_created
                    ON conversation_turns(status, created_at, id);

                CREATE INDEX IF NOT EXISTS ix_conversation_turns_session_status
                    ON conversation_turns(session_key, status, created_at);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn


def _row_to_turn(row: Mapping[str, Any]) -> Turn:
    metadata_raw = row["metadata_json"] or "{}"
    try:
        metadata = json.loads(str(metadata_raw))
    except json.JSONDecodeError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return Turn(
        id=str(row["id"]),
        session_key=str(row["session_key"]),
        content=str(row["content"]),
        status=str(row["status"]),
        answer=row["answer"],
        error=row["error"],
        metadata=metadata,
        attempts=int(row["attempts"] or 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )
