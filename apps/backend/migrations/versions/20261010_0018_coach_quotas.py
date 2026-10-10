"""Share authenticated coaching limits across backend replicas."""

import sqlalchemy as sa
from alembic import op

revision = "20261010_0018"
down_revision = "20261004_0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("coach_quotas",
        sa.Column("owner_key", sa.String(64), primary_key=True),
        sa.Column("minute_window", sa.Integer(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("hour_window", sa.Integer(), nullable=False),
        sa.Column("charged_tokens", sa.Integer(), nullable=False))
    op.create_table("coach_quota_leases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_key", sa.String(64), sa.ForeignKey("coach_quotas.owner_key"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hour_window", sa.Integer(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False))
    op.create_index("ix_coach_quota_leases_owner_expiry", "coach_quota_leases", ["owner_key", "expires_at"])


def downgrade():
    op.drop_index("ix_coach_quota_leases_owner_expiry", table_name="coach_quota_leases")
    op.drop_table("coach_quota_leases")
    op.drop_table("coach_quotas")
