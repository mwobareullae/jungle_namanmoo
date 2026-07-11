from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, BrandAlias, Product, ProductCategory
from app.db.models.commerce import Inventory, Seller
from app.schemas.catalog_search import (
    CatalogSuggestionItem,
    CatalogSuggestionsResponse,
    CatalogSuggestionType,
)
from app.schemas.common import ApiError
from app.services.catalog_search_aliases import (
    equivalent_brand_values,
    known_query_correction,
    matching_brand_equivalent_values,
)
from app.services.catalog_search_query import catalog_category_suggestion_texts
from app.services.catalog_search_text import (
    compact_search_text,
    extract_chosung,
    is_all_chosung_query,
    normalize_query_text,
)
from app.services.elasticsearch_catalog_search import (
    CatalogSuggestionDocument,
    ElasticsearchCatalogSuggestionResult,
    search_elasticsearch_catalog_suggestions,
)


DEFAULT_CATALOG_SUGGESTION_LIMIT = 8
MAX_CATALOG_SUGGESTION_LIMIT = 20
SUGGESTION_DOCUMENT_MULTIPLIER = 4

CatalogElasticsearchSuggestions = Callable[..., ElasticsearchCatalogSuggestionResult]


@dataclass(frozen=True)
class CatalogSuggestionsExecution:
    response: CatalogSuggestionsResponse
    backend: str
    fallback_used: bool
    elasticsearch_attempted: bool
    elasticsearch_duration_ms: int
    correction_suggested: bool
    choseong_used: bool


def get_catalog_suggestions_response(
    session: Session,
    *,
    query: str,
    limit: int = DEFAULT_CATALOG_SUGGESTION_LIMIT,
    elasticsearch_suggestions: CatalogElasticsearchSuggestions = search_elasticsearch_catalog_suggestions,
) -> CatalogSuggestionsExecution:
    original_query = query.strip()
    normalized_query = normalize_query_text(original_query)
    es_result = elasticsearch_suggestions(
        normalized_query,
        limit=max(limit * SUGGESTION_DOCUMENT_MULTIPLIER, limit),
    )
    if es_result.successful:
        documents = es_result.documents
        backend = "elasticsearch"
        fallback_used = False
        brand_names = ()
    else:
        try:
            documents = _load_database_suggestion_documents(
                session,
                normalized_query,
                limit=max(limit * SUGGESTION_DOCUMENT_MULTIPLIER, limit),
            )
            brand_names = _load_matching_brand_names(session, normalized_query, limit=limit)
        except Exception as exc:
            raise ApiError(
                503,
                "SEARCH_UNAVAILABLE",
                "상품 검색을 일시적으로 사용할 수 없습니다.",
            ) from exc
        backend = "database"
        fallback_used = True

    correction = known_query_correction(normalized_query)
    if correction is None and es_result.suggested_queries:
        correction = es_result.suggested_queries[0]
    items = _build_suggestion_items(
        normalized_query,
        documents=documents,
        brand_names=brand_names,
        correction=correction,
        limit=limit,
    )
    response = CatalogSuggestionsResponse(query=original_query, items=items)
    return CatalogSuggestionsExecution(
        response=response,
        backend=backend,
        fallback_used=fallback_used,
        elasticsearch_attempted=es_result.attempted,
        elasticsearch_duration_ms=es_result.duration_ms,
        correction_suggested=any(item.type == CatalogSuggestionType.CORRECTION for item in items),
        choseong_used=is_all_chosung_query(normalized_query),
    )


def _build_suggestion_items(
    query: str,
    *,
    documents: Sequence[CatalogSuggestionDocument],
    brand_names: Sequence[str],
    correction: str | None,
    limit: int,
) -> list[CatalogSuggestionItem]:
    items: list[CatalogSuggestionItem] = []
    seen: set[tuple[CatalogSuggestionType, str]] = set()

    def add(item: CatalogSuggestionItem) -> None:
        key = (item.type, normalize_query_text(item.text))
        if not item.text or key in seen or len(items) >= limit:
            return
        seen.add(key)
        items.append(item)

    if correction and normalize_query_text(correction) != query:
        add(CatalogSuggestionItem(text=correction, type=CatalogSuggestionType.CORRECTION))

    for brand_name in brand_names:
        add(CatalogSuggestionItem(text=brand_name, type=CatalogSuggestionType.BRAND))
    for document in documents:
        if _brand_matches_query(document.brand_name, query):
            add(CatalogSuggestionItem(text=document.brand_name, type=CatalogSuggestionType.BRAND))
    for category_text in catalog_category_suggestion_texts(query):
        add(CatalogSuggestionItem(text=category_text, type=CatalogSuggestionType.CATEGORY))
    for document in documents:
        add(
            CatalogSuggestionItem(
                text=document.product_name,
                type=CatalogSuggestionType.PRODUCT,
                product_id=document.product_id,
            )
        )
    return items


def _load_matching_brand_names(
    session: Session,
    query: str,
    *,
    limit: int,
) -> tuple[str, ...]:
    normalized_query = normalize_query_text(query)
    prefix = f"{_escape_like(normalized_query)}%"
    equivalent_values = {
        normalize_query_text(value)
        for value in matching_brand_equivalent_values(normalized_query)
    }
    for value in tuple(equivalent_values):
        equivalent_values.update(normalize_query_text(alias) for alias in equivalent_brand_values(value))
    conditions = [
        func.lower(Brand.name).like(prefix, escape="\\"),
        func.lower(Brand.brand_code).like(prefix, escape="\\"),
        func.lower(Brand.normalized_name).like(prefix, escape="\\"),
        func.lower(BrandAlias.alias).like(prefix, escape="\\"),
        func.lower(BrandAlias.normalized_alias).like(prefix, escape="\\"),
    ]
    if equivalent_values:
        conditions.extend(
            [
                func.lower(Brand.name).in_(equivalent_values),
                func.lower(Brand.brand_code).in_(equivalent_values),
                func.lower(BrandAlias.alias).in_(equivalent_values),
            ]
        )
    rows = session.execute(
        select(Brand.name)
        .outerjoin(BrandAlias, BrandAlias.brand_id == Brand.id)
        .where(Brand.is_active.is_(True), or_(*conditions))
        .distinct()
        .order_by(Brand.name.asc())
        .limit(max(1, limit))
    ).scalars()
    return tuple(str(name) for name in rows if name)


def _load_database_suggestion_documents(
    session: Session,
    query: str,
    *,
    limit: int,
) -> tuple[CatalogSuggestionDocument, ...]:
    escaped_query = _escape_like(query)
    compact_query = _escape_like(compact_search_text(query))
    contains = f"%{escaped_query}%"
    prefix = f"{escaped_query}%"
    compact_contains = f"%{compact_query}%"
    rows = session.execute(
        select(
            Product.product_code,
            Product.product_name,
            Brand.name.label("brand_name"),
            ProductCategory.category_code,
            ProductCategory.name.label("category_name"),
        )
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, Product.seller_id == Seller.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(
            Product.is_active.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.is_active.is_(True),
            Seller.status == "ACTIVE",
            or_(Inventory.id.is_(None), Inventory.sales_status != "HIDDEN"),
            or_(
                func.lower(Product.product_code).like(prefix, escape="\\"),
                func.lower(Product.product_name).like(contains, escape="\\"),
                func.replace(func.lower(Product.product_name), " ", "").like(
                    compact_contains,
                    escape="\\",
                ),
                func.lower(Brand.name).like(prefix, escape="\\"),
                func.lower(Brand.brand_code).like(prefix, escape="\\"),
                func.lower(ProductCategory.name).like(prefix, escape="\\"),
                func.lower(ProductCategory.category_code).like(prefix, escape="\\"),
            ),
        )
        .order_by(Product.product_name.asc(), Product.id.asc())
        .limit(max(1, limit))
    ).all()
    documents = (
        CatalogSuggestionDocument(
            product_id=row.product_code,
            product_name=row.product_name,
            brand_name=row.brand_name,
            category_code=row.category_code,
            category_group="",
            category_name=row.category_name,
        )
        for row in rows
    )
    return tuple(document for document in documents if _document_matches_prefix(document, query))


def _brand_matches_query(brand_name: str, query: str) -> bool:
    if not brand_name:
        return False
    if is_all_chosung_query(query):
        return extract_chosung(brand_name).startswith(extract_chosung(query))
    compact_query = compact_search_text(query)
    compact_brand = compact_search_text(brand_name)
    return bool(compact_query) and compact_brand.startswith(compact_query)


def _document_matches_prefix(document: CatalogSuggestionDocument, query: str) -> bool:
    compact_query = compact_search_text(query)
    if not compact_query:
        return False
    values = (
        document.product_id,
        document.product_name,
        document.brand_name,
        document.category_code,
        document.category_name,
    )
    for value in values:
        normalized = normalize_query_text(value)
        if compact_search_text(normalized).startswith(compact_query):
            return True
        compact_tokens = [compact_search_text(token) for token in normalized.split()]
        if any(token.startswith(compact_query) for token in compact_tokens):
            return True
        for start in range(len(compact_tokens)):
            combined = ""
            for token in compact_tokens[start:]:
                combined += token
                if combined.startswith(compact_query):
                    return True
                if len(combined) >= len(compact_query):
                    break
    return False


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
