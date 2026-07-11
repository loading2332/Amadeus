"""add trigram index for independent lexical memory retrieval

Revision ID: 20260711_0004
Revises: 20260704_0003
Create Date: 2026-07-11 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260711_0004"
down_revision: str | None = "20260704_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE INDEX ix_memory_items_summary_trgm
        ON memory_items USING gin (summary gin_trgm_ops)
        """
    )


def downgrade() -> None:
    # pg_trgm can be shared by other features; only remove this task-owned index.
    op.execute("DROP INDEX IF EXISTS ix_memory_items_summary_trgm")
