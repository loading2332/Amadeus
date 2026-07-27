"""add web authentication identities and refresh sessions

Revision ID: 20260727_0007
Revises: 20260718_0005
Create Date: 2026-07-27 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_0007"
down_revision: str | None = "20260718_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_subject", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("provider", "provider_subject", name="uq_user_identities_provider_subject"),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by_id", sa.Uuid(), sa.ForeignKey("auth_refresh_tokens.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("token_hash", name="uq_auth_refresh_tokens_token_hash"),
    )
    op.create_index("ix_auth_refresh_tokens_user_id", "auth_refresh_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_auth_refresh_tokens_user_id", table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")
    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_table("user_identities")
