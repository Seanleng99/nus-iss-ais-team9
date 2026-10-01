"""Backend-owned facts and clarification state within a retained chat."""

import sqlalchemy as sa
from alembic import op

revision = "20261002_0014"
down_revision = "20260930_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_sessions", sa.Column("conversation_state", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("chat_sessions", "conversation_state")
