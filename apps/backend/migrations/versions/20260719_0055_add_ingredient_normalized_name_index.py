"""add ingredient normalized name index

Revision ID: 20260719_0055
Revises: 20260719_0054
Create Date: 2026-07-19

The administrator ingredient-mapping queue resolves exact canonical candidates
by ``ingredients.normalized_name``.  The index changes lookup performance only;
it does not modify ingredient, mapping-review, or product data.
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260719_0055"
down_revision: str | None = "20260719_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_ingredients_normalized_name", "ingredients", ["normalized_name"])


def downgrade() -> None:
    op.drop_index("ix_ingredients_normalized_name", table_name="ingredients")
