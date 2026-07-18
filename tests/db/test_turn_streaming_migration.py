from __future__ import annotations

import uuid

import psycopg
from alembic import command
from alembic.config import Config
from tests.db.postgres_helpers import clean_postgres, postgres_dsn


def test_streaming_migration_reconciles_legacy_active_turns(monkeypatch) -> None:
    database = clean_postgres()
    database.close()
    monkeypatch.setenv("AMADEUS_POSTGRES_DSN", postgres_dsn())
    config = Config("alembic.ini")
    user_id = 99101
    session_id = 99101
    oldest_pending = uuid.uuid4()
    duplicate_pending = uuid.uuid4()
    legacy_processing = uuid.uuid4()

    command.downgrade(config, "20260711_0004")
    try:
        with psycopg.connect(postgres_dsn()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (id) VALUES (%s)",
                    (user_id,),
                )
                cursor.execute(
                    """
                    INSERT INTO conversation_sessions (id, user_id, title)
                    VALUES (%s, %s, 'legacy migration')
                    """,
                    (session_id, user_id),
                )
                cursor.executemany(
                    """
                    INSERT INTO conversation_turns (
                        id, user_id, session_id, content, status, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            oldest_pending,
                            user_id,
                            session_id,
                            "oldest",
                            "pending",
                            "2026-07-18T00:00:00+00:00",
                        ),
                        (
                            duplicate_pending,
                            user_id,
                            session_id,
                            "duplicate",
                            "pending",
                            "2026-07-18T00:00:01+00:00",
                        ),
                        (
                            legacy_processing,
                            user_id,
                            session_id,
                            "processing",
                            "processing",
                            "2026-07-18T00:00:02+00:00",
                        ),
                    ],
                )

        command.upgrade(config, "head")

        with psycopg.connect(postgres_dsn()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, status, error_code, error_retryable
                    FROM conversation_turns
                    WHERE session_id = %s
                    ORDER BY created_at ASC
                    """,
                    (session_id,),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT turn_id, event_type, payload_json
                    FROM conversation_turn_events
                    WHERE turn_id IN (%s, %s)
                    ORDER BY turn_id
                    """,
                    (duplicate_pending, legacy_processing),
                )
                events = cursor.fetchall()

        assert rows == [
            (oldest_pending, "pending", None, None),
            (duplicate_pending, "failed", "interrupted", True),
            (legacy_processing, "failed", "interrupted", True),
        ]
        assert len(events) == 2
        assert all(event[1] == "turn_terminal" for event in events)
        assert all(event[2]["status"] == "failed" for event in events)
    finally:
        command.upgrade(config, "head")
        with psycopg.connect(postgres_dsn()) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
