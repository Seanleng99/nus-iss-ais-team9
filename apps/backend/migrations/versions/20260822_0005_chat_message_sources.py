"""Persist source citations with assistant chat messages.

Revision ID: 20260822_0005
Revises: 20260820_0004
Create Date: 2026-08-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0005"
down_revision: str | None = "20260820_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column(
            "sources",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.alter_column("chat_messages", "sources", server_default=None)


def downgrade() -> None:
    op.drop_column("chat_messages", "sources")
