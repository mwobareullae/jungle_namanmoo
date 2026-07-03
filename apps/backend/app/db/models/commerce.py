from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
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
