from __future__ import annotations

import os

import pytest
from amadeus.db import PostgresConfig, PostgresDatabase


def postgres_dsn() -> str:
    return os.environ.get(
        "AMADEUS_POSTGRES_DSN",
        "postgresql://amadeus:amadeus@localhost:5432/amadeus",
    )


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
                    memory_markdown_state,
                    memory_markdown_writes,
                    memory_replacements,
                    memory_items,
                    conversation_turns,
                    conversation_messages,
                    conversation_sessions,
                    users
                RESTART IDENTITY CASCADE
                """
            )
        conn.commit()
    return db
