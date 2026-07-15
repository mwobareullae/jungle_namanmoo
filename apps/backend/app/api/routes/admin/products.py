import logging

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.session import get_db
from app.schemas.admin.product import (
    AdminProductCreateRequest,
    AdminProductDetail,
    AdminProductListResponse,
    AdminProductMasterOptionListResponse,
    AdminProductUpdateRequest,
)
from app.schemas.common import ErrorResponse
from app.services.admin.product_service import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    get_admin_product_detail,
    list_active_product_brands,
    list_active_product_categories,
    list_admin_products,
)
from app.services.admin.product_mutation_service import create_admin_product, update_admin_product
from app.services.elasticsearch_catalog_index import (
    ElasticsearchCatalogIndexError,
    reindex_catalog_product_to_elasticsearch,
)


router = APIRouter()
logger = logging.getLogger(__name__)


def _sync_catalog_product_after_commit(session: Session, product_code: str) -> None:
    """DB 커밋 이후 상품 1건을 ES에 best-effort로 동기화한다."""

    started_at = current_time()
    try:
        result = reindex_catalog_product_to_elasticsearch(
            session,
            product_id=product_code,
        )
    except ElasticsearchCatalogIndexError as exc:
        log_performance_event(
            "admin_product_catalog_sync_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={
                "product_id": product_code,
                "error": type(exc).__name__,
            },
        )
        logger.warning(
            "admin product catalog sync failed",
            extra={"product_id": product_code, "error_type": type(exc).__name__},
        )
        return

    log_performance_event(
        "admin_product_catalog_sync_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "product_id": product_code,
            "action": result.action,
        },
    )


@router.get("/product-brands", response_model=AdminProductMasterOptionListResponse)
def list_product_brands(session: Session = Depends(get_db)) -> AdminProductMasterOptionListResponse:
    """관리자 상품 폼에서 선택할 활성 브랜드 master를 반환한다."""

    return list_active_product_brands(session)


@router.get("/product-categories", response_model=AdminProductMasterOptionListResponse)
def list_product_categories(session: Session = Depends(get_db)) -> AdminProductMasterOptionListResponse:
    """관리자 상품 폼에서 선택할 활성 카테고리 master를 반환한다."""

    return list_active_product_categories(session)


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
    except Exception:
        session.rollback()
        raise
    _sync_catalog_product_after_commit(session, result.product_code)
    return result


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
    except Exception:
        session.rollback()
        raise
    _sync_catalog_product_after_commit(session, result.product_code)
    return result
