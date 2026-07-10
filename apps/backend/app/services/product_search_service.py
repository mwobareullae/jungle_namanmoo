from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.db.models.search import SearchDocument
from app.schemas.product import (
    ProductSearchDiagnostics,
    ProductSearchItem,
    ProductSearchPagination,
    ProductSearchResponse,
)
from app.services.elasticsearch_product_search import (
    ElasticsearchProductSearchResult,
    search_elasticsearch_product_candidates,
)
from app.services.pgvector_product_search import (
    PgvectorProductSearchResult,
    search_pgvector_product_candidates,
)
from app.services.product_candidates import (
    ProductCandidate,
    list_product_candidates_by_db_ids,
)
from app.services.product_image_service import load_thumbnail_storage_keys
from app.services.purchase_conditions import ParsedPurchaseConditions
from app.services.recommendation_intent import build_recommendation_intent
from app.services.search_index_builder import DOCUMENT_CODE_PREFIX


DEFAULT_PRODUCT_SEARCH_PAGE = 1
DEFAULT_PRODUCT_SEARCH_PAGE_SIZE = 20
MAX_PRODUCT_SEARCH_PAGE_SIZE = 50
ElasticsearchSearchFunc = Callable[..., ElasticsearchProductSearchResult]
PgvectorSearchFunc = Callable[..., PgvectorProductSearchResult]


@dataclass(frozen=True)
class _DbSearchHit:
    product_db_id: int
    score: float


def get_product_search_response(
    session: Session,
    *,
    query: str,
    page: int = DEFAULT_PRODUCT_SEARCH_PAGE,
    page_size: int = DEFAULT_PRODUCT_SEARCH_PAGE_SIZE,
    enable_elasticsearch: bool | None = None,
    enable_pgvector: bool | None = None,
    elasticsearch_search: ElasticsearchSearchFunc = search_elasticsearch_product_candidates,
    pgvector_search: PgvectorSearchFunc = search_pgvector_product_candidates,
) -> ProductSearchResponse:
    normalized_query = query.strip()
    pagination = _normalize_pagination(page, page_size, total_items=0)
    intent = build_recommendation_intent(normalized_query)

    if _should_attempt_elasticsearch(session, enable_elasticsearch=enable_elasticsearch):
        es_result = elasticsearch_search(
            intent,
            limit=pagination.page_size,
            offset=pagination.offset,
        )
    else:
        es_result = ElasticsearchProductSearchResult(
            product_db_ids=(),
            raw_hit_count=0,
            attempted=False,
            index_alias=settings.elasticsearch_products_alias,
            query_text=normalized_query,
            duration_ms=0,
            skipped_reason=_elasticsearch_skip_reason(
                session,
                enable_elasticsearch=enable_elasticsearch,
            ),
            total_hit_count=0,
        )
    vector_result: PgvectorProductSearchResult | None = None
    if es_result.successful:
        es_candidates = list_product_candidates_by_db_ids(
            session,
            intent.purchase_conditions,
            list(es_result.product_db_ids),
            limit=pagination.page_size,
            recommendable_only=False,
        )
        vector_candidates: list[ProductCandidate] = []
        if len(es_candidates) < pagination.page_size and pagination.page == 1:
            vector_result = _search_pgvector_or_skip(
                session,
                intent,
                limit=pagination.page_size + len(es_candidates),
                offset=0,
                enable_pgvector=enable_pgvector,
                pgvector_search=pgvector_search,
            )
            if vector_result.successful:
                existing_ids = {candidate.db_product_id for candidate in es_candidates}
                vector_product_db_ids = [
                    product_db_id
                    for product_db_id in vector_result.product_db_ids
                    if product_db_id not in existing_ids
                ]
                vector_candidates = list_product_candidates_by_db_ids(
                    session,
                    intent.purchase_conditions,
                    vector_product_db_ids,
                    limit=max(0, pagination.page_size - len(es_candidates)),
                    recommendable_only=False,
                )
        combined_candidates = [*es_candidates, *vector_candidates]
        es_total_items = (
            es_result.total_hit_count
            if es_result.total_hit_count is not None
            else len(combined_candidates)
        )
        total_items = max(es_total_items, len(combined_candidates))
        backend = "hybrid" if vector_candidates else "elasticsearch"
        return ProductSearchResponse(
            query=normalized_query,
            items=[
                *_candidate_search_items(session, es_candidates, match_source="elasticsearch"),
                *_candidate_search_items(
                    session,
                    vector_candidates,
                    match_source="pgvector",
                    scores_by_product_id=(
                        vector_result.scores_by_product_db_id
                        if vector_result is not None
                        else None
                    ),
                ),
            ],
            pagination=_normalize_pagination(page, page_size, total_items=total_items).to_schema(),
            diagnostics=ProductSearchDiagnostics(
                backend=backend,
                fallback_used=False,
                es_attempted=es_result.attempted,
                es_failure_reason=None,
                es_duration_ms=es_result.duration_ms,
                vector_attempted=vector_result.attempted if vector_result is not None else False,
                vector_failure_reason=_vector_failure_reason(vector_result),
                vector_duration_ms=vector_result.duration_ms if vector_result is not None else None,
                vector_result_count=vector_result.raw_hit_count if vector_result is not None else 0,
                vector_embedding_coverage=(
                    vector_result.embedding_coverage
                    if vector_result is not None
                    else None
                ),
            ),
        )

    vector_result = _search_pgvector_or_skip(
        session,
        intent,
        limit=pagination.page_size,
        offset=pagination.offset,
        enable_pgvector=enable_pgvector,
        pgvector_search=pgvector_search,
    )
    if vector_result.successful:
        candidates = list_product_candidates_by_db_ids(
            session,
            intent.purchase_conditions,
            list(vector_result.product_db_ids),
            limit=pagination.page_size,
            recommendable_only=False,
        )
        total_items = (
            vector_result.total_hit_count
            if vector_result.total_hit_count is not None
            else len(candidates)
        )
        return ProductSearchResponse(
            query=normalized_query,
            items=_candidate_search_items(
                session,
                candidates,
                match_source="pgvector",
                scores_by_product_id=vector_result.scores_by_product_db_id,
            ),
            pagination=_normalize_pagination(page, page_size, total_items=total_items).to_schema(),
            diagnostics=ProductSearchDiagnostics(
                backend="pgvector",
                fallback_used=es_result.attempted,
                es_attempted=es_result.attempted,
                es_failure_reason=es_result.failure_reason or es_result.skipped_reason,
                es_duration_ms=es_result.duration_ms,
                vector_attempted=vector_result.attempted,
                vector_failure_reason=None,
                vector_duration_ms=vector_result.duration_ms,
                vector_result_count=vector_result.raw_hit_count,
                vector_embedding_coverage=vector_result.embedding_coverage,
            ),
        )

    db_hits = _search_products_in_database(
        session,
        query=normalized_query,
        purchase_conditions=intent.purchase_conditions,
        limit=pagination.page_size,
        offset=pagination.offset,
    )
    candidates = list_product_candidates_by_db_ids(
        session,
        intent.purchase_conditions,
        [hit.product_db_id for hit in db_hits.page_hits],
        limit=pagination.page_size,
        recommendable_only=False,
    )
    scores_by_product_id = {
        hit.product_db_id: hit.score
        for hit in db_hits.page_hits
    }

    category_names = _load_category_names_by_product_id(
        session,
        [candidate.db_product_id for candidate in candidates],
    )

    return ProductSearchResponse(
        query=normalized_query,
        items=[
            _product_search_item(
                candidate,
                category_name=category_names.get(candidate.db_product_id, ""),
                search_score=scores_by_product_id.get(candidate.db_product_id),
                match_source="database",
            )
            for candidate in candidates
        ],
        pagination=_normalize_pagination(page, page_size, total_items=db_hits.total_items).to_schema(),
        diagnostics=ProductSearchDiagnostics(
            backend="database",
            fallback_used=es_result.attempted or vector_result.attempted,
            es_attempted=es_result.attempted,
            es_failure_reason=es_result.failure_reason or es_result.skipped_reason,
            es_duration_ms=es_result.duration_ms,
            vector_attempted=vector_result.attempted,
            vector_failure_reason=_vector_failure_reason(vector_result),
            vector_duration_ms=vector_result.duration_ms,
            vector_result_count=vector_result.raw_hit_count,
            vector_embedding_coverage=vector_result.embedding_coverage,
        ),
    )


@dataclass(frozen=True)
class _DbSearchResult:
    page_hits: list[_DbSearchHit]
    total_items: int
    duration_ms: int


def _search_products_in_database(
    session: Session,
    *,
    query: str,
    purchase_conditions: ParsedPurchaseConditions,
    limit: int,
    offset: int,
) -> _DbSearchResult:
    started_at = perf_counter()
    terms = _query_terms(query)
    price_subquery = (
        select(
            ProductPrice.product_id.label("product_id"),
            func.min(ProductPrice.price).label("lowest_price"),
        )
        .group_by(ProductPrice.product_id)
        .subquery()
    )
    statement = (
        select(
            Product.id.label("product_db_id"),
            Product.product_code,
            Product.product_name,
            Brand.name.label("brand_name"),
            ProductCategory.name.label("category_name"),
            SearchDocument.title,
            SearchDocument.content,
            SearchDocument.keywords,
        )
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(price_subquery, price_subquery.c.product_id == Product.id)
        .outerjoin(
            SearchDocument,
            (SearchDocument.product_id == Product.id)
            & (SearchDocument.document_type == "product")
            & (SearchDocument.document_code.like(f"{DOCUMENT_CODE_PREFIX}%")),
        )
        .where(
            Product.is_active.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.is_active.is_(True),
        )
    )
    if purchase_conditions.categories:
        statement = statement.where(
            ProductCategory.category_code.in_(
                category.category_code for category in purchase_conditions.categories
            )
        )
    if purchase_conditions.brands:
        statement = statement.where(
            Brand.brand_code.in_(brand.brand_code for brand in purchase_conditions.brands)
        )
    if purchase_conditions.price_min is not None:
        statement = statement.where(price_subquery.c.lowest_price >= purchase_conditions.price_min)
    if purchase_conditions.price_max is not None:
        statement = statement.where(price_subquery.c.lowest_price <= purchase_conditions.price_max)
    if terms:
        searchable_fields = (
            Product.product_name,
            Brand.name,
            ProductCategory.name,
            SearchDocument.title,
            SearchDocument.content,
            SearchDocument.keywords,
        )
        statement = statement.where(
            or_(
                *[
                    field.ilike(f"%{term}%")
                    for term in terms
                    for field in searchable_fields
                ]
            )
        )

    rows = session.execute(statement).all()
    hits_by_product_id: dict[int, _DbSearchHit] = {}
    for row in rows:
        product_db_id = int(row.product_db_id)
        score = _score_db_row(row, terms)
        existing = hits_by_product_id.get(product_db_id)
        if existing is None or score > existing.score:
            hits_by_product_id[product_db_id] = _DbSearchHit(
                product_db_id=product_db_id,
                score=score,
            )

    hits = sorted(
        hits_by_product_id.values(),
        key=lambda hit: (-hit.score, hit.product_db_id),
    )
    return _DbSearchResult(
        page_hits=hits[offset:offset + limit],
        total_items=len(hits),
        duration_ms=int((perf_counter() - started_at) * 1000),
    )


def _should_attempt_elasticsearch(
    session: Session,
    *,
    enable_elasticsearch: bool | None,
) -> bool:
    if enable_elasticsearch is not None:
        return enable_elasticsearch
    if settings.search_backend_mode == "postgres":
        return False
    return session.get_bind().dialect.name == "postgresql"


def _search_pgvector_or_skip(
    session: Session,
    intent,
    *,
    limit: int,
    offset: int,
    enable_pgvector: bool | None,
    pgvector_search: PgvectorSearchFunc,
) -> PgvectorProductSearchResult:
    if _should_attempt_pgvector(session, enable_pgvector=enable_pgvector):
        return pgvector_search(
            session,
            intent,
            limit=limit,
            offset=offset,
        )

    return PgvectorProductSearchResult(
        product_db_ids=(),
        scores_by_product_db_id={},
        raw_hit_count=0,
        attempted=False,
        query_text=_build_vector_query_text(intent),
        provider_model=None,
        dimensions=None,
        duration_ms=0,
        skipped_reason=_pgvector_skip_reason(
            session,
            enable_pgvector=enable_pgvector,
        ),
        total_hit_count=0,
    )


def _should_attempt_pgvector(
    session: Session,
    *,
    enable_pgvector: bool | None,
) -> bool:
    if enable_pgvector is not None:
        return enable_pgvector
    return session.get_bind().dialect.name == "postgresql"


def _elasticsearch_skip_reason(
    session: Session,
    *,
    enable_elasticsearch: bool | None,
) -> str:
    if enable_elasticsearch is False:
        return "elasticsearch disabled by caller"
    if settings.search_backend_mode == "postgres":
        return "search backend mode is postgres"
    return f"elasticsearch skipped for {session.get_bind().dialect.name}"


def _pgvector_skip_reason(
    session: Session,
    *,
    enable_pgvector: bool | None,
) -> str:
    if enable_pgvector is False:
        return "pgvector disabled by caller"
    return f"pgvector skipped for {session.get_bind().dialect.name}"


def _vector_failure_reason(result: PgvectorProductSearchResult | None) -> str | None:
    if result is None or result.successful:
        return None
    return result.failure_reason or result.skipped_reason


def _build_vector_query_text(intent) -> str:
    terms = [
        intent.concern_text,
        *intent.search_terms,
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip().casefold()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(term.strip())
    return " ".join(deduped)


def _candidate_search_items(
    session: Session,
    candidates: list[ProductCandidate],
    *,
    match_source: str,
    scores_by_product_id: dict[int, float] | None = None,
) -> list[ProductSearchItem]:
    category_names = _load_category_names_by_product_id(
        session,
        [candidate.db_product_id for candidate in candidates],
    )
    return [
        _product_search_item(
            candidate,
            category_name=category_names.get(candidate.db_product_id, ""),
            search_score=(
                scores_by_product_id.get(candidate.db_product_id)
                if scores_by_product_id
                else None
            ),
            match_source=match_source,
        )
        for candidate in candidates
    ]


def _product_search_item(
    candidate: ProductCandidate,
    *,
    category_name: str,
    search_score: float | None,
    match_source: str,
) -> ProductSearchItem:
    return ProductSearchItem(
        product_id=candidate.product_id,
        brand=candidate.brand,
        name=candidate.name,
        category_code=candidate.category_code,
        category_name=category_name,
        thumbnail_url=candidate.thumbnail_url or "",
        lowest_price=candidate.lowest_price,
        search_score=search_score,
        match_source=match_source,
    )


def _load_category_names_by_product_id(
    session: Session,
    product_db_ids: list[int],
) -> dict[int, str]:
    if not product_db_ids:
        return {}
    rows = session.execute(
        select(Product.id, ProductCategory.name)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .where(Product.id.in_(product_db_ids))
    ).all()
    return {
        int(product_id): category_name
        for product_id, category_name in rows
    }


@dataclass(frozen=True)
class _Pagination:
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    def to_schema(self) -> ProductSearchPagination:
        return ProductSearchPagination(
            page=self.page,
            page_size=self.page_size,
            total_items=self.total_items,
            total_pages=self.total_pages,
            has_next=self.has_next,
            has_prev=self.has_prev,
        )


def _normalize_pagination(page: int, page_size: int, *, total_items: int) -> _Pagination:
    normalized_page = max(1, page)
    normalized_page_size = max(1, min(MAX_PRODUCT_SEARCH_PAGE_SIZE, page_size))
    total_pages = math.ceil(total_items / normalized_page_size) if total_items else 0
    return _Pagination(
        page=normalized_page,
        page_size=normalized_page_size,
        total_items=max(0, total_items),
        total_pages=total_pages,
        has_next=total_pages > 0 and normalized_page < total_pages,
        has_prev=normalized_page > 1 and total_pages > 0,
    )


def _query_terms(query: str) -> tuple[str, ...]:
    terms = [
        term
        for term in re.split(r"[\s/·,]+", query.strip().casefold())
        if len(term) >= 2
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return tuple(deduped)


def _score_db_row(row, terms: tuple[str, ...]) -> float:
    if not terms:
        return 0.0
    title_text = _normalize_text(" ".join(str(value or "") for value in (row.product_name, row.brand_name, row.category_name, row.title)))
    body_text = _normalize_text(" ".join(str(value or "") for value in (row.content, row.keywords)))
    score = 0.0
    for term in terms:
        normalized_term = _normalize_text(term)
        compact_term = normalized_term.replace(" ", "")
        if compact_term and compact_term in title_text.replace(" ", ""):
            score += 3.0
        elif compact_term and compact_term in body_text.replace(" ", ""):
            score += 1.0
    return round(score, 4)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())
