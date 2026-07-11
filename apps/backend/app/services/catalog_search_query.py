from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.catalog import (
    Brand,
    BrandAlias,
    ProductCategory,
    ProductCategoryAlias,
)
from app.schemas.catalog_search import CatalogSearchSort
from app.services.catalog_search_aliases import (
    equivalent_brand_values,
    matching_brand_equivalent_values,
)
from app.services.catalog_search_text import (
    CATEGORY_GROUP_LABELS,
    compact_search_text,
    normalize_query_text,
    normalize_search_text,
)


_CATEGORY_QUERY_ALIASES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "토너": (("toner",), ()),
    "스킨토너": (("toner",), ()),
    "세럼": (("serum",), ()),
    "앰플": (("serum",), ()),
    "에센스": (("serum",), ()),
    "수분크림": (("cream",), ()),
    "크림": (("cream",), ()),
    "로션": (("lotion",), ()),
    "클렌징폼": (("cleanser", "cleansing"), ()),
    "클렌저": (("cleanser", "cleansing"), ()),
    "클렌징": ((), ("cleansing",)),
    "바디워시": (("bodycare", "hair_body"), ()),
    "바디": ((), ("bodycare",)),
    "드라이샴푸": (("haircare",), ()),
    "샴푸": (("haircare",), ()),
    "헤어마스크": (("haircare",), ()),
    "헤어": ((), ("haircare",)),
    "메이크업스펀지": (("beauty_tool",), ()),
    "스펀지": (("beauty_tool",), ()),
    "뷰티소품": ((), ("beauty_tool",)),
    "마스크팩": (("mask", "mask_pack"), ()),
    "선크림": (("suncare", "sunscreen"), ()),
    "선케어": ((), ("suncare",)),
    "립틴트": ((), ("makeup",)),
    "틴트": ((), ("makeup",)),
    "쿠션": ((), ("makeup",)),
    "메이크업": ((), ("makeup",)),
    "네일폴리쉬": (("nail",), ()),
    "네일": (("nail",), ()),
    "향수": (("fragrance",), ()),
    "남성": ((), ("men",)),
    "스킨케어": ((), ("skincare",)),
}

_SORT_PHRASES: tuple[tuple[re.Pattern[str], CatalogSearchSort], ...] = (
    (re.compile(r"(?:인기|판매)\s*순"), CatalogSearchSort.POPULAR),
    (re.compile(r"(?:신상품|최신)\s*순?"), CatalogSearchSort.NEWEST),
    (re.compile(r"(?:낮은\s*가격|가격\s*낮은)\s*순"), CatalogSearchSort.PRICE_ASC),
    (re.compile(r"(?:높은\s*가격|가격\s*높은)\s*순"), CatalogSearchSort.PRICE_DESC),
    (re.compile(r"(?:평점|별점)\s*순"), CatalogSearchSort.RATING),
)
_MAN_PRICE_BAND_PATTERN = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*만원대")
_MAN_PRICE_BOUND_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*만원\s*(?P<operator>이하|미만|이상|초과)"
)
_WON_PRICE_BOUND_PATTERN = re.compile(
    r"(?P<value>[\d,]+)\s*원\s*(?P<operator>이하|미만|이상|초과)"
)
_RATING_PATTERN = re.compile(r"(?P<value>[0-5](?:\.\d+)?)\s*점\s*이상")
_IN_STOCK_PATTERN = re.compile(r"(?:재고\s*(?:있는|있음|보유)|구매\s*가능(?:한)?)")


@dataclass(frozen=True)
class CatalogSearchFilters:
    brand_codes: tuple[str, ...]
    category_codes: tuple[str, ...]
    category_groups: tuple[str, ...]
    min_price: int | None
    max_price: int | None
    min_rating: float | None
    in_stock: bool | None

    @property
    def category_values(self) -> tuple[str, ...]:
        return (*self.category_codes, *self.category_groups)


@dataclass(frozen=True)
class CatalogSearchQuery:
    original_query: str
    text_query: str
    normalized_query: str
    compact_query: str
    filters: CatalogSearchFilters
    sort: CatalogSearchSort


def catalog_category_suggestion_texts(query: str) -> tuple[str, ...]:
    compact_query = compact_search_text(query)
    if not compact_query:
        return ()
    matches = [
        alias
        for alias in _CATEGORY_QUERY_ALIASES
        if compact_search_text(alias).startswith(compact_query)
        or compact_query.startswith(compact_search_text(alias))
    ]
    return tuple(
        sorted(
            dict.fromkeys(matches),
            key=lambda value: (len(compact_search_text(value)), value),
        )
    )


def parse_catalog_search_query(
    session: Session,
    *,
    query: str,
    brands: Iterable[str] = (),
    categories: Iterable[str] = (),
    min_price: int | None = None,
    max_price: int | None = None,
    min_rating: float | None = None,
    in_stock: bool | None = None,
    sort: CatalogSearchSort = CatalogSearchSort.RELEVANCE,
    sort_is_explicit: bool = False,
) -> CatalogSearchQuery:
    original_query = query.strip()
    parsed_text, parsed_min_price, parsed_max_price = _extract_price_filters(original_query)
    parsed_text, parsed_min_rating = _extract_rating_filter(parsed_text)
    parsed_text, parsed_in_stock = _extract_stock_filter(parsed_text)
    parsed_text, parsed_sort = _extract_sort(parsed_text)
    normalized_query = normalize_query_text(parsed_text)
    compact_query = compact_search_text(parsed_text)

    explicit_brands = _dedupe(brands)
    brand_codes = (
        _resolve_brand_values(session, explicit_brands)
        if explicit_brands
        else _detect_brand_codes(session, normalized_query, compact_query)
    )
    explicit_categories = _dedupe(categories)
    if explicit_categories:
        category_codes, category_groups = _resolve_category_values(session, explicit_categories)
    else:
        category_codes, category_groups = _detect_categories(compact_query)

    resolved_min_price = min_price if min_price is not None else parsed_min_price
    resolved_max_price = max_price if max_price is not None else parsed_max_price
    resolved_min_rating = min_rating if min_rating is not None else parsed_min_rating
    resolved_in_stock = in_stock if in_stock is not None else parsed_in_stock
    resolved_sort = sort if sort_is_explicit else parsed_sort or sort

    return CatalogSearchQuery(
        original_query=original_query,
        text_query=normalized_query,
        normalized_query=normalized_query,
        compact_query=compact_query,
        filters=CatalogSearchFilters(
            brand_codes=brand_codes,
            category_codes=category_codes,
            category_groups=category_groups,
            min_price=resolved_min_price,
            max_price=resolved_max_price,
            min_rating=resolved_min_rating,
            in_stock=resolved_in_stock,
        ),
        sort=resolved_sort,
    )


def _extract_price_filters(value: str) -> tuple[str, int | None, int | None]:
    min_price: int | None = None
    max_price: int | None = None

    def replace_band(match: re.Match[str]) -> str:
        nonlocal min_price, max_price
        band_start = int(float(match.group("value")) * 10_000)
        min_price = band_start
        max_price = band_start + 9_999
        return " "

    remaining = _MAN_PRICE_BAND_PATTERN.sub(replace_band, value)

    def replace_man_bound(match: re.Match[str]) -> str:
        nonlocal min_price, max_price
        amount = int(float(match.group("value")) * 10_000)
        min_price, max_price = _apply_price_bound(
            amount,
            match.group("operator"),
            min_price=min_price,
            max_price=max_price,
        )
        return " "

    remaining = _MAN_PRICE_BOUND_PATTERN.sub(replace_man_bound, remaining)

    def replace_won_bound(match: re.Match[str]) -> str:
        nonlocal min_price, max_price
        amount = int(match.group("value").replace(",", ""))
        min_price, max_price = _apply_price_bound(
            amount,
            match.group("operator"),
            min_price=min_price,
            max_price=max_price,
        )
        return " "

    remaining = _WON_PRICE_BOUND_PATTERN.sub(replace_won_bound, remaining)
    return normalize_search_text(remaining), min_price, max_price


def _apply_price_bound(
    amount: int,
    operator: str,
    *,
    min_price: int | None,
    max_price: int | None,
) -> tuple[int | None, int | None]:
    if operator == "이하":
        max_price = amount
    elif operator == "미만":
        max_price = max(amount - 1, 0)
    elif operator == "이상":
        min_price = amount
    elif operator == "초과":
        min_price = amount + 1
    return min_price, max_price


def _extract_rating_filter(value: str) -> tuple[str, float | None]:
    match = _RATING_PATTERN.search(value)
    if match is None:
        return value, None
    rating = float(match.group("value"))
    return normalize_search_text(_RATING_PATTERN.sub(" ", value)), rating


def _extract_stock_filter(value: str) -> tuple[str, bool | None]:
    if _IN_STOCK_PATTERN.search(value) is None:
        return value, None
    return normalize_search_text(_IN_STOCK_PATTERN.sub(" ", value)), True


def _extract_sort(value: str) -> tuple[str, CatalogSearchSort | None]:
    for pattern, sort in _SORT_PHRASES:
        if pattern.search(value) is not None:
            return normalize_search_text(pattern.sub(" ", value)), sort
    return value, None


def _resolve_brand_values(session: Session, values: tuple[str, ...]) -> tuple[str, ...]:
    lookup = _brand_lookup(session)
    resolved: list[str] = []
    for value in values:
        matched_existing = False
        for equivalent in equivalent_brand_values(value):
            brand_code = lookup.get(_lookup_key(equivalent))
            if brand_code is None:
                continue
            matched_existing = True
            resolved.append(brand_code)
        if not matched_existing:
            resolved.append(normalize_search_text(value))
    return _dedupe(resolved)


def _detect_brand_codes(
    session: Session,
    normalized_query: str,
    compact_query: str,
) -> tuple[str, ...]:
    lookup = _brand_lookup(session)
    matches: list[tuple[int, str]] = []
    for alias_key, brand_code in lookup.items():
        compact_alias = compact_search_text(alias_key)
        if not compact_alias:
            continue
        if len(compact_alias) <= 1:
            matched = compact_query == compact_alias or alias_key in normalized_query.split()
        else:
            matched = compact_alias in compact_query or alias_key in normalized_query
        if matched:
            matches.append((len(compact_alias), brand_code))
    if not matches:
        return ()
    longest = max(length for length, _ in matches)
    matched_codes = [brand_code for length, brand_code in matches if length == longest]
    for equivalent in matching_brand_equivalent_values(normalized_query):
        brand_code = lookup.get(_lookup_key(equivalent))
        if brand_code is not None:
            matched_codes.append(brand_code)
    return _dedupe(matched_codes)


def _brand_lookup(session: Session) -> dict[str, str]:
    rows = session.execute(
        select(
            Brand.brand_code,
            Brand.name,
            Brand.normalized_name,
            BrandAlias.alias,
            BrandAlias.normalized_alias,
        )
        .outerjoin(BrandAlias, BrandAlias.brand_id == Brand.id)
        .where(Brand.is_active.is_(True))
    ).all()
    lookup: dict[str, str] = {}
    for brand_code, name, normalized_name, alias, normalized_alias in rows:
        for value in (brand_code, name, normalized_name, alias, normalized_alias):
            if value:
                lookup[_lookup_key(str(value))] = str(brand_code)
    return lookup


def _resolve_category_values(
    session: Session,
    values: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    category_lookup = _category_lookup(session)
    group_lookup = {
        _lookup_key(group): group
        for group in CATEGORY_GROUP_LABELS
    }
    group_lookup.update(
        {_lookup_key(label): group for group, label in CATEGORY_GROUP_LABELS.items()}
    )
    category_codes: list[str] = []
    category_groups: list[str] = []
    for value in values:
        key = _lookup_key(value)
        if key in group_lookup:
            category_groups.append(group_lookup[key])
        else:
            category_codes.append(category_lookup.get(key, normalize_search_text(value)))
    return _dedupe(category_codes), _dedupe(category_groups)


def _category_lookup(session: Session) -> dict[str, str]:
    rows = session.execute(
        select(
            ProductCategory.category_code,
            ProductCategory.name,
            ProductCategoryAlias.alias,
            ProductCategoryAlias.normalized_alias,
        )
        .outerjoin(ProductCategoryAlias, ProductCategoryAlias.category_id == ProductCategory.id)
        .where(ProductCategory.is_active.is_(True))
    ).all()
    lookup: dict[str, str] = {}
    for category_code, name, alias, normalized_alias in rows:
        for value in (category_code, name, alias, normalized_alias):
            if value:
                lookup[_lookup_key(str(value))] = str(category_code)
    return lookup


def _detect_categories(compact_query: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    matches: list[tuple[int, tuple[str, ...], tuple[str, ...]]] = []
    for alias, (category_codes, category_groups) in _CATEGORY_QUERY_ALIASES.items():
        compact_alias = compact_search_text(alias)
        if compact_alias and compact_alias in compact_query:
            matches.append((len(compact_alias), category_codes, category_groups))
    if not matches:
        return (), ()
    longest = max(length for length, _, _ in matches)
    category_codes: list[str] = []
    category_groups: list[str] = []
    for length, matched_codes, matched_groups in matches:
        if length != longest:
            continue
        category_codes.extend(matched_codes)
        category_groups.extend(matched_groups)
    return _dedupe(category_codes), _dedupe(category_groups)


def _lookup_key(value: str) -> str:
    compact = compact_search_text(value)
    return compact or normalize_search_text(value)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)
