"""Create initial financial data schema.

Revision ID: 20260805_0001
Revises:
Create Date: 2026-08-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_table(
        "financial_profiles",
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("monthly_income", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("risk_tolerance", sa.String(length=32), nullable=True),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "monthly_income IS NULL OR monthly_income >= 0",
            name=op.f("ck_financial_profiles_monthly_income_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_financial_profiles_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_financial_profiles")),
    )
    op.create_table(
        "financial_goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("target_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("current_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("target_months", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "current_amount >= 0", name=op.f("ck_financial_goals_current_amount_non_negative")
        ),
        sa.CheckConstraint(
            "target_amount >= 0", name=op.f("ck_financial_goals_target_amount_non_negative")
        ),
        sa.CheckConstraint(
            "target_months > 0 AND target_months <= 600",
            name=op.f("ck_financial_goals_target_months_range"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_financial_goals_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_goals")),
    )
    op.create_index("ix_financial_goals_user", "financial_goals", ["user_id"])
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("recurring", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_transactions_amount_non_negative")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_transactions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    op.create_index("ix_transactions_user_category", "transactions", ["user_id", "category"])
    op.create_index("ix_transactions_user_occurred", "transactions", ["user_id", "occurred_on"])


def downgrade() -> None:
    op.drop_index("ix_transactions_user_occurred", table_name="transactions")
    op.drop_index("ix_transactions_user_category", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_financial_goals_user", table_name="financial_goals")
    op.drop_table("financial_goals")
    op.drop_table("financial_profiles")
    op.drop_table("users")
