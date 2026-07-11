from __future__ import annotations

import pytest
from tests.db import postgres_helpers


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_require_postgres_caches_unavailable_database(monkeypatch):
    dsn = "postgresql://amadeus:amadeus@localhost:5432/amadeus"
    calls: list[tuple[str, int]] = []

    def fail_connect(conninfo: str, *, connect_timeout: int):
        calls.append((conninfo, connect_timeout))
        raise postgres_helpers.psycopg.OperationalError("database is offline")

    monkeypatch.setenv("AMADEUS_POSTGRES_DSN", dsn)
    monkeypatch.setattr(postgres_helpers, "_probe_results", {})
    monkeypatch.setattr(postgres_helpers.psycopg, "connect", fail_connect)

    for _ in range(2):
        with pytest.raises(pytest.skip.Exception, match="database is offline"):
            postgres_helpers.require_postgres()

    assert calls == [(dsn, 1)]


def test_require_postgres_caches_success_and_closes_probe(monkeypatch):
    dsn = "postgresql://amadeus:amadeus@localhost:5432/amadeus"
    connection = FakeConnection()
    calls: list[tuple[str, int]] = []

    def connect(conninfo: str, *, connect_timeout: int) -> FakeConnection:
        calls.append((conninfo, connect_timeout))
        return connection

    monkeypatch.setenv("AMADEUS_POSTGRES_DSN", dsn)
    monkeypatch.setattr(postgres_helpers, "_probe_results", {})
    monkeypatch.setattr(postgres_helpers.psycopg, "connect", connect)

    postgres_helpers.require_postgres()
    postgres_helpers.require_postgres()

    assert calls == [(dsn, 1)]
    assert connection.closed is True
