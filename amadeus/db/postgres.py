from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from pgvector.psycopg import register_vector  # type: ignore[import-untyped]
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class PostgresExtensionError(RuntimeError):
    """Raised when a required PostgreSQL extension is unavailable."""


@dataclass(frozen=True)
class PostgresConfig:
    dsn: str
    min_pool_size: int = 1
    max_pool_size: int = 10

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("Missing Amadeus runtime config: AMADEUS_POSTGRES_DSN")
        if self.min_pool_size < 0:
            raise ValueError("PostgreSQL min_pool_size must be >= 0")
        if self.max_pool_size < 1:
            raise ValueError("PostgreSQL max_pool_size must be >= 1")
        if self.min_pool_size > self.max_pool_size:
            raise ValueError("PostgreSQL min_pool_size must be <= max_pool_size")


def _configure_vector_adapter(conn: Any) -> None:
    """Register the pgvector psycopg adapter on a pooled connection.

    Lets stores pass ``pgvector.Vector`` (or numpy arrays) as query parameters
    and receive pgvector columns back as arrays, instead of hand-formatting
    ``[v1,v2,...]::vector`` string literals. Registered per-connection because
    pgvector's adapter must bind the connection-specific ``vector`` type OID.
    """
    register_vector(conn)


class PostgresDatabase:
    """Small PostgreSQL lifecycle boundary shared by native-SQL stores."""

    def __init__(self, config: PostgresConfig) -> None:
        self.config = config
        self._pool = ConnectionPool(
            conninfo=config.dsn,
            min_size=config.min_pool_size,
            max_size=config.max_pool_size,
            kwargs={"row_factory": dict_row},
            configure=_configure_vector_adapter,
            open=False,
        )

    def open(self) -> None:
        self._pool.open()
        with self.connection() as conn:
            check_vector_extension(conn)

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        with self._pool.connection() as conn:
            yield conn


def check_vector_extension(conn: Any) -> None:
    """Fail fast unless PostgreSQL has the pgvector extension installed."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_extension WHERE extname = %s",
            ("vector",),
        )
        row = cursor.fetchone()
    if row is None:
        raise PostgresExtensionError(
            "PostgreSQL extension 'vector' is required; run Alembic migrations "
            "against a pgvector-enabled database before starting Amadeus."
        )


def normalize_psycopg_dsn(dsn: str) -> str:
    """Return a psycopg runtime DSN from app/Alembic-style PostgreSQL URLs."""
    stripped = dsn.strip()
    if stripped.startswith("postgresql+psycopg://"):
        return "postgresql://" + stripped.removeprefix("postgresql+psycopg://")
    return stripped
