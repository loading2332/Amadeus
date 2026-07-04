"""add memory_items.content_hash column

Revision ID: 20260704_0002
Revises: 20260704_0001
Create Date: 2026-07-04 00:00:01
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260704_0002"
down_revision: str | None = "20260704_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _memory_content_hash(summary: str, memory_type: str) -> str:
    normalized = " ".join(summary.split())
    return hashlib.sha256(f"{memory_type}:{normalized}".encode()).hexdigest()[:16]


def upgrade() -> None:
    # content_hash backs source_ref-independent reinforcement: two writes of the
    # same (user_id, memory_type, normalized summary) reinforce one row instead
    # of producing duplicates. Keep this backfill aligned with
    # ``amadeus.memory.store._content_hash``; database md5 would split the
    # runtime and migration semantics.
    op.add_column(
        "memory_items",
        sa.Column("content_hash", sa.Text(), nullable=False, server_default=""),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, memory_type, summary
            FROM memory_items
            WHERE content_hash = ''
            """
        )
    )
    for row in rows.mappings():
        connection.execute(
            sa.text(
                """
                UPDATE memory_items
                SET content_hash = :content_hash
                WHERE id = :id
                """
            ),
            {
                "content_hash": _memory_content_hash(
                    str(row["summary"] or ""),
                    str(row["memory_type"] or ""),
                ),
                "id": row["id"],
            },
        )
    op.create_index(
        "ix_memory_items_user_type_source",
        "memory_items",
        ["user_id", "memory_type", "source_ref"],
    )
    op.create_unique_constraint(
        "uq_memory_items_user_type_content_hash",
        "memory_items",
        ["user_id", "memory_type", "content_hash"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_memory_items_user_type_content_hash", "memory_items", type_="unique"
    )
    op.drop_index("ix_memory_items_user_type_source", table_name="memory_items")
    op.drop_column("memory_items", "content_hash")
