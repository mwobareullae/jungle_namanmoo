from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.session import get_db
from app.schemas.catalog_search import (
    CatalogSearchResponse,
    CatalogSearchSort,
    CatalogSuggestionsResponse,
)
from app.schemas.common import ErrorResponse
from app.services.catalog_search_service import (
    DEFAULT_CATALOG_SEARCH_PAGE,
    DEFAULT_CATALOG_SEARCH_PAGE_SIZE,
    MAX_CATALOG_SEARCH_PAGE_SIZE,
    get_catalog_search_response,
)
from app.services.event_tracking import request_id_from_request
from app.services.catalog_suggestion_service import (
    DEFAULT_CATALOG_SUGGESTION_LIMIT,
    MAX_CATALOG_SUGGESTION_LIMIT,
    get_catalog_suggestions_response,
)


router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "/products",
    response_model=CatalogSearchResponse,
    responses={
        400: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def search_catalog_products(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    page: int = Query(DEFAULT_CATALOG_SEARCH_PAGE, ge=1),
    page_size: int = Query(DEFAULT_CATALOG_SEARCH_PAGE_SIZE, ge=1, le=MAX_CATALOG_SEARCH_PAGE_SIZE),
    brand: list[str] | None = Query(default=None),
    category: list[str] | None = Query(default=None),
    feature: list[str] | None = Query(default=None),
    skin_type: list[str] | None = Query(default=None),
    min_price: int | None = Query(default=None, ge=0),
    max_price: int | None = Query(default=None, ge=0),
    min_rating: float | None = Query(default=None, ge=0, le=5),
    in_stock: bool | None = Query(default=None),
    sort: CatalogSearchSort = Query(default=CatalogSearchSort.RELEVANCE),
    session: Session = Depends(get_db),
) -> CatalogSearchResponse:
    started_at = current_time()
    execution = get_catalog_search_response(
        session,
        query=q,
        page=page,
        page_size=page_size,
        brands=brand or (),
        categories=category or (),
        features=feature or (),
        skin_types=skin_type or (),
        min_price=min_price,
        max_price=max_price,
        min_rating=min_rating,
        in_stock=in_stock,
        sort=sort,
        sort_is_explicit="sort" in request.query_params,
    )
    response = execution.response
    log_performance_event(
        "catalog_search_completed",
        request_id=request_id_from_request(request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "query_length": len(q),
            "page": page,
            "page_size": page_size,
            "result_count": len(response.items),
            "total_items": response.pagination.total_items,
            "sort": response.sort.value,
            "backend": execution.backend,
            "elasticsearch_attempted": execution.elasticsearch_attempted,
            "elasticsearch_duration_ms": execution.elasticsearch_duration_ms,
            "fallback_used": execution.fallback_used,
            "recovery_used": execution.recovery_used,
            "choseong_used": execution.choseong_used,
            "keyboard_conversion_used": execution.keyboard_conversion_used,
        },
    )
    return response


@router.get(
    "/suggestions",
    response_model=CatalogSuggestionsResponse,
    responses={503: {"model": ErrorResponse}},
)
def get_catalog_search_suggestions(
    request: Request,
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(DEFAULT_CATALOG_SUGGESTION_LIMIT, ge=1, le=MAX_CATALOG_SUGGESTION_LIMIT),
    session: Session = Depends(get_db),
) -> CatalogSuggestionsResponse:
    started_at = current_time()
    execution = get_catalog_suggestions_response(
        session,
        query=q,
        limit=limit,
    )
    response = execution.response
    log_performance_event(
        "catalog_search_suggestions_completed",
        request_id=request_id_from_request(request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "query_length": len(q),
            "requested_limit": limit,
            "result_count": len(response.items),
            "backend": execution.backend,
            "elasticsearch_attempted": execution.elasticsearch_attempted,
            "elasticsearch_duration_ms": execution.elasticsearch_duration_ms,
            "fallback_used": execution.fallback_used,
            "correction_suggested": execution.correction_suggested,
            "choseong_used": execution.choseong_used,
        },
    )
    return response
