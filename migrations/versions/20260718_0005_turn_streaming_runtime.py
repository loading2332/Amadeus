"""add durable turn streaming state and events

Revision ID: 20260718_0005
Revises: 20260711_0004
Create Date: 2026-07-18 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0005"
down_revision: str | None = "20260711_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_turns",
        sa.Column("partial_answer", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("stream_version", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("next_event_seq", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
    )
    op.add_column("conversation_turns", sa.Column("lease_id", postgresql.UUID()))
    op.add_column(
        "conversation_turns",
        sa.Column(
            "retry_of_turn_id",
            postgresql.UUID(),
            sa.ForeignKey("conversation_turns.id"),
        ),
    )
    op.add_column("conversation_turns", sa.Column("error_code", sa.Text()))
    op.add_column("conversation_turns", sa.Column("error_message", sa.Text()))
    op.add_column("conversation_turns", sa.Column("error_retryable", sa.Boolean()))
    op.create_check_constraint(
        "ck_conversation_turns_retry_not_self",
        "conversation_turns",
        "retry_of_turn_id IS NULL OR retry_of_turn_id <> id",
    )
    op.create_index(
        "ix_conversation_turns_processing_heartbeat",
        "conversation_turns",
        ["status", "heartbeat_at"],
    )
    op.create_table(
        "conversation_turn_events",
        sa.Column(
            "turn_id",
            postgresql.UUID(),
            sa.ForeignKey("conversation_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("turn_id", "seq"),
    )
    op.create_index(
        "ix_conversation_turn_events_turn_created",
        "conversation_turn_events",
        ["turn_id", "created_at"],
    )
    op.execute(
        """
        WITH interrupted AS (
          UPDATE conversation_turns
          SET status = 'failed',
              error = '服务升级中断了处理，请重试',
              error_code = 'interrupted',
              error_message = '服务升级中断了处理，请重试',
              error_retryable = true,
              completed_at = now(),
              updated_at = now(),
              next_event_seq = next_event_seq + 1
          WHERE status = 'processing'
          RETURNING id, next_event_seq
        )
        INSERT INTO conversation_turn_events (
          turn_id, seq, event_type, payload_json
        )
        SELECT id,
               next_event_seq,
               'turn_terminal',
               jsonb_build_object(
                 'status', 'failed',
                 'error', jsonb_build_object(
                   'error_code', 'interrupted',
                   'message', '服务升级中断了处理，请重试',
                   'retryable', true
                 )
               )
        FROM interrupted
        """
    )
    op.execute(
        """
        WITH ranked AS (
          SELECT id,
                 row_number() OVER (
                   PARTITION BY user_id, session_id
                   ORDER BY created_at ASC, id ASC
                 ) AS position
          FROM conversation_turns
          WHERE status = 'pending'
        ), reconciled AS (
          UPDATE conversation_turns AS turn
          SET status = 'failed',
              error = '升级前存在多个排队请求，请重试',
              error_code = 'interrupted',
              error_message = '升级前存在多个排队请求，请重试',
              error_retryable = true,
              completed_at = now(),
              updated_at = now(),
              next_event_seq = next_event_seq + 1
          FROM ranked
          WHERE turn.id = ranked.id AND ranked.position > 1
          RETURNING turn.id, turn.next_event_seq
        )
        INSERT INTO conversation_turn_events (
          turn_id, seq, event_type, payload_json
        )
        SELECT id,
               next_event_seq,
               'turn_terminal',
               jsonb_build_object(
                 'status', 'failed',
                 'error', jsonb_build_object(
                   'error_code', 'interrupted',
                   'message', '升级前存在多个排队请求，请重试',
                   'retryable', true
                 )
               )
        FROM reconciled
        """
    )
    op.create_index(
        "uq_conversation_turns_active_session",
        "conversation_turns",
        ["user_id", "session_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'processing', 'finalizing')"
        ),
    )
    op.add_column(
        "conversation_messages",
        sa.Column(
            "turn_id",
            postgresql.UUID(),
            sa.ForeignKey("conversation_turns.id", ondelete="SET NULL"),
        ),
    )
    op.create_index(
        "uq_conversation_messages_turn_role",
        "conversation_messages",
        ["turn_id", "role"],
        unique=True,
        postgresql_where=sa.text("turn_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_conversation_messages_turn_role",
        table_name="conversation_messages",
    )
    op.drop_column("conversation_messages", "turn_id")
    op.drop_index(
        "ix_conversation_turn_events_turn_created",
        table_name="conversation_turn_events",
    )
    op.drop_table("conversation_turn_events")
    op.drop_index(
        "ix_conversation_turns_processing_heartbeat",
        table_name="conversation_turns",
    )
    op.drop_index("uq_conversation_turns_active_session", table_name="conversation_turns")
    op.drop_constraint(
        "ck_conversation_turns_retry_not_self",
        "conversation_turns",
        type_="check",
    )
    for column in (
        "error_retryable",
        "error_message",
        "error_code",
        "retry_of_turn_id",
        "lease_id",
        "heartbeat_at",
        "cancel_requested_at",
        "next_event_seq",
        "stream_version",
        "partial_answer",
    ):
        op.drop_column("conversation_turns", column)
