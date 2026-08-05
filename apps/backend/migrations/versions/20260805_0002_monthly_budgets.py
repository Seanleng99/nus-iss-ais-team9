"""Create monthly budgets and category limits.

Revision ID: 20260805_0002
Revises: 20260805_0001
Create Date: 2026-08-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0002"
down_revision: str | None = "20260805_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monthly_budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_monthly_budgets_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monthly_budgets")),
        sa.UniqueConstraint(
            "user_id", "period_start", name="uq_monthly_budgets_user_period"
        ),
    )
    op.create_index(
        "ix_monthly_budgets_user_period",
        "monthly_budgets",
        ["user_id", "period_start"],
    )
    op.create_table(
        "budget_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("budget_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("limit_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "limit_amount >= 0",
            name=op.f("ck_budget_categories_limit_amount_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["budget_id"],
            ["monthly_budgets.id"],
            name=op.f("fk_budget_categories_budget_id_monthly_budgets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budget_categories")),
        sa.UniqueConstraint(
            "budget_id", "category", name="uq_budget_categories_budget_category"
        ),
    )


def downgrade() -> None:
    op.drop_table("budget_categories")
    op.drop_index("ix_monthly_budgets_user_period", table_name="monthly_budgets")
    op.drop_table("monthly_budgets")
