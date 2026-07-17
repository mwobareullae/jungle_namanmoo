"""M3-B 표시명 기반 브랜드·카테고리 exact 해소.

이 서비스는 읽기 전용이다. 행별 bulk 검증이 계속 진행될 수 있도록 ApiError를
던지지 않고 상태 결과를 반환한다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, BrandAlias, ProductCategory, ProductCategoryAlias
from app.services.ingredient_resolution_service import normalize_for_resolution


FOUND = "FOUND"
NOT_FOUND = "NOT_FOUND"
AMBIGUOUS = "AMBIGUOUS"
INACTIVE = "INACTIVE"


@dataclass(frozen=True)
class BrandResolution:
    status: str
    brand_id: int | None = None


@dataclass(frozen=True)
class CategoryResolution:
    status: str
    category_id: int | None = None


def resolve_brands(session: Session, names: Iterable[str]) -> dict[str, BrandResolution]:
    """정규화된 표시명마다 brand ID 기준 단일 후보 여부를 반환한다."""
    normalized_names = {normalize_for_resolution(name) for name in names}
    normalized_names.discard("")
    if not normalized_names:
        return {}

    candidates: dict[str, dict[int, Brand]] = defaultdict(dict)
    direct_rows = session.execute(
        select(Brand).where(Brand.normalized_name.in_(normalized_names))
    ).scalars().all()
    for brand in direct_rows:
        candidates[brand.normalized_name][brand.id] = brand

    alias_rows = session.execute(
        select(Brand, BrandAlias.normalized_alias)
        .join(BrandAlias, BrandAlias.brand_id == Brand.id)
        .where(BrandAlias.normalized_alias.in_(normalized_names))
    ).all()
    for brand, normalized_alias in alias_rows:
        candidates[normalized_alias][brand.id] = brand

    return {
        name: _brand_resolution(candidates.get(name, {})) for name in normalized_names
    }


def resolve_brand(session: Session, name: str) -> BrandResolution:
    normalized_name = normalize_for_resolution(name)
    return resolve_brands(session, [name]).get(
        normalized_name, BrandResolution(status=NOT_FOUND)
    )


def resolve_categories(
    session: Session, names: Iterable[str]
) -> dict[str, CategoryResolution]:
    """카테고리는 normalized_name 컬럼이 없어 name을 같은 규칙으로 비교한다."""
    normalized_names = {normalize_for_resolution(name) for name in names}
    normalized_names.discard("")
    if not normalized_names:
        return {}

    candidates: dict[str, dict[int, ProductCategory]] = defaultdict(dict)
    for category in session.execute(select(ProductCategory)).scalars().all():
        normalized_name = normalize_for_resolution(category.name)
        if normalized_name in normalized_names:
            candidates[normalized_name][category.id] = category

    alias_rows = session.execute(
        select(ProductCategory, ProductCategoryAlias.normalized_alias)
        .join(ProductCategoryAlias, ProductCategoryAlias.category_id == ProductCategory.id)
        .where(ProductCategoryAlias.normalized_alias.in_(normalized_names))
    ).all()
    for category, normalized_alias in alias_rows:
        candidates[normalized_alias][category.id] = category

    return {
        name: _category_resolution(candidates.get(name, {})) for name in normalized_names
    }


def resolve_category(session: Session, name: str) -> CategoryResolution:
    normalized_name = normalize_for_resolution(name)
    return resolve_categories(session, [name]).get(
        normalized_name, CategoryResolution(status=NOT_FOUND)
    )


def _brand_resolution(candidates: dict[int, Brand]) -> BrandResolution:
    if not candidates:
        return BrandResolution(status=NOT_FOUND)
    if len(candidates) > 1:
        return BrandResolution(status=AMBIGUOUS)
    brand = next(iter(candidates.values()))
    if not brand.is_active:
        return BrandResolution(status=INACTIVE, brand_id=brand.id)
    return BrandResolution(status=FOUND, brand_id=brand.id)


def _category_resolution(candidates: dict[int, ProductCategory]) -> CategoryResolution:
    if not candidates:
        return CategoryResolution(status=NOT_FOUND)
    if len(candidates) > 1:
        return CategoryResolution(status=AMBIGUOUS)
    category = next(iter(candidates.values()))
    if not category.is_active:
        return CategoryResolution(status=INACTIVE, category_id=category.id)
    return CategoryResolution(status=FOUND, category_id=category.id)
