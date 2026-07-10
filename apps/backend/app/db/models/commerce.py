from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import big_integer_pk_type, jsonb_type


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
    "'READY', 'CONFIRMING', 'UNKNOWN', 'APPROVED', 'FAILED', 'CANCELED', 'EXPIRED', "
    "'REFUND_REQUESTED', 'REFUNDED', 'PARTIALLY_REFUNDED'"
)


class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    seller_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    seller_type: Mapped[str] = mapped_column(String(40), nullable=False, default="FIRST_PARTY", server_default="FIRST_PARTY")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SellerShippingPolicy(Base):
    __tablename__ = "seller_shipping_policies"
    __table_args__ = (
        CheckConstraint("base_shipping_fee >= 0", name="ck_seller_shipping_policies_base_fee_non_negative"),
        CheckConstraint(
            "free_shipping_threshold is null or free_shipping_threshold >= 0",
            name="ck_seller_shipping_policies_free_threshold_non_negative",
        ),
        UniqueConstraint("seller_id", "policy_name", name="uq_seller_shipping_policies_seller_policy_name"),
        Index("ix_seller_shipping_policies_seller_active", "seller_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), nullable=False, index=True)
    policy_name: Mapped[str] = mapped_column(String(80), nullable=False, default="default", server_default="default")
    base_shipping_fee: Mapped[int] = mapped_column(Integer, nullable=False, default=3000, server_default="3000")
    free_shipping_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Inventory(Base):
    __tablename__ = "inventories"
    __table_args__ = (
        CheckConstraint("stock_quantity >= 0", name="ck_inventories_stock_quantity_non_negative"),
        CheckConstraint("reserved_quantity >= 0", name="ck_inventories_reserved_quantity_non_negative"),
        CheckConstraint("safety_stock >= 0", name="ck_inventories_safety_stock_non_negative"),
        CheckConstraint("sales_status in ('ON_SALE', 'SOLD_OUT', 'HIDDEN')", name="ck_inventories_sales_status"),
        UniqueConstraint("product_id", name="uq_inventories_product_id"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reserved_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sales_status: Mapped[str] = mapped_column(String(20), nullable=False, default="ON_SALE", server_default="ON_SALE")
    inventory_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    inventory_id: Mapped[int] = mapped_column(ForeignKey("inventories.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    movement_type: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Cart(Base):
    __tablename__ = "carts"
    __table_args__ = (
        CheckConstraint("status in ('ACTIVE', 'MERGED', 'ORDERED', 'EXPIRED')", name="ck_carts_status"),
        CheckConstraint(
            "user_id is not null or anonymous_cart_id is not null",
            name="ck_carts_has_owner",
        ),
        Index("ix_carts_user_status_updated_at", "user_id", "status", "updated_at"),
        Index("ix_carts_anonymous_status_updated_at", "anonymous_cart_id", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    anonymous_cart_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_into_cart_id: Mapped[int | None] = mapped_column(ForeignKey("carts.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        CheckConstraint("quantity >= 1 and quantity <= 99", name="ck_cart_items_quantity_range"),
        CheckConstraint("unit_price_snapshot >= 0", name="ck_cart_items_unit_price_snapshot_non_negative"),
        CheckConstraint(
            "recommendation_rank is null or recommendation_rank > 0",
            name="ck_cart_items_recommendation_rank_positive",
        ),
        UniqueConstraint("cart_id", "product_id", name="uq_cart_items_cart_product"),
        Index("ix_cart_items_cart_created_at", "cart_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="KRW", server_default="KRW")
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    recommendation_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Wishlist(Base):
    __tablename__ = "wishlists"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_wishlists_user_product"),
        Index("ix_wishlists_user_added_at", "user_id", "added_at"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RecentView(Base):
    __tablename__ = "recent_views"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_recent_views_user_product"),
        Index("ix_recent_views_user_viewed_at", "user_id", "viewed_at"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductPopularityMetric(Base):
    __tablename__ = "product_popularity_metrics"
    __table_args__ = (
        CheckConstraint("window_days >= 0", name="ck_product_popularity_metrics_window_days_non_negative"),
        CheckConstraint("view_count >= 0", name="ck_product_popularity_metrics_view_count_non_negative"),
        CheckConstraint("click_count >= 0", name="ck_product_popularity_metrics_click_count_non_negative"),
        CheckConstraint("cart_add_count >= 0", name="ck_product_popularity_metrics_cart_add_count_non_negative"),
        CheckConstraint("order_count >= 0", name="ck_product_popularity_metrics_order_count_non_negative"),
        CheckConstraint("units_sold >= 0", name="ck_product_popularity_metrics_units_sold_non_negative"),
        CheckConstraint("review_count >= 0", name="ck_product_popularity_metrics_review_count_non_negative"),
        CheckConstraint(
            "average_rating is null or (average_rating >= 0 and average_rating <= 5)",
            name="ck_product_popularity_metrics_average_rating_range",
        ),
        CheckConstraint("popularity_score >= 0", name="ck_product_popularity_metrics_popularity_score_non_negative"),
        UniqueConstraint("product_id", "window_days", name="uq_product_popularity_metrics_product_window"),
        Index(
            "ix_product_popularity_metrics_window_score",
            "window_days",
            "popularity_score",
            "computed_at",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7, server_default="7")
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cart_add_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    units_sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    wishlist_add_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    checkout_start_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    paid_order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    home_product_impression_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    home_product_click_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    search_result_impression_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    search_result_click_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    wishlist_remove_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cart_remove_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cart_quantity_change_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    payment_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    order_cancel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    average_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    popularity_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0, server_default="0")
    score_version: Mapped[str] = mapped_column(String(40), nullable=False, default="popular_v1", server_default="popular_v1")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserAddress(Base):
    __tablename__ = "user_addresses"
    __table_args__ = (
        CheckConstraint("length(trim(recipient_name)) > 0", name="ck_user_addresses_recipient_not_blank"),
        CheckConstraint("length(trim(phone)) > 0", name="ck_user_addresses_phone_not_blank"),
        CheckConstraint("length(trim(postal_code)) > 0", name="ck_user_addresses_postal_code_not_blank"),
        CheckConstraint("length(trim(address1)) > 0", name="ck_user_addresses_address1_not_blank"),
        Index("ix_user_addresses_user_default", "user_id", "is_default"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    recipient_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    address1: Mapped[str] = mapped_column(String(255), nullable=False)
    address2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_memo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_orders_user_idempotency_key"),
        CheckConstraint(f"status in ({ORDER_STATUS_VALUES})", name="ck_orders_status"),
        CheckConstraint("subtotal_amount >= 0", name="ck_orders_subtotal_non_negative"),
        CheckConstraint("shipping_fee >= 0", name="ck_orders_shipping_fee_non_negative"),
        CheckConstraint("discount_amount >= 0", name="ck_orders_discount_amount_non_negative"),
        CheckConstraint("total_amount >= 0", name="ck_orders_total_amount_non_negative"),
        CheckConstraint("item_count > 0", name="ck_orders_item_count_positive"),
        CheckConstraint("total_quantity > 0", name="ck_orders_total_quantity_positive"),
        Index("ix_orders_user_status_created_at", "user_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    order_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    cart_id: Mapped[int | None] = mapped_column(ForeignKey("carts.id"), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="PENDING_PAYMENT",
        server_default="PENDING_PAYMENT",
    )
    subtotal_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    shipping_fee: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    discount_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="KRW", server_default="KRW")
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint(f"status in ({ORDER_ITEM_STATUS_VALUES})", name="ck_order_items_status"),
        CheckConstraint("quantity >= 1 and quantity <= 99", name="ck_order_items_quantity_range"),
        CheckConstraint("unit_price >= 0", name="ck_order_items_unit_price_non_negative"),
        CheckConstraint("line_subtotal >= 0", name="ck_order_items_line_subtotal_non_negative"),
        CheckConstraint("line_discount_amount >= 0", name="ck_order_items_line_discount_non_negative"),
        CheckConstraint("line_total >= 0", name="ck_order_items_line_total_non_negative"),
        CheckConstraint(
            "recommendation_rank is null or recommendation_rank > 0",
            name="ck_order_items_recommendation_rank_positive",
        ),
        Index("ix_order_items_order_status", "order_id", "status"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    cart_item_id: Mapped[int | None] = mapped_column(ForeignKey("cart_items.id"), nullable=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), nullable=False, index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    seller_name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    thumbnail_storage_key_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_subtotal: Mapped[int] = mapped_column(Integer, nullable=False)
    line_discount_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    line_total: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="KRW", server_default="KRW")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="ORDERED", server_default="ORDERED")
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    recommendation_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OrderShippingAddress(Base):
    __tablename__ = "order_shipping_addresses"
    __table_args__ = (
        CheckConstraint("length(trim(recipient_name)) > 0", name="ck_order_shipping_addresses_recipient_not_blank"),
        CheckConstraint("length(trim(phone)) > 0", name="ck_order_shipping_addresses_phone_not_blank"),
        CheckConstraint("length(trim(postal_code)) > 0", name="ck_order_shipping_addresses_postal_code_not_blank"),
        CheckConstraint("length(trim(address1)) > 0", name="ck_order_shipping_addresses_address1_not_blank"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True, nullable=False, index=True)
    user_address_id: Mapped[int | None] = mapped_column(ForeignKey("user_addresses.id"), nullable=True, index=True)
    recipient_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    address1: Mapped[str] = mapped_column(String(255), nullable=False)
    address2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_memo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OrderShippingGroup(Base):
    __tablename__ = "order_shipping_groups"
    __table_args__ = (
        UniqueConstraint("order_id", "seller_id", name="uq_order_shipping_groups_order_seller"),
        CheckConstraint("item_subtotal >= 0", name="ck_order_shipping_groups_item_subtotal_non_negative"),
        CheckConstraint("shipping_fee >= 0", name="ck_order_shipping_groups_shipping_fee_non_negative"),
        CheckConstraint(
            "free_shipping_threshold_snapshot is null or free_shipping_threshold_snapshot >= 0",
            name="ck_order_shipping_groups_free_threshold_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), nullable=False, index=True)
    seller_name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    item_subtotal: Mapped[int] = mapped_column(Integer, nullable=False)
    shipping_fee: Mapped[int] = mapped_column(Integer, nullable=False)
    free_shipping_threshold_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shipping_policy_snapshot_json: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(f"provider in ({PAYMENT_PROVIDER_VALUES})", name="ck_payments_provider"),
        CheckConstraint(f"status in ({PAYMENT_STATUS_VALUES})", name="ck_payments_status"),
        CheckConstraint("amount >= 0", name="ck_payments_amount_non_negative"),
        UniqueConstraint("provider", "provider_payment_key", name="uq_payments_provider_payment_key"),
        Index("ix_payments_provider_order_id", "provider", "provider_order_id"),
        Index("ix_payments_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    payment_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="MOCK", server_default="MOCK")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="READY", server_default="READY")
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="KRW", server_default="KRW")
    provider_payment_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_payment_events_provider_event_id"),
        CheckConstraint("amount is null or amount >= 0", name="ck_payment_events_amount_non_negative"),
        Index("ix_payment_events_payment_created_at", "payment_id", "created_at"),
        Index("ix_payment_events_order_created_at", "order_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), nullable=False, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_payment_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="KRW", server_default="KRW")
    status_before: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status_after: Mapped[str | None] = mapped_column(String(40), nullable=True)
    raw_payload_json: Mapped[dict] = mapped_column(jsonb_type(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        CheckConstraint("operation in ('CONFIRM', 'CANCEL')", name="ck_payment_attempts_operation"),
        CheckConstraint("status <> ''", name="ck_payment_attempts_status_not_blank"),
        CheckConstraint("provider in ('MOCK', 'TOSS')", name="ck_payment_attempts_provider"),
        UniqueConstraint("payment_id", "attempt_code", name="uq_payment_attempts_payment_attempt_code"),
        UniqueConstraint(
            "provider",
            "provider_idempotency_key",
            name="uq_payment_attempts_provider_idempotency_key",
        ),
        Index("ix_payment_attempts_payment_requested_at", "payment_id", "requested_at"),
        Index("ix_payment_attempts_status_requested_at", "status", "requested_at"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), nullable=False, index=True)
    attempt_code: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_payment_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_summary_json: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    response_summary_json: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
