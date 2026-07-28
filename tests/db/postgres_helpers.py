from __future__ import annotations

import os

import psycopg
import pytest
from amadeus.db import PostgresConfig, PostgresDatabase

_POSTGRES_PROBE_TIMEOUT_SECONDS = 1
_probe_results: dict[str, str | None] = {}


def postgres_dsn() -> str:
    return os.environ.get(
        "AMADEUS_POSTGRES_DSN",
        "postgresql://amadeus:amadeus@localhost:5432/amadeus",
    )


def require_postgres() -> None:
    dsn = postgres_dsn()
    if dsn in _probe_results:
        failure = _probe_results[dsn]
        if failure is not None:
            pytest.skip(failure)
        return

    try:
        connection = psycopg.connect(
            dsn,
            connect_timeout=_POSTGRES_PROBE_TIMEOUT_SECONDS,
        )
    except psycopg.Error as exc:
        failure = f"PostgreSQL test database unavailable: {exc}"
        _probe_results[dsn] = failure
        pytest.skip(failure)

    connection.close()
    _probe_results[dsn] = None


def clean_postgres() -> PostgresDatabase:
    db = PostgresDatabase(PostgresConfig(dsn=postgres_dsn()))
    try:
        db.open()
    except Exception as exc:
        pytest.skip(f"PostgreSQL test database unavailable: {exc}")
    with db.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE
                    post_response_memory_jobs,
                    memory_markdown_state,
                    memory_markdown_writes,
                    memory_replacements,
                    memory_items,
                    conversation_turn_events,
                    conversation_turns,
                    conversation_messages,
                    conversation_sessions,
                    users
                RESTART IDENTITY CASCADE
                """
            )
        conn.commit()
    return db
