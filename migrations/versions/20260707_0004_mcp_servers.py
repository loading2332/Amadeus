"""mcp_servers table

Revision ID: 20260707_0004
Revises: 20260704_0003
Create Date: 2026-07-07 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260707_0004"
down_revision: str | None = "20260704_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("transport_type", sa.Text(), nullable=False),
        sa.Column(
            "command",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "env",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column(
            "headers",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "authorized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("mcp_servers")