"""add cart checkout tables

Revision ID: 20260705_0021
Revises: 20260705_0020
Create Date: 2026-07-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260705_0021"
down_revision: str | None = "20260705_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "carts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("anonymous_cart_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="ACTIVE", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_into_cart_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('ACTIVE', 'MERGED', 'ORDERED', 'EXPIRED')", name="ck_carts_status"),
        sa.CheckConstraint(
            "user_id is not null or anonymous_cart_id is not null",
            name="ck_carts_has_owner",
        ),
        sa.ForeignKeyConstraint(["merged_into_cart_id"], ["carts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_carts_anonymous_cart_id", "carts", ["anonymous_cart_id"])
    op.create_index(
        "ix_carts_anonymous_status_updated_at",
        "carts",
        ["anonymous_cart_id", "status", "updated_at"],
    )
    op.create_index("ix_carts_merged_into_cart_id", "carts", ["merged_into_cart_id"])
    op.create_index("ix_carts_user_id", "carts", ["user_id"])
    op.create_index(
        "ix_carts_user_status_updated_at",
        "carts",
        ["user_id", "status", "updated_at"],
    )

    op.create_table(
        "cart_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("cart_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("seller_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_snapshot", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="KRW", nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("recommendation_id", sa.String(length=128), nullable=True),
        sa.Column("recommendation_rank", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity >= 1 and quantity <= 99", name="ck_cart_items_quantity_range"),
        sa.CheckConstraint(
            "unit_price_snapshot >= 0",
            name="ck_cart_items_unit_price_snapshot_non_negative",
        ),
        sa.CheckConstraint(
            "recommendation_rank is null or recommendation_rank > 0",
            name="ck_cart_items_recommendation_rank_positive",
        ),
        sa.ForeignKeyConstraint(["cart_id"], ["carts.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cart_id", "product_id", name="uq_cart_items_cart_product"),
    )
    op.create_index("ix_cart_items_cart_created_at", "cart_items", ["cart_id", "created_at"])
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"])
    op.create_index("ix_cart_items_product_id", "cart_items", ["product_id"])
    op.create_index("ix_cart_items_recommendation_id", "cart_items", ["recommendation_id"])
    op.create_index("ix_cart_items_seller_id", "cart_items", ["seller_id"])


def downgrade() -> None:
    op.drop_index("ix_cart_items_seller_id", table_name="cart_items")
    op.drop_index("ix_cart_items_recommendation_id", table_name="cart_items")
    op.drop_index("ix_cart_items_product_id", table_name="cart_items")
    op.drop_index("ix_cart_items_cart_id", table_name="cart_items")
    op.drop_index("ix_cart_items_cart_created_at", table_name="cart_items")
    op.drop_table("cart_items")

    op.drop_index("ix_carts_user_status_updated_at", table_name="carts")
    op.drop_index("ix_carts_user_id", table_name="carts")
    op.drop_index("ix_carts_merged_into_cart_id", table_name="carts")
    op.drop_index("ix_carts_anonymous_status_updated_at", table_name="carts")
    op.drop_index("ix_carts_anonymous_cart_id", table_name="carts")
    op.drop_table("carts")
