"""Add coaching context and isolated fairness profile data.

Revision ID: 20260813_0003
Revises: 20260805_0002
Create Date: 2026-08-13
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0003"
down_revision: str | None = "20260805_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("financial_profiles", sa.Column("employment_status", sa.String(32)))
    op.add_column("financial_profiles", sa.Column("occupation_category", sa.String(64)))
    op.add_column("financial_profiles", sa.Column("income_frequency", sa.String(32)))
    op.add_column("financial_profiles", sa.Column("income_stability", sa.String(32)))
    op.add_column("financial_profiles", sa.Column("household_size", sa.Integer()))
    op.add_column("financial_profiles", sa.Column("dependants", sa.Integer()))
    op.add_column("financial_profiles", sa.Column("housing_status", sa.String(32)))
    op.add_column("financial_profiles", sa.Column("financial_literacy", sa.String(32)))
    op.add_column("financial_profiles", sa.Column("preferred_language", sa.String(32)))
    op.add_column(
        "financial_profiles",
        sa.Column(
            "accessibility_preferences",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )

    op.create_table(
        "profile_demographics",
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("age_band", sa.String(32)),
        sa.Column("gender_identity", sa.String(64)),
        sa.Column("race_ethnicity", sa.JSON(), nullable=False),
        sa.Column("nationality_residency", sa.String(64)),
        sa.Column("disability_status", sa.String(64)),
        sa.Column("marital_status", sa.String(32)),
        sa.Column("residential_region", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_profile_demographics_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_profile_demographics")),
    )
    op.create_table(
        "profile_consents",
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("consent_version", sa.String(32), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_profile_consents_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "purpose", name=op.f("pk_profile_consents")),
    )


def downgrade() -> None:
    op.drop_table("profile_consents")
    op.drop_table("profile_demographics")
    op.drop_column("financial_profiles", "accessibility_preferences")
    op.drop_column("financial_profiles", "preferred_language")
    op.drop_column("financial_profiles", "financial_literacy")
    op.drop_column("financial_profiles", "housing_status")
    op.drop_column("financial_profiles", "dependants")
    op.drop_column("financial_profiles", "household_size")
    op.drop_column("financial_profiles", "income_stability")
    op.drop_column("financial_profiles", "income_frequency")
    op.drop_column("financial_profiles", "occupation_category")
    op.drop_column("financial_profiles", "employment_status")
