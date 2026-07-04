from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import big_integer_pk_type


class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    seller_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    seller_type: Mapped[str] = mapped_column(String(40), nullable=False, default="FIRST_PARTY", server_default="FIRST_PARTY")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="ACTIVE", server_default="ACTIVE")
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
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    average_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    popularity_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0, server_default="0")
    score_version: Mapped[str] = mapped_column(String(40), nullable=False, default="popular_v1", server_default="popular_v1")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
