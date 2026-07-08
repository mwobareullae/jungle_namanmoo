import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_optional_current_user
from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.event import EventLogCreateRequest
from app.schemas.product import PopularProductsResponse, ProductDetailResponse, ProductSearchResponse
from app.services.event_tracking import (
    anonymous_user_id_from_request,
    record_event_log_best_effort,
    request_id_from_request,
    session_id_from_request,
)
from app.services.popular_products_service import (
    DEFAULT_POPULAR_LIMIT,
    DEFAULT_POPULAR_WINDOW_DAYS,
    MAX_POPULAR_LIMIT,
    get_popular_products_response,
)
from app.services.product_detail_service import get_product_detail_response
from app.services.product_search_service import (
    DEFAULT_PRODUCT_SEARCH_PAGE,
    DEFAULT_PRODUCT_SEARCH_PAGE_SIZE,
    MAX_PRODUCT_SEARCH_PAGE_SIZE,
    get_product_search_response,
)


router = APIRouter(tags=["products"])
logger = logging.getLogger(__name__)


@router.get(
    "/products/popular",
    response_model=PopularProductsResponse,
)
def get_popular_products(
    request: Request,
    window_days: int = Query(default=DEFAULT_POPULAR_WINDOW_DAYS, ge=0, le=365),
    limit: int = Query(default=DEFAULT_POPULAR_LIMIT, ge=1, le=MAX_POPULAR_LIMIT),
    category_code: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> PopularProductsResponse:
    started_at = current_time()
    response = get_popular_products_response(
        session,
        window_days=window_days,
        limit=limit,
        category_code=category_code,
    )
    log_performance_event(
        "popular_products_completed",
        request_id=request_id_from_request(request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "window_days": response.window_days,
            "requested_limit": limit,
            "item_count": len(response.items),
            "category_code": category_code,
            "top_popularity_score": response.items[0].popularity_score if response.items else None,
        },
    )
    return response


@router.get(
    "/products/search",
    response_model=ProductSearchResponse,
)
def search_products(
    q: str = Query(min_length=1, max_length=200),
    page: int = Query(DEFAULT_PRODUCT_SEARCH_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PRODUCT_SEARCH_PAGE_SIZE, ge=1, le=MAX_PRODUCT_SEARCH_PAGE_SIZE),
    session: Session = Depends(get_db),
) -> ProductSearchResponse:
    return get_product_search_response(
        session,
        query=q,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/products/{product_id}",
    response_model=ProductDetailResponse,
    responses={
        404: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
    },
)
def get_product_by_id(
    request: Request,
    product_id: str,
    recommendation_id: str | None = Query(default=None),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> ProductDetailResponse:
    started_at = current_time()
    response = get_product_detail_response(session, product_id, recommendation_id)
    _record_product_viewed_event(
        session,
        request=request,
        response=response,
        recommendation_id=recommendation_id,
        current_user=current_user,
    )
    log_performance_event(
        "product_detail_completed",
        request_id=request_id_from_request(request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "product_id": response.product.product_id,
            "has_recommendation_context": recommendation_id is not None,
            "can_purchase": response.purchase_info.can_purchase,
            "sales_status": response.purchase_info.sales_status,
            "stock_status": response.purchase_info.stock_status,
        },
    )
    return response


def _record_product_viewed_event(
    session: Session,
    *,
    request: Request,
    response: ProductDetailResponse,
    recommendation_id: str | None,
    current_user: User | None,
) -> None:
    product = response.product
    record_event_log_best_effort(
        session,
        EventLogCreateRequest(
            event_name="product_viewed",
            recommendation_id=recommendation_id,
            product_id=product.product_id,
            rank=product.cart_handoff.recommendation_rank if product.cart_handoff else None,
            source="recommendation_detail" if recommendation_id else "product_detail",
            page="product_detail",
            metadata_json={
                "has_recommendation_context": recommendation_id is not None,
                "can_purchase": response.purchase_info.can_purchase,
                "sales_status": response.purchase_info.sales_status,
                "stock_status": response.purchase_info.stock_status,
            },
        ),
        current_user=current_user,
        fallback_request_id=request_id_from_request(request),
        fallback_anonymous_user_id=anonymous_user_id_from_request(request),
        fallback_session_id=session_id_from_request(request),
        logger=logger,
        failure_message="failed_to_record_product_viewed_event",
    )
