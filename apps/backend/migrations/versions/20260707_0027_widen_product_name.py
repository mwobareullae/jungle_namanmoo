"""widen product name

Revision ID: 20260707_0027
Revises: 20260706_0026
Create Date: 2026-07-07
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260707_0027"
down_revision: str | None = "20260706_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "products",
        "product_name",
        existing_type=sa.String(length=200),
        type_=sa.String(length=512),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "products",
        "product_name",
        existing_type=sa.String(length=512),
        type_=sa.String(length=200),
        existing_nullable=False,
    )
