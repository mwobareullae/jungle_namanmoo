"""Add an optional product release timestamp for newest catalog ordering.

Revision ID: 20260712_0036
Revises: 20260712_0035
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260712_0036"
down_revision: str | None = "20260712_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("released_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_products_released_at", "products", ["released_at"])


def downgrade() -> None:
    op.drop_index("ix_products_released_at", table_name="products")
    op.drop_column("products", "released_at")
