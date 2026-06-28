from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import big_integer_pk_type


class Concern(Base):
    __tablename__ = "concerns"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    concern_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class ConcernAlias(Base):
    __tablename__ = "concern_aliases"
    __table_args__ = (
        UniqueConstraint("concern_id", "normalized_alias", name="uq_concern_aliases_concern_normalized_alias"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    concern_id: Mapped[int] = mapped_column(ForeignKey("concerns.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(80), nullable=False)


class Effect(Base):
    __tablename__ = "effects"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    effect_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class EffectAlias(Base):
    __tablename__ = "effect_aliases"
    __table_args__ = (
        UniqueConstraint("effect_id", "normalized_alias", name="uq_effect_aliases_effect_normalized_alias"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    effect_id: Mapped[int] = mapped_column(ForeignKey("effects.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(80), nullable=False)


class ConcernEffect(Base):
    __tablename__ = "concern_effects"
    __table_args__ = (
        UniqueConstraint("concern_id", "effect_id", name="uq_concern_effects_concern_effect"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    concern_id: Mapped[int] = mapped_column(ForeignKey("concerns.id"), nullable=False, index=True)
    effect_id: Mapped[int] = mapped_column(ForeignKey("effects.id"), nullable=False, index=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=1, server_default="1.0")


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    ingredient_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_ko: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(160), nullable=True)
    normalized_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IngredientEffect(Base):
    __tablename__ = "ingredient_effects"
    __table_args__ = (
        UniqueConstraint("ingredient_id", "effect_id", name="uq_ingredient_effects_ingredient_effect"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    effect_id: Mapped[int] = mapped_column(ForeignKey("effects.id"), nullable=False, index=True)
    effect_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0, server_default="0.0")


class IngredientEffectRange(Base):
    __tablename__ = "ingredient_effect_ranges"
    __table_args__ = (
        UniqueConstraint(
            "ingredient_id",
            "effect_id",
            "unit",
            name="uq_ingredient_effect_ranges_ingredient_effect_unit",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    effect_id: Mapped[int] = mapped_column(ForeignKey("effects.id"), nullable=False, index=True)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    meaningful_min: Mapped[Decimal] = mapped_column(Numeric(14, 8), nullable=False)
    optimal_min: Mapped[Decimal] = mapped_column(Numeric(14, 8), nullable=False)
    optimal_max: Mapped[Decimal] = mapped_column(Numeric(14, 8), nullable=False)
    excessive_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 8), nullable=True)
    range_confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class IngredientEvidence(Base):
    __tablename__ = "ingredient_evidence"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    effect_id: Mapped[int | None] = mapped_column(ForeignKey("effects.id"), nullable=True, index=True)
    evidence_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    evidence_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0, server_default="0.0")
    source_title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)


class RiskFlag(Base):
    __tablename__ = "risk_flags"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    risk_type: Mapped[str] = mapped_column(String(80), nullable=False)
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
