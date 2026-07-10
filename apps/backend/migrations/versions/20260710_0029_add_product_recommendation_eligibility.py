"""add product recommendation eligibility

Revision ID: 20260710_0029
Revises: 20260709_0028
Create Date: 2026-07-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260710_0029"
down_revision: str | None = "20260709_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("is_recommendable", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "products",
        sa.Column("recommend_exclude_reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_products_is_recommendable", "products", ["is_recommendable"])


def downgrade() -> None:
    op.drop_index("ix_products_is_recommendable", table_name="products")
    op.drop_column("products", "recommend_exclude_reason")
    op.drop_column("products", "is_recommendable")
