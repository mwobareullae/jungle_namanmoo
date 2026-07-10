from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import big_integer_pk_type


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    brand_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BrandAlias(Base):
    __tablename__ = "brand_aliases"
    __table_args__ = (
        UniqueConstraint("brand_id", "normalized_alias", name="uq_brand_aliases_brand_normalized_alias"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(120), nullable=False)


class ProductCategory(Base):
    __tablename__ = "product_categories"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    category_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductCategoryAlias(Base):
    __tablename__ = "product_category_aliases"
    __table_args__ = (
        UniqueConstraint("category_id", "normalized_alias", name="uq_product_category_aliases_category_normalized_alias"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("product_categories.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(80), nullable=False)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    product_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), nullable=False, index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("product_categories.id"), nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(512), nullable=False)
    skin_type_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    functional_review_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    functional_cosmetic_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    functional_cosmetic_claims: Mapped[str | None] = mapped_column(Text, nullable=True)
    functional_claim_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    functional_claim_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_recommendable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
    )
    recommend_exclude_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductImage(Base):
    __tablename__ = "product_images"
    __table_args__ = (
        CheckConstraint("image_type in ('thumbnail', 'detail')", name="ck_product_images_image_type"),
        UniqueConstraint("product_id", "image_type", "display_order", name="uq_product_images_product_type_order"),
        UniqueConstraint("product_id", "storage_key", name="uq_product_images_product_storage_key"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    image_type: Mapped[str] = mapped_column(String(20), nullable=False, default="detail", server_default="detail")
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class ProductPrice(Base):
    __tablename__ = "product_prices"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    mall_name: Mapped[str] = mapped_column(String(80), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="KRW", server_default="KRW")
    product_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_lowest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductSkinProfile(Base):
    __tablename__ = "product_skin_profiles"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), unique=True, nullable=False)
    dry_fit: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    oily_fit: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    combination_fit: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    normal_fit: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    dehydrated_oily_fit: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    sensitive_fit: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    sensitivity_tag: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProductIngredient(Base):
    __tablename__ = "product_ingredients"
    __table_args__ = (
        UniqueConstraint("product_id", "ingredient_id", name="uq_product_ingredients_product_ingredient"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    ingredient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_confidence: Mapped[str | None] = mapped_column(String(40), nullable=True)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    concentration_text: Mapped[str | None] = mapped_column(String(160), nullable=True)
    concentration_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    concentration_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    concentration_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    normalized_concentration_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 8), nullable=True)
    normalized_concentration_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
