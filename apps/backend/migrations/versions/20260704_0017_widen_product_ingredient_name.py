"""widen product ingredient display name

Revision ID: 20260704_0017
Revises: 20260704_0016
Create Date: 2026-07-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260704_0017"
down_revision: str | None = "20260704_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "product_ingredients",
        "ingredient_name",
        existing_type=sa.String(length=160),
        type_=sa.String(length=255),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "product_ingredients",
        "ingredient_name",
        existing_type=sa.String(length=255),
        type_=sa.String(length=160),
        existing_nullable=True,
    )
