"""add sellers and inventory tables

Revision ID: 20260703_0011
Revises: 20260703_0010
Create Date: 2026-07-03
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260703_0011"
down_revision: str | None = "20260703_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sellers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("seller_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("seller_type", sa.String(length=40), server_default="FIRST_PARTY", nullable=False),
        sa.Column("status", sa.String(length=40), server_default="ACTIVE", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_code"),
    )
    op.execute(
        """
        INSERT INTO sellers (seller_code, display_name, seller_type, status)
        VALUES ('mwobareullae', '뭐바를래', 'FIRST_PARTY', 'ACTIVE')
        ON CONFLICT (seller_code) DO UPDATE
        SET display_name = EXCLUDED.display_name,
            seller_type = EXCLUDED.seller_type,
            status = EXCLUDED.status
        """
    )

    op.add_column("products", sa.Column("seller_id", sa.BigInteger(), nullable=True))
    op.execute(
        """
        UPDATE products
        SET seller_id = (SELECT id FROM sellers WHERE seller_code = 'mwobareullae')
        WHERE seller_id IS NULL
        """
    )
    op.alter_column("products", "seller_id", nullable=False)
    op.create_foreign_key("fk_products_seller_id_sellers", "products", "sellers", ["seller_id"], ["id"])
    op.create_index("ix_products_seller_id", "products", ["seller_id"])

    op.create_table(
        "inventories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("stock_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reserved_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("safety_stock", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sales_status", sa.String(length=20), server_default="ON_SALE", nullable=False),
        sa.Column("inventory_source", sa.String(length=40), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("stock_quantity >= 0", name="ck_inventories_stock_quantity_non_negative"),
        sa.CheckConstraint("reserved_quantity >= 0", name="ck_inventories_reserved_quantity_non_negative"),
        sa.CheckConstraint("safety_stock >= 0", name="ck_inventories_safety_stock_non_negative"),
        sa.CheckConstraint("sales_status in ('ON_SALE', 'SOLD_OUT', 'HIDDEN')", name="ck_inventories_sales_status"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_inventories_product_id"),
    )
    op.create_index("ix_inventories_product_id", "inventories", ["product_id"])

    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inventory_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("movement_type", sa.String(length=40), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("stock_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reference_type", sa.String(length=40), nullable=True),
        sa.Column("reference_id", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["inventory_id"], ["inventories.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_movements_inventory_id", "inventory_movements", ["inventory_id"])
    op.create_index("ix_inventory_movements_product_id", "inventory_movements", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_inventory_movements_product_id", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_inventory_id", table_name="inventory_movements")
    op.drop_table("inventory_movements")
    op.drop_index("ix_inventories_product_id", table_name="inventories")
    op.drop_table("inventories")
    op.drop_index("ix_products_seller_id", table_name="products")
    op.drop_constraint("fk_products_seller_id_sellers", "products", type_="foreignkey")
    op.drop_column("products", "seller_id")
    op.drop_table("sellers")
