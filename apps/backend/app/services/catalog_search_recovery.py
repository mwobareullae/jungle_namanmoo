from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, BrandAlias, Product, ProductCategory, ProductCategoryAlias
from app.db.models.taxonomy import Effect, EffectAlias, Ingredient, IngredientAlias
from app.services.catalog_search_aliases import brand_query_variants, known_query_correction
from app.services.catalog_search_query import CatalogSearchQuery
from app.services.catalog_search_text import (
    compact_search_text,
    english_keys_to_hangul,
    hangul_to_english_keys,
    is_all_chosung_query,
    normalize_query_text,
)


MAX_RECOVERY_VARIANTS = 5
_ASCII_KEY_QUERY = re.compile(r"^[a-zA-Z\s]+$")
_HANGUL_KEY_QUERY = re.compile(r"^[가-힣ㄱ-ㅎㅏ-ㅣ\s]+$")


@dataclass(frozen=True)
class CatalogSearchRecoveryPlan:
    variants: tuple[str, ...]
    corrected_query: str | None
    fuzzy_enabled: bool
    keyboard_conversion_used: bool
    choseong_used: bool

    @property
    def should_search(self) -> bool:
        return bool(self.variants) or self.fuzzy_enabled


def build_catalog_search_recovery_plan(
    session: Session,
    parsed_query: CatalogSearchQuery,
) -> CatalogSearchRecoveryPlan:
    if is_all_chosung_query(parsed_query.text_query):
        return CatalogSearchRecoveryPlan(
            variants=(),
            corrected_query=None,
            fuzzy_enabled=False,
            keyboard_conversion_used=False,
            choseong_used=True,
        )

    variants: list[str] = []
    corrected_query = known_query_correction(parsed_query.text_query)
    if corrected_query is not None:
        variants.append(corrected_query)

    variants.extend(brand_query_variants(parsed_query.text_query))

    compact_variant = compact_search_text(parsed_query.text_query)
    if (
        " " in parsed_query.text_query
        and compact_variant
        and compact_variant != parsed_query.text_query
        and _dictionary_contains(session, compact_variant)
    ):
        variants.append(compact_variant)
        corrected_query = corrected_query or compact_variant

    keyboard_conversion_used = False
    keyboard_variant = _keyboard_variant(parsed_query.text_query)
    if (
        keyboard_variant
        and keyboard_variant != parsed_query.text_query
        and _dictionary_contains(session, keyboard_variant)
    ):
        variants.append(keyboard_variant)
        corrected_query = corrected_query or keyboard_variant
        keyboard_conversion_used = True

    deduped_variants: list[str] = []
    seen = {parsed_query.text_query}
    for variant in variants:
        normalized = normalize_query_text(variant)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped_variants.append(normalized)
        if len(deduped_variants) >= MAX_RECOVERY_VARIANTS:
            break

    return CatalogSearchRecoveryPlan(
        variants=tuple(deduped_variants),
        corrected_query=normalize_query_text(corrected_query) if corrected_query else None,
        fuzzy_enabled=len(parsed_query.compact_query) >= 3,
        keyboard_conversion_used=keyboard_conversion_used,
        choseong_used=False,
    )


def _keyboard_variant(query: str) -> str | None:
    if _ASCII_KEY_QUERY.fullmatch(query):
        return normalize_query_text(english_keys_to_hangul(query))
    if _HANGUL_KEY_QUERY.fullmatch(query):
        return normalize_query_text(hangul_to_english_keys(query))
    return None


def _dictionary_contains(session: Session, value: str) -> bool:
    normalized = normalize_query_text(value)
    if not normalized:
        return False
    brand_match = session.execute(
        select(Brand.id)
        .outerjoin(BrandAlias, BrandAlias.brand_id == Brand.id)
        .where(
            Brand.is_active.is_(True),
            or_(
                func.lower(Brand.brand_code) == normalized,
                func.lower(Brand.name) == normalized,
                func.lower(Brand.normalized_name) == normalized,
                func.lower(BrandAlias.alias) == normalized,
                func.lower(BrandAlias.normalized_alias) == normalized,
            ),
        )
        .limit(1)
    ).scalar_one_or_none()
    if brand_match is not None:
        return True

    category_match = session.execute(
        select(ProductCategory.id)
        .outerjoin(ProductCategoryAlias, ProductCategoryAlias.category_id == ProductCategory.id)
        .where(
            ProductCategory.is_active.is_(True),
            or_(
                func.lower(ProductCategory.category_code) == normalized,
                func.lower(ProductCategory.name) == normalized,
                func.lower(ProductCategoryAlias.alias) == normalized,
                func.lower(ProductCategoryAlias.normalized_alias) == normalized,
            ),
        )
        .limit(1)
    ).scalar_one_or_none()
    if category_match is not None:
        return True

    ingredient_match = session.execute(
        select(Ingredient.id)
        .outerjoin(IngredientAlias, IngredientAlias.ingredient_id == Ingredient.id)
        .where(
            Ingredient.is_active.is_(True),
            or_(
                func.lower(Ingredient.name_ko) == normalized,
                func.lower(Ingredient.name_en) == normalized,
                func.lower(Ingredient.normalized_name) == normalized,
                func.lower(IngredientAlias.alias) == normalized,
                func.lower(IngredientAlias.normalized_alias) == normalized,
            ),
        )
        .limit(1)
    ).scalar_one_or_none()
    if ingredient_match is not None:
        return True

    effect_match = session.execute(
        select(Effect.id)
        .outerjoin(EffectAlias, EffectAlias.effect_id == Effect.id)
        .where(
            Effect.is_active.is_(True),
            or_(
                func.lower(Effect.effect_code) == normalized,
                func.lower(Effect.name) == normalized,
                func.lower(EffectAlias.alias) == normalized,
                func.lower(EffectAlias.normalized_alias) == normalized,
            ),
        )
        .limit(1)
    ).scalar_one_or_none()
    if effect_match is not None:
        return True

    product_match = session.execute(
        select(Product.id)
        .where(Product.is_active.is_(True), func.lower(Product.product_name) == normalized)
        .limit(1)
    ).scalar_one_or_none()
    return product_match is not None
