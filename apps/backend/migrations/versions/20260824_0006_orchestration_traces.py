"""Persist privacy-safe orchestration decision traces.

Revision ID: 20260824_0006
Revises: 20260822_0005
Create Date: 2026-08-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0006"
down_revision: str | None = "20260822_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orchestration_traces",
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), nullable=False),
        sa.Column("selected_agents", sa.JSON(), nullable=False),
        sa.Column("agent_results", sa.JSON(), nullable=False),
        sa.Column("audit", sa.JSON(), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("model_provider", sa.String(64), nullable=True),
        sa.Column("model_id", sa.String(256), nullable=True),
        sa.Column("prompt_set_version", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"],
            ["chat_messages.id"],
            name=op.f("fk_orchestration_traces_assistant_message_id_chat_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_orchestration_traces_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("trace_id", name=op.f("pk_orchestration_traces")),
        sa.UniqueConstraint(
            "assistant_message_id",
            name=op.f("uq_orchestration_traces_assistant_message_id"),
        ),
    )
    op.create_index(
        "ix_orchestration_traces_session_created",
        "orchestration_traces",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_orchestration_traces_session_created",
        table_name="orchestration_traces",
    )
    op.drop_table("orchestration_traces")
