"""extend product popularity metrics

Revision ID: 20260706_0026
Revises: 20260705_0025
Create Date: 2026-07-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260706_0026"
down_revision: str | None = "20260705_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COUNT_COLUMNS = (
    "wishlist_add_count",
    "checkout_start_count",
    "paid_order_count",
    "home_product_impression_count",
    "home_product_click_count",
    "search_result_impression_count",
    "search_result_click_count",
    "wishlist_remove_count",
    "cart_remove_count",
    "cart_quantity_change_count",
    "payment_failed_count",
    "order_cancel_count",
)


def upgrade() -> None:
    for column_name in _COUNT_COLUMNS:
        op.add_column(
            "product_popularity_metrics",
            sa.Column(column_name, sa.Integer(), server_default="0", nullable=False),
        )


def downgrade() -> None:
    for column_name in reversed(_COUNT_COLUMNS):
        op.drop_column("product_popularity_metrics", column_name)
