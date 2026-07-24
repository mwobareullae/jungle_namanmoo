"""widen product ingredient concentration values

Revision ID: 20260629_0005
Revises: 20260629_0004
Create Date: 2026-06-29 22:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260629_0005"
down_revision: str | None = "20260629_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "product_ingredients",
        "concentration_text",
        existing_type=sa.String(length=80),
        type_=sa.String(length=160),
        existing_nullable=True,
    )
    op.alter_column(
        "product_ingredients",
        "concentration_value",
        existing_type=sa.Numeric(8, 4),
        type_=sa.Numeric(14, 6),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Narrowing these columns could fail or truncate already-seeded ppm values.
    # Keep downgrade as no-op for compatibility with real local/dev data.
    pass
