"""relax ingredient_effect_ranges concentration columns to nullable

Revision ID: 20260630_0007
Revises: 20260629_0006
Create Date: 2026-06-30 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260630_0007"
down_revision: str | None = "20260629_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLS = ("meaningful_min", "optimal_min", "optimal_max")


def upgrade() -> None:
    for c in _COLS:
        op.alter_column("ingredient_effect_ranges", c,
                        existing_type=sa.Numeric(14, 8), nullable=True)


def downgrade() -> None:
    for c in _COLS:
        op.alter_column("ingredient_effect_ranges", c,
                        existing_type=sa.Numeric(14, 8), nullable=False)
