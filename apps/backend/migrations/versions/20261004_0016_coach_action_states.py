"""Persist conversation-scoped transaction edit and last-saved references."""

import sqlalchemy as sa
from alembic import op

revision = "20261004_0016"
down_revision = "20261002_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "coach_action_states",
        sa.Column("session_id", sa.String(128), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(128), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("last_saved", sa.JSON(), nullable=True),
        sa.Column("pending_edit", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("coach_action_states")
