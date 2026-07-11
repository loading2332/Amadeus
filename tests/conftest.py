from __future__ import annotations

from functools import wraps

import pytest
from amadeus.db import PostgresDatabase

from tests.db.postgres_helpers import require_postgres


@pytest.fixture(autouse=True)
def _postgres_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "AMADEUS_POSTGRES_DSN",
        "postgresql://amadeus:amadeus@localhost:5432/amadeus",
    )

    original_open = PostgresDatabase.open

    @wraps(original_open)
    def open_after_probe(database: PostgresDatabase) -> None:
        require_postgres()
        original_open(database)

    monkeypatch.setattr(PostgresDatabase, "open", open_after_probe)
