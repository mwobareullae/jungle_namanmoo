from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.admin.product import AdminProductDetail, AdminProductListResponse
from app.schemas.common import ErrorResponse
from app.services.admin.product_service import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    get_admin_product_detail,
    list_admin_products,
)


router = APIRouter()


@router.get("/products", response_model=AdminProductListResponse)
def list_products(
    q: str | None = Query(default=None, description="상품명 부분 검색"),
    brand_code: str | None = Query(default=None),
    category_code: str | None = Query(default=None),
    is_active: bool | None = Query(default=None, description="노출 여부 필터. 미지정 시 전체(비활성 포함)"),
    sales_status: str | None = Query(
        default=None, description="ON_SALE/SOLD_OUT/HIDDEN/UNKNOWN(재고 행 없는 상품). 잘못된 값은 400."
    ),
    page: int = Query(default=DEFAULT_PAGE, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    session: Session = Depends(get_db),
) -> AdminProductListResponse:
    """관리자 상품 목록 조회(조회 전용). 고객 목록과 달리 비활성·숨김 상품도 포함한다.

    인증/인가는 admin_router 공통 가드가 적용.
    """
    return list_admin_products(
        session,
        query=q,
        brand_code=brand_code,
        category_code=category_code,
        is_active=is_active,
        sales_status=sales_status,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/products/{product_code}",
    response_model=AdminProductDetail,
    responses={404: {"model": ErrorResponse}},
)
def get_product(
    product_code: str,
    session: Session = Depends(get_db),
) -> AdminProductDetail:
    """관리자 상품 상세 조회(조회 전용). 인증/인가는 admin_router 공통 가드가 적용."""
    return get_admin_product_detail(session, product_code)
