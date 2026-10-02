"""Conversation-scoped spending record drafts."""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0014"
down_revision = "20260930_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_sessions", sa.Column("pending_transaction", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("chat_sessions", "pending_transaction")
