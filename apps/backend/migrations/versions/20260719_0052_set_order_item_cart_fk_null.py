"""set order item cart reference null when cart item is deleted

Revision ID: 20260719_0052
Revises: 20260718_0051
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260719_0052"
down_revision: str | None = "20260718_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "order_items_cart_item_id_fkey",
        "order_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_order_items_cart_item_id_cart_items",
        "order_items",
        "cart_items",
        ["cart_item_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_order_items_cart_item_id_cart_items",
        "order_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "order_items_cart_item_id_fkey",
        "order_items",
        "cart_items",
        ["cart_item_id"],
        ["id"],
    )
