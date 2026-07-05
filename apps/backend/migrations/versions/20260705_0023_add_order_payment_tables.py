"""add order payment tables

Revision ID: 20260705_0023
Revises: 20260705_0022
Create Date: 2026-07-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260705_0023"
down_revision: str | None = "20260705_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSONB = postgresql.JSONB(astext_type=sa.Text())

ORDER_STATUS_VALUES = (
    "'PENDING_PAYMENT', 'PAID', 'PAYMENT_FAILED', 'EXPIRED', 'CANCELED', "
    "'PREPARING_SHIPMENT', 'SHIPPED', 'DELIVERED', 'CANCEL_REQUESTED', "
    "'REFUND_REQUESTED', 'REFUNDED', 'RETURN_REQUESTED', 'RETURNED', "
    "'EXCHANGE_REQUESTED', 'EXCHANGED'"
)
ORDER_ITEM_STATUS_VALUES = (
    "'ORDERED', 'CANCELED', 'PREPARING_SHIPMENT', 'SHIPPED', 'DELIVERED', "
    "'RETURN_REQUESTED', 'RETURNED', 'EXCHANGE_REQUESTED', 'EXCHANGED', "
    "'REFUND_REQUESTED', 'REFUNDED'"
)
PAYMENT_PROVIDER_VALUES = "'MOCK', 'TOSS', 'KAKAO_PAY', 'NAVER_PAY'"
PAYMENT_STATUS_VALUES = (
    "'READY', 'APPROVED', 'FAILED', 'CANCELED', 'EXPIRED', "
    "'REFUND_REQUESTED', 'REFUNDED', 'PARTIALLY_REFUNDED'"
)


def upgrade() -> None:
    op.create_table(
        "user_addresses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("recipient_name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.Column("address1", sa.String(length=255), nullable=False),
        sa.Column("address2", sa.String(length=255), nullable=True),
        sa.Column("delivery_memo", sa.String(length=255), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "length(trim(recipient_name)) > 0",
            name="ck_user_addresses_recipient_not_blank",
        ),
        sa.CheckConstraint("length(trim(phone)) > 0", name="ck_user_addresses_phone_not_blank"),
        sa.CheckConstraint(
            "length(trim(postal_code)) > 0",
            name="ck_user_addresses_postal_code_not_blank",
        ),
        sa.CheckConstraint("length(trim(address1)) > 0", name="ck_user_addresses_address1_not_blank"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_addresses_user_id", "user_addresses", ["user_id"])
    op.create_index("ix_user_addresses_user_default", "user_addresses", ["user_id", "is_default"])

    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_code", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("cart_id", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="PENDING_PAYMENT", nullable=False),
        sa.Column("subtotal_amount", sa.Integer(), nullable=False),
        sa.Column("shipping_fee", sa.Integer(), server_default="0", nullable=False),
        sa.Column("discount_amount", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="KRW", nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("total_quantity", sa.Integer(), nullable=False),
        sa.Column("payment_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ordered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"status in ({ORDER_STATUS_VALUES})", name="ck_orders_status"),
        sa.CheckConstraint("subtotal_amount >= 0", name="ck_orders_subtotal_non_negative"),
        sa.CheckConstraint("shipping_fee >= 0", name="ck_orders_shipping_fee_non_negative"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_orders_discount_amount_non_negative"),
        sa.CheckConstraint("total_amount >= 0", name="ck_orders_total_amount_non_negative"),
        sa.CheckConstraint("item_count > 0", name="ck_orders_item_count_positive"),
        sa.CheckConstraint("total_quantity > 0", name="ck_orders_total_quantity_positive"),
        sa.ForeignKeyConstraint(["cart_id"], ["carts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_code"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_orders_user_idempotency_key"),
    )
    op.create_index("ix_orders_cart_id", "orders", ["cart_id"])
    op.create_index("ix_orders_payment_expires_at", "orders", ["payment_expires_at"])
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_user_status_created_at", "orders", ["user_id", "status", "created_at"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("cart_item_id", sa.BigInteger(), nullable=True),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("seller_id", sa.BigInteger(), nullable=False),
        sa.Column("product_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("brand_name_snapshot", sa.String(length=120), nullable=False),
        sa.Column("seller_name_snapshot", sa.String(length=120), nullable=False),
        sa.Column("thumbnail_storage_key_snapshot", sa.Text(), nullable=True),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_subtotal", sa.Integer(), nullable=False),
        sa.Column("line_discount_amount", sa.Integer(), server_default="0", nullable=False),
        sa.Column("line_total", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="KRW", nullable=False),
        sa.Column("status", sa.String(length=40), server_default="ORDERED", nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("recommendation_id", sa.String(length=128), nullable=True),
        sa.Column("recommendation_rank", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"status in ({ORDER_ITEM_STATUS_VALUES})", name="ck_order_items_status"),
        sa.CheckConstraint("quantity >= 1 and quantity <= 99", name="ck_order_items_quantity_range"),
        sa.CheckConstraint("unit_price >= 0", name="ck_order_items_unit_price_non_negative"),
        sa.CheckConstraint("line_subtotal >= 0", name="ck_order_items_line_subtotal_non_negative"),
        sa.CheckConstraint("line_discount_amount >= 0", name="ck_order_items_line_discount_non_negative"),
        sa.CheckConstraint("line_total >= 0", name="ck_order_items_line_total_non_negative"),
        sa.CheckConstraint(
            "recommendation_rank is null or recommendation_rank > 0",
            name="ck_order_items_recommendation_rank_positive",
        ),
        sa.ForeignKeyConstraint(["cart_item_id"], ["cart_items.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_items_cart_item_id", "order_items", ["cart_item_id"])
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_order_status", "order_items", ["order_id", "status"])
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])
    op.create_index("ix_order_items_recommendation_id", "order_items", ["recommendation_id"])
    op.create_index("ix_order_items_seller_id", "order_items", ["seller_id"])

    op.create_table(
        "order_shipping_addresses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("user_address_id", sa.BigInteger(), nullable=True),
        sa.Column("recipient_name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.Column("address1", sa.String(length=255), nullable=False),
        sa.Column("address2", sa.String(length=255), nullable=True),
        sa.Column("delivery_memo", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "length(trim(recipient_name)) > 0",
            name="ck_order_shipping_addresses_recipient_not_blank",
        ),
        sa.CheckConstraint("length(trim(phone)) > 0", name="ck_order_shipping_addresses_phone_not_blank"),
        sa.CheckConstraint(
            "length(trim(postal_code)) > 0",
            name="ck_order_shipping_addresses_postal_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(address1)) > 0",
            name="ck_order_shipping_addresses_address1_not_blank",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["user_address_id"], ["user_addresses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
    )
    op.create_index("ix_order_shipping_addresses_order_id", "order_shipping_addresses", ["order_id"])
    op.create_index("ix_order_shipping_addresses_user_address_id", "order_shipping_addresses", ["user_address_id"])

    op.create_table(
        "order_shipping_groups",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("seller_id", sa.BigInteger(), nullable=False),
        sa.Column("seller_name_snapshot", sa.String(length=120), nullable=False),
        sa.Column("item_subtotal", sa.Integer(), nullable=False),
        sa.Column("shipping_fee", sa.Integer(), nullable=False),
        sa.Column("free_shipping_threshold_snapshot", sa.Integer(), nullable=True),
        sa.Column("shipping_policy_snapshot_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "item_subtotal >= 0",
            name="ck_order_shipping_groups_item_subtotal_non_negative",
        ),
        sa.CheckConstraint("shipping_fee >= 0", name="ck_order_shipping_groups_shipping_fee_non_negative"),
        sa.CheckConstraint(
            "free_shipping_threshold_snapshot is null or free_shipping_threshold_snapshot >= 0",
            name="ck_order_shipping_groups_free_threshold_non_negative",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "seller_id", name="uq_order_shipping_groups_order_seller"),
    )
    op.create_index("ix_order_shipping_groups_order_id", "order_shipping_groups", ["order_id"])
    op.create_index("ix_order_shipping_groups_seller_id", "order_shipping_groups", ["seller_id"])

    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("payment_code", sa.String(length=40), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=40), server_default="MOCK", nullable=False),
        sa.Column("status", sa.String(length=40), server_default="READY", nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="KRW", nullable=False),
        sa.Column("provider_payment_key", sa.String(length=255), nullable=True),
        sa.Column("provider_order_id", sa.String(length=80), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"provider in ({PAYMENT_PROVIDER_VALUES})", name="ck_payments_provider"),
        sa.CheckConstraint(f"status in ({PAYMENT_STATUS_VALUES})", name="ck_payments_status"),
        sa.CheckConstraint("amount >= 0", name="ck_payments_amount_non_negative"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_code"),
        sa.UniqueConstraint("order_id"),
        sa.UniqueConstraint("provider", "provider_payment_key", name="uq_payments_provider_payment_key"),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_index("ix_payments_provider_order_id", "payments", ["provider", "provider_order_id"])
    op.create_index("ix_payments_status_created_at", "payments", ["status", "created_at"])

    op.create_table(
        "payment_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("payment_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_payment_key", sa.String(length=255), nullable=True),
        sa.Column("provider_order_id", sa.String(length=80), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=8), server_default="KRW", nullable=False),
        sa.Column("status_before", sa.String(length=40), nullable=True),
        sa.Column("status_after", sa.String(length=40), nullable=True),
        sa.Column("raw_payload_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount is null or amount >= 0", name="ck_payment_events_amount_non_negative"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "event_id", name="uq_payment_events_provider_event_id"),
    )
    op.create_index("ix_payment_events_order_created_at", "payment_events", ["order_id", "created_at"])
    op.create_index("ix_payment_events_order_id", "payment_events", ["order_id"])
    op.create_index("ix_payment_events_payment_created_at", "payment_events", ["payment_id", "created_at"])
    op.create_index("ix_payment_events_payment_id", "payment_events", ["payment_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_events_payment_id", table_name="payment_events")
    op.drop_index("ix_payment_events_payment_created_at", table_name="payment_events")
    op.drop_index("ix_payment_events_order_id", table_name="payment_events")
    op.drop_index("ix_payment_events_order_created_at", table_name="payment_events")
    op.drop_table("payment_events")

    op.drop_index("ix_payments_status_created_at", table_name="payments")
    op.drop_index("ix_payments_provider_order_id", table_name="payments")
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_order_shipping_groups_seller_id", table_name="order_shipping_groups")
    op.drop_index("ix_order_shipping_groups_order_id", table_name="order_shipping_groups")
    op.drop_table("order_shipping_groups")

    op.drop_index("ix_order_shipping_addresses_user_address_id", table_name="order_shipping_addresses")
    op.drop_index("ix_order_shipping_addresses_order_id", table_name="order_shipping_addresses")
    op.drop_table("order_shipping_addresses")

    op.drop_index("ix_order_items_seller_id", table_name="order_items")
    op.drop_index("ix_order_items_recommendation_id", table_name="order_items")
    op.drop_index("ix_order_items_product_id", table_name="order_items")
    op.drop_index("ix_order_items_order_status", table_name="order_items")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_index("ix_order_items_cart_item_id", table_name="order_items")
    op.drop_table("order_items")

    op.drop_index("ix_orders_user_status_created_at", table_name="orders")
    op.drop_index("ix_orders_user_id", table_name="orders")
    op.drop_index("ix_orders_payment_expires_at", table_name="orders")
    op.drop_index("ix_orders_cart_id", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_user_addresses_user_default", table_name="user_addresses")
    op.drop_index("ix_user_addresses_user_id", table_name="user_addresses")
    op.drop_table("user_addresses")
