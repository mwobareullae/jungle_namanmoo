from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.db.models.commerce import Inventory, ProductPopularityMetric, Seller
from app.schemas.catalog_search import (
    CatalogSearchAppliedFilters,
    CatalogSearchFacetItem,
    CatalogSearchFacets,
    CatalogSearchItem,
    CatalogSearchPagination,
    CatalogSearchResponse,
    CatalogSearchSort,
)
from app.schemas.common import ApiError
from app.services.catalog_search_query import (
    CatalogSearchFilters,
    CatalogSearchQuery,
    parse_catalog_search_query,
)
from app.services.catalog_search_aliases import known_query_correction
from app.services.catalog_search_recovery import (
    CatalogSearchRecoveryPlan,
    build_catalog_search_recovery_plan,
)
from app.services.catalog_search_text import (
    CATEGORY_GROUP_LABELS,
    category_group_for_code,
    is_all_chosung_query,
    normalize_search_text,
)
from app.services.elasticsearch_catalog_search import (
    ElasticsearchCatalogSearchResult,
    search_elasticsearch_catalog_products,
)


DEFAULT_CATALOG_SEARCH_PAGE = 1
DEFAULT_CATALOG_SEARCH_PAGE_SIZE = 20
MAX_CATALOG_SEARCH_PAGE_SIZE = 50
CATALOG_SEARCH_FALLBACK_LIMIT = 500
POPULARITY_WINDOW_DAYS = 7
MAX_RECOVERY_FETCH = 250

_PRICE_FACETS: tuple[tuple[str, str, int | None, int | None], ...] = (
    ("under_10000", "1만원 미만", 0, 10_000),
    ("10000_19999", "1~2만원", 10_000, 20_000),
    ("20000_29999", "2~3만원", 20_000, 30_000),
    ("30000_49999", "3~5만원", 30_000, 50_000),
    ("50000_plus", "5만원 이상", 50_000, None),
)


CatalogElasticsearchSearch = Callable[..., ElasticsearchCatalogSearchResult]


@dataclass(frozen=True)
class CatalogSearchExecution:
    response: CatalogSearchResponse
    backend: str
    fallback_used: bool
    elasticsearch_attempted: bool
    elasticsearch_duration_ms: int
    recovery_used: bool = False
    choseong_used: bool = False
    keyboard_conversion_used: bool = False


def get_catalog_search_response(
    session: Session,
    *,
    query: str,
    page: int = DEFAULT_CATALOG_SEARCH_PAGE,
    page_size: int = DEFAULT_CATALOG_SEARCH_PAGE_SIZE,
    brands: Iterable[str] = (),
    categories: Iterable[str] = (),
    min_price: int | None = None,
    max_price: int | None = None,
    min_rating: float | None = None,
    in_stock: bool | None = None,
    sort: CatalogSearchSort = CatalogSearchSort.RELEVANCE,
    sort_is_explicit: bool = False,
    elasticsearch_search: CatalogElasticsearchSearch = search_elasticsearch_catalog_products,
) -> CatalogSearchExecution:
    try:
        parsed_query = parse_catalog_search_query(
            session,
            query=query,
            brands=brands,
            categories=categories,
            min_price=min_price,
            max_price=max_price,
            min_rating=min_rating,
            in_stock=in_stock,
            sort=sort,
            sort_is_explicit=sort_is_explicit,
        )
    except Exception as exc:
        raise _search_unavailable() from exc

    if (
        parsed_query.filters.min_price is not None
        and parsed_query.filters.max_price is not None
        and parsed_query.filters.min_price > parsed_query.filters.max_price
    ):
        raise ApiError(400, "INVALID_SEARCH_FILTER", "최소 가격은 최대 가격보다 클 수 없습니다.")

    offset = (page - 1) * page_size
    es_result = elasticsearch_search(
        parsed_query,
        offset=offset,
        limit=page_size,
    )
    if es_result.successful:
        try:
            recovery_plan = _build_recovery_plan_for_result(
                session,
                parsed_query,
                normal_result=es_result,
            )
            selected_result, recovery_used, search_duration_ms = _recover_low_result_search(
                parsed_query,
                normal_result=es_result,
                recovery_plan=recovery_plan,
                offset=offset,
                page_size=page_size,
                elasticsearch_search=elasticsearch_search,
            )
            corrected_query = (
                recovery_plan.corrected_query
                if recovery_used or recovery_plan.confident_correction
                else None
            )
            if recovery_used and corrected_query is None and selected_result.suggested_queries:
                corrected_query = selected_result.suggested_queries[0]

            rows = _load_catalog_rows(session, selected_result.product_db_ids)
            ordered_rows = _order_rows(rows, selected_result.product_db_ids)
            current_rows = [
                row
                for row in ordered_rows
                if _row_matches_filters(row, parsed_query.filters)
            ]
            stale_count = len(selected_result.product_db_ids) - len(current_rows)
            items = [_row_to_item(row) for row in current_rows]
            total_items = max(
                offset + len(items),
                max(0, selected_result.total_hit_count - stale_count),
            )
            facets = _facets_from_elasticsearch(session, selected_result.aggregations)
            response = _build_response(
                parsed_query,
                items=items,
                facets=facets,
                page=page,
                page_size=page_size,
                total_items=total_items,
                corrected_query=corrected_query,
            )
            return CatalogSearchExecution(
                response=response,
                backend="elasticsearch",
                fallback_used=False,
                elasticsearch_attempted=es_result.attempted,
                elasticsearch_duration_ms=search_duration_ms,
                recovery_used=recovery_used,
                choseong_used=recovery_plan.choseong_used,
                keyboard_conversion_used=recovery_plan.keyboard_conversion_used,
            )
        except Exception:
            pass

    try:
        fallback_rows = _search_catalog_rows_with_database(
            session,
            parsed_query,
            limit=CATALOG_SEARCH_FALLBACK_LIMIT,
        )
    except Exception as exc:
        raise _search_unavailable() from exc

    total_items = len(fallback_rows)
    page_rows = fallback_rows[offset : offset + page_size]
    response = _build_response(
        parsed_query,
        items=[_row_to_item(row) for row in page_rows],
        facets=_facets_from_rows(fallback_rows),
        page=page,
        page_size=page_size,
        total_items=total_items,
        corrected_query=None,
    )
    return CatalogSearchExecution(
        response=response,
        backend="database",
        fallback_used=True,
        elasticsearch_attempted=es_result.attempted,
        elasticsearch_duration_ms=es_result.duration_ms,
        choseong_used=is_all_chosung_query(parsed_query.text_query),
    )


def _build_recovery_plan_for_result(
    session: Session,
    parsed_query: CatalogSearchQuery,
    *,
    normal_result: ElasticsearchCatalogSearchResult,
) -> CatalogSearchRecoveryPlan:
    if normal_result.total_hit_count < 3:
        return build_catalog_search_recovery_plan(session, parsed_query)

    corrected_query = known_query_correction(parsed_query.text_query)
    return CatalogSearchRecoveryPlan(
        variants=(),
        corrected_query=corrected_query,
        fuzzy_enabled=False,
        keyboard_conversion_used=False,
        choseong_used=is_all_chosung_query(parsed_query.text_query),
        confident_correction=corrected_query is not None,
    )


def _recover_low_result_search(
    parsed_query: CatalogSearchQuery,
    *,
    normal_result: ElasticsearchCatalogSearchResult,
    recovery_plan: CatalogSearchRecoveryPlan,
    offset: int,
    page_size: int,
    elasticsearch_search: CatalogElasticsearchSearch,
) -> tuple[ElasticsearchCatalogSearchResult, bool, int]:
    if normal_result.total_hit_count >= 3 or not recovery_plan.should_search:
        return normal_result, False, normal_result.duration_ms

    recovery_fetch = min(max(offset + page_size, page_size), MAX_RECOVERY_FETCH)
    recovery_result = elasticsearch_search(
        parsed_query,
        offset=0 if normal_result.total_hit_count > 0 else offset,
        limit=recovery_fetch if normal_result.total_hit_count > 0 else page_size,
        recovery_variants=recovery_plan.variants,
        fuzzy_enabled=recovery_plan.fuzzy_enabled,
        recovery_only=True,
    )
    total_duration_ms = normal_result.duration_ms + recovery_result.duration_ms
    if not recovery_result.successful:
        return normal_result, False, total_duration_ms
    if normal_result.total_hit_count == 0:
        return recovery_result, True, total_duration_ms

    normal_ids = normal_result.product_db_ids
    if offset > 0 and len(normal_ids) < normal_result.total_hit_count:
        anchor_result = elasticsearch_search(
            parsed_query,
            offset=0,
            limit=min(normal_result.total_hit_count, 2),
        )
        total_duration_ms += anchor_result.duration_ms
        if anchor_result.successful:
            normal_ids = anchor_result.product_db_ids
    merged_ids = _dedupe_product_ids((*normal_ids, *recovery_result.product_db_ids))
    page_ids = merged_ids[offset : offset + page_size]
    return (
        ElasticsearchCatalogSearchResult(
            product_db_ids=page_ids,
            total_hit_count=max(normal_result.total_hit_count, recovery_result.total_hit_count),
            aggregations=recovery_result.aggregations or normal_result.aggregations,
            attempted=True,
            duration_ms=total_duration_ms,
            index_alias=normal_result.index_alias,
            suggested_queries=recovery_result.suggested_queries,
        ),
        True,
        total_duration_ms,
    )


def _dedupe_product_ids(product_db_ids: Sequence[int]) -> tuple[int, ...]:
    result: list[int] = []
    seen: set[int] = set()
    for product_db_id in product_db_ids:
        if product_db_id in seen:
            continue
        seen.add(product_db_id)
        result.append(product_db_id)
    return tuple(result)


def _load_catalog_rows(session: Session, product_db_ids: Sequence[int]) -> list[Any]:
    if not product_db_ids:
        return []
    statement = _catalog_row_statement(price_product_db_ids=product_db_ids).where(
        Product.id.in_(product_db_ids),
        *_catalog_eligibility(),
    )
    return list(session.execute(statement).all())


def _search_catalog_rows_with_database(
    session: Session,
    parsed_query: CatalogSearchQuery,
    *,
    limit: int,
) -> list[Any]:
    statement = _catalog_row_statement().where(*_catalog_eligibility())
    searchable_fields = (
        func.lower(Product.product_code),
        func.lower(Product.product_name),
        func.lower(Brand.name),
        func.lower(Brand.brand_code),
        func.lower(ProductCategory.name),
        func.lower(ProductCategory.category_code),
    )
    for term in parsed_query.text_query.split():
        escaped_term = _escape_like(term.casefold())
        pattern = f"%{escaped_term}%"
        statement = statement.where(
            or_(*(field.like(pattern, escape="\\") for field in searchable_fields))
        )
    statement = _apply_database_filters(statement, parsed_query.filters)
    statement = statement.order_by(*_database_sort(parsed_query, statement))
    return list(session.execute(statement.limit(max(1, limit))).all())


def _catalog_row_statement(
    *,
    price_product_db_ids: Sequence[int] = (),
) -> Any:
    lowest_price_statement = (
        select(
            ProductPrice.product_id.label("product_id"),
            func.min(ProductPrice.price).label("lowest_price"),
        )
        .group_by(ProductPrice.product_id)
    )
    if price_product_db_ids:
        lowest_price_statement = lowest_price_statement.where(
            ProductPrice.product_id.in_(price_product_db_ids)
        )
    lowest_price = lowest_price_statement.subquery()
    return (
        select(
            Product.id.label("product_db_id"),
            Product.product_code,
            Product.product_name,
            Product.thumbnail_url,
            Product.created_at,
            Brand.brand_code,
            Brand.name.label("brand_name"),
            ProductCategory.category_code,
            ProductCategory.name.label("category_name"),
            lowest_price.c.lowest_price,
            Inventory.id.label("inventory_id"),
            Inventory.stock_quantity,
            Inventory.reserved_quantity,
            Inventory.safety_stock,
            Inventory.sales_status,
            ProductPopularityMetric.average_rating,
            ProductPopularityMetric.review_count,
            ProductPopularityMetric.popularity_score,
        )
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, Product.seller_id == Seller.id)
        .outerjoin(lowest_price, lowest_price.c.product_id == Product.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .outerjoin(
            ProductPopularityMetric,
            (ProductPopularityMetric.product_id == Product.id)
            & (ProductPopularityMetric.window_days == POPULARITY_WINDOW_DAYS),
        )
    )


def _catalog_eligibility() -> tuple[Any, ...]:
    return (
        Product.is_active.is_(True),
        Brand.is_active.is_(True),
        ProductCategory.is_active.is_(True),
        Seller.status == "ACTIVE",
        or_(Inventory.id.is_(None), Inventory.sales_status != "HIDDEN"),
    )


def _apply_database_filters(statement: Any, filters: CatalogSearchFilters) -> Any:
    if filters.brand_codes:
        statement = statement.where(Brand.brand_code.in_(filters.brand_codes))
    category_conditions: list[Any] = []
    if filters.category_codes:
        category_conditions.append(ProductCategory.category_code.in_(filters.category_codes))
    if filters.category_groups:
        grouped_codes = [
            category_code
            for category_code in _all_known_category_codes()
            if category_group_for_code(category_code) in filters.category_groups
        ]
        if grouped_codes:
            category_conditions.append(ProductCategory.category_code.in_(grouped_codes))
        if "other" in filters.category_groups:
            non_other_codes = [
                category_code
                for category_code in _all_known_category_codes()
                if category_group_for_code(category_code) != "other"
            ]
            category_conditions.append(ProductCategory.category_code.not_in(non_other_codes))
    if category_conditions:
        statement = statement.where(or_(*category_conditions))
    if filters.min_price is not None:
        statement = statement.where(_column(statement, "lowest_price") >= filters.min_price)
    if filters.max_price is not None:
        statement = statement.where(_column(statement, "lowest_price") <= filters.max_price)
    if filters.min_rating is not None:
        statement = statement.where(ProductPopularityMetric.average_rating >= filters.min_rating)
    if filters.in_stock is True:
        statement = statement.where(
            Inventory.sales_status == "ON_SALE",
            (
                Inventory.stock_quantity
                - Inventory.reserved_quantity
                - Inventory.safety_stock
            )
            > 0,
        )
    return statement


def _database_sort(parsed_query: CatalogSearchQuery, statement: Any) -> tuple[Any, ...]:
    stable_id = Product.id.asc()
    if parsed_query.sort == CatalogSearchSort.POPULAR:
        return (ProductPopularityMetric.popularity_score.desc().nulls_last(), stable_id)
    if parsed_query.sort == CatalogSearchSort.NEWEST:
        return (Product.created_at.desc(), stable_id)
    if parsed_query.sort == CatalogSearchSort.PRICE_ASC:
        return (_column(statement, "lowest_price").asc().nulls_last(), stable_id)
    if parsed_query.sort == CatalogSearchSort.PRICE_DESC:
        return (_column(statement, "lowest_price").desc().nulls_last(), stable_id)
    if parsed_query.sort == CatalogSearchSort.RATING:
        return (
            ProductPopularityMetric.average_rating.desc().nulls_last(),
            ProductPopularityMetric.review_count.desc(),
            stable_id,
        )
    normalized = normalize_search_text(parsed_query.text_query)
    return (
        case(
            (func.lower(Product.product_code) == normalized, 0),
            (func.lower(Product.product_name) == normalized, 1),
            (func.lower(Brand.name) == normalized, 2),
            else_=3,
        ).asc(),
        ProductPopularityMetric.popularity_score.desc().nulls_last(),
        stable_id,
    )


def _column(statement: Any, name: str) -> Any:
    for column in statement.selected_columns:
        if column.key == name:
            return column
    raise KeyError(name)


def _order_rows(rows: Sequence[Any], product_db_ids: Sequence[int]) -> list[Any]:
    rows_by_id = {int(row.product_db_id): row for row in rows}
    return [rows_by_id[product_id] for product_id in product_db_ids if product_id in rows_by_id]


def _row_matches_filters(row: Any, filters: CatalogSearchFilters) -> bool:
    if filters.brand_codes and row.brand_code not in filters.brand_codes:
        return False
    if filters.category_codes or filters.category_groups:
        category_group = category_group_for_code(row.category_code)
        if (
            row.category_code not in filters.category_codes
            and category_group not in filters.category_groups
        ):
            return False
    if filters.min_price is not None and (
        row.lowest_price is None or int(row.lowest_price) < filters.min_price
    ):
        return False
    if filters.max_price is not None and (
        row.lowest_price is None or int(row.lowest_price) > filters.max_price
    ):
        return False
    if filters.min_rating is not None and (
        row.average_rating is None or float(row.average_rating) < filters.min_rating
    ):
        return False
    if filters.in_stock is True and not _row_in_stock(row):
        return False
    return True


def _row_to_item(row: Any) -> CatalogSearchItem:
    return CatalogSearchItem(
        product_id=row.product_code,
        brand=row.brand_name,
        name=row.product_name,
        category_code=row.category_code,
        category_group=category_group_for_code(row.category_code),
        category_name=row.category_name,
        thumbnail_url=row.thumbnail_url or "",
        lowest_price=int(row.lowest_price) if row.lowest_price is not None else None,
        rating=float(row.average_rating) if row.average_rating is not None else None,
        review_count=int(row.review_count or 0),
        sales_status=row.sales_status if row.inventory_id is not None else "UNKNOWN",
    )


def _row_in_stock(row: Any) -> bool:
    if row.inventory_id is None or row.sales_status != "ON_SALE":
        return False
    available = (
        int(row.stock_quantity or 0)
        - int(row.reserved_quantity or 0)
        - int(row.safety_stock or 0)
    )
    return available > 0


def _facets_from_elasticsearch(
    session: Session,
    aggregations: dict[str, Any],
) -> CatalogSearchFacets:
    brand_buckets = _aggregation_buckets(aggregations.get("brands"))
    brand_codes = [str(bucket.get("key")) for bucket in brand_buckets]
    brand_labels = {
        brand_code: name
        for brand_code, name in session.execute(
            select(Brand.brand_code, Brand.name).where(Brand.brand_code.in_(brand_codes))
        ).all()
    }
    brands = [
        CatalogSearchFacetItem(
            value=str(bucket.get("key")),
            label=brand_labels.get(str(bucket.get("key")), str(bucket.get("key"))),
            count=int(bucket.get("doc_count") or 0),
        )
        for bucket in brand_buckets
    ]
    categories = [
        CatalogSearchFacetItem(
            value=str(bucket.get("key")),
            label=CATEGORY_GROUP_LABELS.get(str(bucket.get("key")), str(bucket.get("key"))),
            count=int(bucket.get("doc_count") or 0),
        )
        for bucket in _aggregation_buckets(aggregations.get("categories"))
    ]
    price_counts = _keyed_bucket_counts(aggregations.get("price_ranges"))
    availability_counts = _keyed_bucket_counts(aggregations.get("availability"))
    return CatalogSearchFacets(
        brands=brands,
        categories=categories,
        price_ranges=[
            CatalogSearchFacetItem(value=value, label=label, count=price_counts.get(value, 0))
            for value, label, _, _ in _PRICE_FACETS
        ],
        availability=[
            CatalogSearchFacetItem(
                value="in_stock",
                label="판매 가능",
                count=availability_counts.get("in_stock", 0),
            ),
            CatalogSearchFacetItem(
                value="sold_out",
                label="품절",
                count=availability_counts.get("sold_out", 0),
            ),
        ],
    )


def _facets_from_rows(rows: Sequence[Any]) -> CatalogSearchFacets:
    brand_counts = Counter(str(row.brand_code) for row in rows)
    brand_labels = {str(row.brand_code): str(row.brand_name) for row in rows}
    category_counts = Counter(category_group_for_code(str(row.category_code)) for row in rows)
    price_counts: Counter[str] = Counter()
    availability_counts: Counter[str] = Counter()
    for row in rows:
        if row.lowest_price is not None:
            price_bucket = _price_bucket(int(row.lowest_price))
            if price_bucket is not None:
                price_counts[price_bucket] += 1
        if _row_in_stock(row):
            availability_counts["in_stock"] += 1
        elif row.sales_status == "SOLD_OUT":
            availability_counts["sold_out"] += 1
    return CatalogSearchFacets(
        brands=[
            CatalogSearchFacetItem(value=value, label=brand_labels[value], count=count)
            for value, count in brand_counts.most_common(50)
        ],
        categories=[
            CatalogSearchFacetItem(
                value=value,
                label=CATEGORY_GROUP_LABELS.get(value, value),
                count=count,
            )
            for value, count in category_counts.most_common()
        ],
        price_ranges=[
            CatalogSearchFacetItem(value=value, label=label, count=price_counts[value])
            for value, label, _, _ in _PRICE_FACETS
        ],
        availability=[
            CatalogSearchFacetItem(
                value="in_stock",
                label="판매 가능",
                count=availability_counts["in_stock"],
            ),
            CatalogSearchFacetItem(
                value="sold_out",
                label="품절",
                count=availability_counts["sold_out"],
            ),
        ],
    )


def _build_response(
    parsed_query: CatalogSearchQuery,
    *,
    items: list[CatalogSearchItem],
    facets: CatalogSearchFacets,
    page: int,
    page_size: int,
    total_items: int,
    corrected_query: str | None,
) -> CatalogSearchResponse:
    total_pages = ceil(total_items / page_size) if total_items else 0
    return CatalogSearchResponse(
        query=parsed_query.original_query,
        corrected_query=corrected_query,
        items=items,
        pagination=CatalogSearchPagination(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1 and total_pages > 0,
        ),
        facets=facets,
        applied_filters=CatalogSearchAppliedFilters(
            brands=list(parsed_query.filters.brand_codes),
            categories=list(parsed_query.filters.category_values),
            min_price=parsed_query.filters.min_price,
            max_price=parsed_query.filters.max_price,
            min_rating=parsed_query.filters.min_rating,
            in_stock=parsed_query.filters.in_stock,
        ),
        sort=parsed_query.sort,
    )


def _aggregation_buckets(aggregation: Any) -> list[dict[str, Any]]:
    if not isinstance(aggregation, dict):
        return []
    buckets = aggregation.get("buckets") or []
    if isinstance(buckets, list):
        return [bucket for bucket in buckets if isinstance(bucket, dict)]
    if isinstance(buckets, dict):
        return [
            {"key": key, **(bucket if isinstance(bucket, dict) else {})}
            for key, bucket in buckets.items()
        ]
    return []


def _keyed_bucket_counts(aggregation: Any) -> dict[str, int]:
    return {
        str(bucket.get("key")): int(bucket.get("doc_count") or 0)
        for bucket in _aggregation_buckets(aggregation)
    }


def _price_bucket(price: int) -> str | None:
    for value, _, minimum, maximum in _PRICE_FACETS:
        if minimum is not None and price < minimum:
            continue
        if maximum is not None and price >= maximum:
            continue
        return value
    return None


def _all_known_category_codes() -> tuple[str, ...]:
    from app.services.catalog_search_text import CATEGORY_GROUP_BY_CODE

    return tuple(CATEGORY_GROUP_BY_CODE)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_unavailable() -> ApiError:
    return ApiError(
        503,
        "SEARCH_UNAVAILABLE",
        "상품 검색을 일시적으로 사용할 수 없습니다.",
    )
