"""add auth consent tables

Revision ID: 20260704_0013
Revises: 20260703_0012
Create Date: 2026-07-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260704_0013"
down_revision: str | None = "20260703_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_users_display_name", "users", ["display_name"])
    op.add_column(
        "password_reset_tokens",
        sa.Column("failed_attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "password_reset_tokens",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "terms_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("terms_key", sa.String(length=40), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "terms_key in ('tos', 'privacy', 'age14', 'marketing')",
            name="ck_terms_versions_key",
        ),
        sa.CheckConstraint("length(trim(version)) > 0", name="ck_terms_versions_version_not_blank"),
        sa.CheckConstraint("length(trim(title)) > 0", name="ck_terms_versions_title_not_blank"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("terms_key", "version", name="uq_terms_versions_key_version"),
    )

    op.create_table(
        "user_consents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("terms_version_id", sa.BigInteger(), nullable=False),
        sa.Column("consent_key", sa.String(length=40), nullable=False),
        sa.Column("agreed", sa.Boolean(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "consent_key in ('tos', 'privacy', 'age14', 'marketing')",
            name="ck_user_consents_key",
        ),
        sa.ForeignKeyConstraint(["terms_version_id"], ["terms_versions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "terms_version_id", name="uq_user_consents_user_terms_version"),
    )
    op.create_index("ix_user_consents_terms_version_id", "user_consents", ["terms_version_id"])
    op.create_index("ix_user_consents_user_id", "user_consents", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_consents_user_id", table_name="user_consents")
    op.drop_index("ix_user_consents_terms_version_id", table_name="user_consents")
    op.drop_table("user_consents")
    op.drop_table("terms_versions")
    op.drop_column("password_reset_tokens", "last_attempt_at")
    op.drop_column("password_reset_tokens", "failed_attempt_count")
    op.drop_constraint("uq_users_display_name", "users", type_="unique")
