"""postgres foundation schema

Revision ID: 20260704_0001
Revises:
Create Date: 2026-07-04 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260704_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("external_key", sa.Text(), unique=True),
        sa.Column("display_name", sa.Text()),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_consolidated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_conversation_sessions_user_id", "conversation_sessions", ["user_id"])
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "extra_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["session_id"], ["conversation_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "session_id", "seq", name="uq_conversation_messages_user_session_seq"),
    )
    op.create_index("ix_conversation_messages_user_session", "conversation_messages", ["user_id", "session_id"])
    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["session_id"], ["conversation_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_conversation_turns_pending", "conversation_turns", ["status", "created_at"])
    op.create_index("ix_conversation_turns_user_session_status", "conversation_turns", ["user_id", "session_id", "status"])
    op.execute(
        """
        CREATE TABLE memory_items (
            id TEXT PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            summary TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            happened_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'active',
            embedding vector(1024),
            extra_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            reinforcement INTEGER NOT NULL DEFAULT 1,
            emotional_weight DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index("ix_memory_items_user_status", "memory_items", ["user_id", "status"])
    op.create_index("ix_memory_items_source_ref", "memory_items", ["user_id", "source_ref"])
    op.execute(
        "CREATE INDEX ix_memory_items_embedding ON memory_items USING hnsw (embedding vector_cosine_ops)"
    )
    op.create_table(
        "memory_replacements",
        sa.Column("old_item_id", sa.Text(), nullable=False),
        sa.Column("new_item_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["old_item_id"], ["memory_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["new_item_id"], ["memory_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("old_item_id", "new_item_id", "source_ref"),
    )
    op.create_table(
        "memory_markdown_writes",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("user_id", "source_ref", "kind", "target"),
    )
    op.create_table(
        "memory_markdown_state",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("conversation_sessions.id", ondelete="CASCADE")),
        sa.Column("state_key", sa.Text(), nullable=False),
        sa.Column(
            "state_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("user_id", "state_key"),
    )


def downgrade() -> None:
    op.drop_table("memory_markdown_state")
    op.drop_table("memory_markdown_writes")
    op.drop_table("memory_replacements")
    op.drop_index("ix_memory_items_embedding", table_name="memory_items")
    op.drop_index("ix_memory_items_source_ref", table_name="memory_items")
    op.drop_index("ix_memory_items_user_status", table_name="memory_items")
    op.drop_table("memory_items")
    op.drop_index("ix_conversation_turns_user_session_status", table_name="conversation_turns")
    op.drop_index("ix_conversation_turns_pending", table_name="conversation_turns")
    op.drop_table("conversation_turns")
    op.drop_index("ix_conversation_messages_user_session", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversation_sessions_user_id", table_name="conversation_sessions")
    op.drop_table("conversation_sessions")
    op.drop_table("users")
