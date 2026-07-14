from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.admin.product import (
    AdminProductCreateRequest,
    AdminProductDetail,
    AdminProductListResponse,
    AdminProductUpdateRequest,
)
from app.schemas.common import ErrorResponse
from app.services.admin.product_service import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    get_admin_product_detail,
    list_admin_products,
)
from app.services.admin.product_mutation_service import create_admin_product, update_admin_product


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


@router.post(
    "/products",
    response_model=AdminProductDetail,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_product(
    body: AdminProductCreateRequest,
    session: Session = Depends(get_db),
) -> AdminProductDetail:
    """자사 상품과 HIDDEN/0 기본 재고·자사몰 가격을 한 트랜잭션으로 등록한다."""

    try:
        result = create_admin_product(session, body)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


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


@router.patch(
    "/products/{product_code}",
    response_model=AdminProductDetail,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def update_product(
    product_code: str,
    body: AdminProductUpdateRequest,
    session: Session = Depends(get_db),
) -> AdminProductDetail:
    """상품 기본정보·가격·노출 여부를 부분 수정한다."""

    try:
        result = update_admin_product(session, product_code, body)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
