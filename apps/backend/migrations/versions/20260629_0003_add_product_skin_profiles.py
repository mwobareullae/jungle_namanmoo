"""add product skin profiles

Revision ID: 20260629_0003
Revises: 20260629_0002
Create Date: 2026-06-29 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260629_0003"
down_revision: str | None = "20260629_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_skin_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("dry_fit", sa.Numeric(5, 4), nullable=False),
        sa.Column("oily_fit", sa.Numeric(5, 4), nullable=False),
        sa.Column("combination_fit", sa.Numeric(5, 4), nullable=False),
        sa.Column("normal_fit", sa.Numeric(5, 4), nullable=False),
        sa.Column("dehydrated_oily_fit", sa.Numeric(5, 4), nullable=False),
        sa.Column("sensitive_fit", sa.Numeric(5, 4), nullable=False),
        sa.Column("sensitivity_tag", sa.String(length=40), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_product_skin_profiles_product"),
    )


def downgrade() -> None:
    op.drop_table("product_skin_profiles")
