from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.session import get_db
from app.schemas.common import ApiError, ErrorResponse
from app.schemas.product_listing import (
    BrandListResponse,
    CategoryListResponse,
    ProductListingResponse,
    ProductListingSort,
)
from app.services.event_tracking import request_id_from_request
from app.services.product_listing_service import (
    DEFAULT_BRAND_LIST_PAGE_SIZE,
    DEFAULT_PRODUCT_LISTING_PAGE,
    DEFAULT_PRODUCT_LISTING_PAGE_SIZE,
    MAX_PRODUCT_LISTING_PAGE_SIZE,
    get_brands_response,
    get_categories_response,
    get_product_listing_response,
)


router = APIRouter(tags=["catalog"])


@router.get(
    "/products",
    response_model=ProductListingResponse,
    responses={400: {"model": ErrorResponse}},
)
def list_products(
    request: Request,
    page: int = Query(default=DEFAULT_PRODUCT_LISTING_PAGE, ge=1),
    page_size: int = Query(default=DEFAULT_PRODUCT_LISTING_PAGE_SIZE, ge=1, le=MAX_PRODUCT_LISTING_PAGE_SIZE),
    brand_code: list[str] | None = Query(default=None),
    category_code: list[str] | None = Query(default=None),
    category_group: list[str] | None = Query(default=None),
    min_price: int | None = Query(default=None, ge=0),
    max_price: int | None = Query(default=None, ge=0),
    min_rating: float | None = Query(default=None, ge=0, le=5),
    in_stock: bool | None = Query(default=None),
    sort: ProductListingSort = Query(default=ProductListingSort.POPULAR),
    session: Session = Depends(get_db),
) -> ProductListingResponse:
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ApiError(400, "INVALID_PRODUCT_FILTER", "최소 가격은 최대 가격보다 클 수 없습니다.")

    started_at = current_time()
    response = get_product_listing_response(
        session,
        page=page,
        page_size=page_size,
        brand_codes=brand_code or (),
        category_codes=category_code or (),
        category_groups=category_group or (),
        min_price=min_price,
        max_price=max_price,
        min_rating=min_rating,
        in_stock=in_stock,
        sort=sort,
    )
    log_performance_event(
        "product_listing_completed",
        request_id=request_id_from_request(request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "page": page,
            "page_size": page_size,
            "item_count": len(response.items),
            "total_items": response.pagination.total_items,
            "sort": response.sort.value,
            "brand_filter_count": len(response.applied_filters.brand_codes),
            "category_filter_count": len(response.applied_filters.category_codes),
            "category_group_filter_count": len(response.applied_filters.category_groups),
        },
    )
    return response


@router.get("/categories", response_model=CategoryListResponse)
def list_categories(
    request: Request,
    session: Session = Depends(get_db),
) -> CategoryListResponse:
    started_at = current_time()
    response = get_categories_response(session)
    log_performance_event(
        "catalog_categories_completed",
        request_id=request_id_from_request(request),
        duration_ms=elapsed_ms(started_at),
        metadata={"item_count": len(response.items)},
    )
    return response


@router.get("/brands", response_model=BrandListResponse)
def list_brands(
    request: Request,
    q: str | None = Query(default=None, max_length=120),
    page: int = Query(default=DEFAULT_PRODUCT_LISTING_PAGE, ge=1),
    page_size: int = Query(default=DEFAULT_BRAND_LIST_PAGE_SIZE, ge=1, le=MAX_PRODUCT_LISTING_PAGE_SIZE),
    session: Session = Depends(get_db),
) -> BrandListResponse:
    started_at = current_time()
    response = get_brands_response(session, page=page, page_size=page_size, query=q)
    log_performance_event(
        "catalog_brands_completed",
        request_id=request_id_from_request(request),
        duration_ms=elapsed_ms(started_at),
        metadata={"page": page, "page_size": page_size, "item_count": len(response.items), "has_query": bool(q)},
    )
    return response
