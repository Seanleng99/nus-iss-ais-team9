"""Allow durable orchestration runs before an assistant message exists."""

import sqlalchemy as sa
from alembic import op

revision = "20260926_0009"
down_revision = "20260831_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "orchestration_traces", "assistant_message_id", existing_type=sa.Uuid(), nullable=True
    )
    op.add_column(
        "orchestration_traces",
        sa.Column("status", sa.String(24), nullable=False, server_default="completed"),
    )
    op.add_column("orchestration_traces", sa.Column("correlation_id", sa.String(128)))
    op.add_column("orchestration_traces", sa.Column("deadline_at", sa.DateTime(timezone=True)))
    op.add_column("orchestration_traces", sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.add_column("orchestration_traces", sa.Column("error_code", sa.String(128)))
    op.create_check_constraint(
        "run_status",
        "orchestration_traces",
        "status IN ('running', 'completed', 'blocked', 'failed', 'timed_out', 'abandoned')",
    )
    op.execute("UPDATE orchestration_traces SET status = 'blocked' WHERE blocked = true")
    op.create_index(
        "ix_orchestration_traces_correlation_id", "orchestration_traces", ["correlation_id"]
    )
    op.create_index("ix_orchestration_traces_deadline_at", "orchestration_traces", ["deadline_at"])


def downgrade():
    # Downgrade cannot represent incomplete runs. Refuse to silently discard their audit.
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT count(*) FROM orchestration_traces WHERE assistant_message_id IS NULL")
    ).scalar():
        raise RuntimeError("Export and explicitly remove incomplete runs before downgrade")
    op.drop_index("ix_orchestration_traces_deadline_at", table_name="orchestration_traces")
    op.drop_index("ix_orchestration_traces_correlation_id", table_name="orchestration_traces")
    op.drop_constraint(
        op.f("ck_orchestration_traces_run_status"), "orchestration_traces", type_="check"
    )
    for column in ("error_code", "finished_at", "deadline_at", "correlation_id", "status"):
        op.drop_column("orchestration_traces", column)
    op.alter_column(
        "orchestration_traces", "assistant_message_id", existing_type=sa.Uuid(), nullable=False
    )
