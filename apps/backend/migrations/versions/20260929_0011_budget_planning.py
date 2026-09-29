"""Persist confirmed income and savings separately from expense category limits."""

import sqlalchemy as sa
from alembic import op

revision = "20260929_0011"
down_revision = "20260928_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("monthly_budgets", sa.Column("planning", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("monthly_budgets", "planning")
