"""Typed ledger entries and owned financial planning preferences."""

import sqlalchemy as sa
from alembic import op

revision = "20260930_0012"
down_revision = "20260929_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "transactions",
        sa.Column("transaction_type", sa.String(16), nullable=False, server_default="expense"),
    )
    op.create_table(
        "planning_preferences",
        sa.Column(
            "user_id",
            sa.String(128),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade():
    op.drop_table("planning_preferences")
    op.drop_column("transactions", "transaction_type")
