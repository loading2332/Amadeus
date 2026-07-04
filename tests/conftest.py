from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)  # type: ignore[untyped-decorator]
def _default_postgres_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "AMADEUS_POSTGRES_DSN",
        "postgresql://amadeus:amadeus@localhost:5432/amadeus",
    )
