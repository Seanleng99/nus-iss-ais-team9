"""Persist conversation-scoped budget drafts awaiting explicit confirmation."""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0010"
down_revision = "20260926_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_sessions", sa.Column("pending_budget", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("chat_sessions", "pending_budget")
