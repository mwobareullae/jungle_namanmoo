"""add ingredient aliases

Revision ID: 20260630_0008
Revises: 20260630_0007
Create Date: 2026-06-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260630_0008"
down_revision: str | None = "20260630_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingredient_aliases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("alias", sa.String(length=160), nullable=False),
        sa.Column("normalized_alias", sa.String(length=160), nullable=False),
        sa.Column("alias_type", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_alias", name="uq_ingredient_aliases_normalized_alias"),
    )
    op.create_index("ix_ingredient_aliases_ingredient_id", "ingredient_aliases", ["ingredient_id"])


def downgrade() -> None:
    op.drop_index("ix_ingredient_aliases_ingredient_id", table_name="ingredient_aliases")
    op.drop_table("ingredient_aliases")
