"""add ingredient effect ranges

Revision ID: 20260629_0006
Revises: 20260629_0005
Create Date: 2026-06-29 23:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260629_0006"
down_revision: str | None = "20260629_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingredient_effect_ranges",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("effect_id", sa.BigInteger(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("meaningful_min", sa.Numeric(14, 8), nullable=False),
        sa.Column("optimal_min", sa.Numeric(14, 8), nullable=False),
        sa.Column("optimal_max", sa.Numeric(14, 8), nullable=False),
        sa.Column("excessive_min", sa.Numeric(14, 8), nullable=True),
        sa.Column("range_confidence", sa.String(length=20), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["effect_id"], ["effects.id"]),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ingredient_id",
            "effect_id",
            "unit",
            name="uq_ingredient_effect_ranges_ingredient_effect_unit",
        ),
    )
    op.create_index("ix_ingredient_effect_ranges_effect_id", "ingredient_effect_ranges", ["effect_id"])
    op.create_index("ix_ingredient_effect_ranges_ingredient_id", "ingredient_effect_ranges", ["ingredient_id"])


def downgrade() -> None:
    op.drop_index("ix_ingredient_effect_ranges_ingredient_id", table_name="ingredient_effect_ranges")
    op.drop_index("ix_ingredient_effect_ranges_effect_id", table_name="ingredient_effect_ranges")
    op.drop_table("ingredient_effect_ranges")
