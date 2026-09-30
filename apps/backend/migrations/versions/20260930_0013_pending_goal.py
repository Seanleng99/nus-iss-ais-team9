"""Conversation-scoped goal change drafts."""

import sqlalchemy as sa
from alembic import op

revision = "20260930_0013"
down_revision = "20260930_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_sessions", sa.Column("pending_goal", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("chat_sessions", "pending_goal")
