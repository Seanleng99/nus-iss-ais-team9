"""Keep explicit recurring expense terms and stable obligation identities."""

import sqlalchemy as sa
from alembic import op

revision = "20261004_0017"
down_revision = "20261004_0016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("transactions", sa.Column("recurrence", sa.JSON(none_as_null=True), nullable=True))
    op.add_column("transactions", sa.Column("obligation_id", sa.String(64), nullable=True))
    op.create_index("ix_transactions_user_obligation", "transactions", ["user_id", "obligation_id"])
    # Legacy flags intentionally remain unknown; no frequency or identity is guessed.


def downgrade():
    op.drop_index("ix_transactions_user_obligation", table_name="transactions")
    op.drop_column("transactions", "obligation_id")
    op.drop_column("transactions", "recurrence")
