"""align memory embedding dimension with Qwen text-embedding-v4

Revision ID: 20260704_0003
Revises: 20260704_0002
Create Date: 2026-07-04 00:00:02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260704_0003"
down_revision: str | None = "20260704_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_items_embedding")
    op.execute("UPDATE memory_items SET embedding = NULL")
    op.execute("ALTER TABLE memory_items ALTER COLUMN embedding TYPE vector(1024)")
    op.execute(
        """
        CREATE INDEX ix_memory_items_embedding
        ON memory_items USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_items_embedding")
    op.execute("UPDATE memory_items SET embedding = NULL")
    op.execute("ALTER TABLE memory_items ALTER COLUMN embedding TYPE vector(1536)")
    op.execute(
        """
        CREATE INDEX ix_memory_items_embedding
        ON memory_items USING ivfflat (embedding vector_cosine_ops)
        """
    )
