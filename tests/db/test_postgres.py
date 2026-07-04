from __future__ import annotations

import pytest
from amadeus.db.postgres import (
    PostgresConfig,
    PostgresExtensionError,
    check_vector_extension,
)


class FakeCursor:
    def __init__(self, row: tuple[int] | None) -> None:
        self.row = row
        self.executed: tuple[str, tuple[str, ...]] | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[str, ...]) -> None:
        self.executed = (query, params)

    def fetchone(self) -> tuple[int] | None:
        return self.row


class FakeConnection:
    def __init__(self, row: tuple[int] | None) -> None:
        self.cursor_obj = FakeCursor(row)

    def cursor(self) -> FakeCursor:
        return self.cursor_obj


def test_postgres_config_requires_dsn() -> None:
    with pytest.raises(ValueError, match="AMADEUS_POSTGRES_DSN"):
        PostgresConfig(dsn="")


def test_check_vector_extension_accepts_installed_extension() -> None:
    conn = FakeConnection((1,))

    check_vector_extension(conn)

    assert conn.cursor_obj.executed == (
        "SELECT 1 FROM pg_extension WHERE extname = %s",
        ("vector",),
    )


def test_check_vector_extension_fails_when_missing() -> None:
    conn = FakeConnection(None)

    with pytest.raises(PostgresExtensionError, match="vector"):
        check_vector_extension(conn)
