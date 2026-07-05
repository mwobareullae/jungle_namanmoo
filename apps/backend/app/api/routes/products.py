import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_optional_current_user
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.event import EventLogCreateRequest
from app.schemas.product import PopularProductsResponse, ProductDetailResponse
from app.services.event_tracking import record_event_log_best_effort
from app.services.popular_products_service import (
    DEFAULT_POPULAR_LIMIT,
    DEFAULT_POPULAR_WINDOW_DAYS,
    MAX_POPULAR_LIMIT,
    get_popular_products_response,
)
from app.services.product_detail_service import get_product_detail_response


router = APIRouter(tags=["products"])
logger = logging.getLogger(__name__)


@router.get(
    "/products/popular",
    response_model=PopularProductsResponse,
)
def get_popular_products(
    window_days: int = Query(default=DEFAULT_POPULAR_WINDOW_DAYS, ge=0, le=365),
    limit: int = Query(default=DEFAULT_POPULAR_LIMIT, ge=1, le=MAX_POPULAR_LIMIT),
    category_code: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> PopularProductsResponse:
    return get_popular_products_response(
        session,
        window_days=window_days,
        limit=limit,
        category_code=category_code,
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
    response = get_product_detail_response(session, product_id, recommendation_id)
    _record_product_viewed_event(
        session,
        request=request,
        response=response,
        recommendation_id=recommendation_id,
        current_user=current_user,
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
        fallback_request_id=request.headers.get("x-request-id"),
        logger=logger,
        failure_message="failed_to_record_product_viewed_event",
    )
