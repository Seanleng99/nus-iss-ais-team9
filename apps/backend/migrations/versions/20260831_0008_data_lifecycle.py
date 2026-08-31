"""Add activity metadata for governed data lifecycle enforcement.

Revision ID: 20260831_0008
Revises: 20260829_0007
Create Date: 2026-08-31
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0008"
down_revision: str | None = "20260829_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_users_last_activity_at",
        "users",
        ["last_activity_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_users_last_activity_at", table_name="users")
    op.drop_column("users", "last_activity_at")
