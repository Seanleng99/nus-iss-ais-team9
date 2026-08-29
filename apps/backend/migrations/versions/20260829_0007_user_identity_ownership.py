"""Bind financial profiles to authenticated OIDC identities.

Revision ID: 20260829_0007
Revises: 20260824_0006
Create Date: 2026-08-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0007"
down_revision: str | None = "20260824_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("owner_issuer", sa.String(512), nullable=True))
    op.add_column("users", sa.Column("owner_subject", sa.String(255), nullable=True))
    op.create_check_constraint(
        "owner_identity_complete",
        "users",
        "(owner_issuer IS NULL) = (owner_subject IS NULL)",
    )
    op.create_index(
        "ix_users_owner_identity",
        "users",
        ["owner_issuer", "owner_subject"],
    )


def downgrade() -> None:
    op.drop_index("ix_users_owner_identity", table_name="users")
    op.drop_constraint("owner_identity_complete", "users", type_="check")
    op.drop_column("users", "owner_subject")
    op.drop_column("users", "owner_issuer")
