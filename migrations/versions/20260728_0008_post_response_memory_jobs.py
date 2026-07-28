"""add durable post-response memory jobs

Revision ID: 20260728_0008
Revises: 20260727_0007
Create Date: 2026-07-28 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0008"
down_revision: str | None = "20260727_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "post_response_memory_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "turn_id",
            sa.Uuid(),
            sa.ForeignKey("conversation_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.BigInteger(),
            sa.ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_message_id",
            sa.Text(),
            sa.ForeignKey("conversation_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assistant_message_id",
            sa.Text(),
            sa.ForeignKey("conversation_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "explicit_memory_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_id", sa.Uuid()),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed')",
            name="ck_post_response_memory_jobs_status",
        ),
        sa.UniqueConstraint(
            "turn_id",
            name="uq_post_response_memory_jobs_turn_id",
        ),
    )
    op.create_index(
        "ix_post_response_memory_jobs_claim",
        "post_response_memory_jobs",
        ["status", "created_at", "id"],
    )
    op.create_index(
        "uq_post_response_memory_jobs_processing_session",
        "post_response_memory_jobs",
        ["user_id", "session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'processing'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_post_response_memory_jobs_processing_session",
        table_name="post_response_memory_jobs",
    )
    op.drop_index(
        "ix_post_response_memory_jobs_claim",
        table_name="post_response_memory_jobs",
    )
    op.drop_table("post_response_memory_jobs")
