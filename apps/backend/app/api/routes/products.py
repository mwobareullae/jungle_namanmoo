from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.product import PopularProductsResponse, ProductDetailResponse
from app.services.popular_products_service import (
    DEFAULT_POPULAR_LIMIT,
    DEFAULT_POPULAR_WINDOW_DAYS,
    MAX_POPULAR_LIMIT,
    get_popular_products_response,
)
from app.services.product_detail_service import get_product_detail_response


router = APIRouter(tags=["products"])


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
    product_id: str,
    recommendation_id: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> ProductDetailResponse:
    return get_product_detail_response(session, product_id, recommendation_id)
