"""관리자 재고·가격 조회 라우트 (P1-M4, Chunk 1)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_error_event, log_performance_event
from app.db.session import get_db
from app.schemas.admin.inventory_price import (
    AdminInventoryAdjustmentRequest,
    AdminInventoryAdjustmentResponse,
    AdminInventoryHistoryResponse,
    AdminInventoryPriceListResponse,
    AdminInventoryPriceUpdateRequest,
    AdminInventoryPriceUpdateResponse,
    AdminProductSaleStartResponse,
)
from app.schemas.common import ApiError, ErrorResponse
from app.services.catalog_sync import sync_catalog_product_after_commit
from app.services.admin.inventory_price_service import (
    DEFAULT_LIMIT,
    adjust_admin_inventory,
    get_admin_inventory_history,
    list_admin_inventory_prices,
    start_admin_product_sale,
    update_admin_inventory_price,
)


router = APIRouter()


@router.get(
    "/inventory",
    response_model=AdminInventoryPriceListResponse,
    responses={400: {"model": ErrorResponse}},
)
def list_inventory_prices(
    q: str | None = Query(default=None, description="상품명 부분 검색"),
    sales_status: str | None = Query(default=None, description="ON_SALE/SOLD_OUT/HIDDEN"),
    stock_status: str | None = Query(default=None, description="IN_STOCK/LOW_STOCK/SOLD_OUT/HIDDEN"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=100),
    cursor: str | None = Query(default=None, description="서버 발급 opaque cursor. 프론트 해석 금지"),
    session: Session = Depends(get_db),
) -> AdminInventoryPriceListResponse:
    """재고·가격 운영 목록을 반환한다. 관리자 공통 인증 가드가 적용된다."""

    return list_admin_inventory_prices(
        session,
        query=q,
        sales_status=sales_status,
        stock_status=stock_status,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/inventory/{product_code}/history",
    response_model=AdminInventoryHistoryResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_inventory_history(
    product_code: str,
    session: Session = Depends(get_db),
) -> AdminInventoryHistoryResponse:
    """선택 상품의 실제 InventoryMovement 최근 20건을 반환한다."""

    return get_admin_inventory_history(session, product_code=product_code)


@router.patch(
    "/inventory/{product_code}",
    response_model=AdminInventoryAdjustmentResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def adjust_inventory(
    product_code: str,
    body: AdminInventoryAdjustmentRequest,
    session: Session = Depends(get_db),
) -> AdminInventoryAdjustmentResponse:
    """절대 재고 수량을 조정하고 실제 변경 때만 이력·재색인을 수행한다."""

    started_at = current_time()
    try:
        response = adjust_admin_inventory(
            session,
            product_code=product_code,
            stock_quantity=body.stock_quantity,
            reason=body.reason,
        )
        session.commit()
    except ApiError as exc:
        session.rollback()
        log_performance_event(
            "admin_inventory_adjustment_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={"product_code": product_code, "error_code": exc.code},
        )
        raise
    except Exception as exc:
        session.rollback()
        log_error_event(
            "admin_inventory_adjustment_failed",
            started_at=started_at,
            metadata={"product_code": product_code, "error_code": "UNEXPECTED_ERROR"},
            exc=exc,
        )
        raise

    if response.changed and response.availability.sales_status != "HIDDEN":
        sync_catalog_product_after_commit(session, response.product_code, event_prefix="admin_inventory")

    log_performance_event(
        "admin_inventory_adjustment_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "product_code": response.product_code,
            "changed": response.changed,
            "sales_status": response.availability.sales_status,
        },
    )
    return response


@router.patch(
    "/inventory/{product_code}/price",
    response_model=AdminInventoryPriceUpdateResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def update_inventory_price(
    product_code: str,
    body: AdminInventoryPriceUpdateRequest,
    session: Session = Depends(get_db),
) -> AdminInventoryPriceUpdateResponse:
    """자사 운영몰 가격을 갱신하고 판매 중 상품만 커밋 후 재색인한다."""

    started_at = current_time()
    try:
        outcome = update_admin_inventory_price(session, product_code=product_code, price=body.price)
        session.commit()
    except ApiError as exc:
        session.rollback()
        log_performance_event(
            "admin_inventory_price_update_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={"product_code": product_code, "error_code": exc.code},
        )
        raise
    except Exception as exc:
        session.rollback()
        log_error_event(
            "admin_inventory_price_update_failed",
            started_at=started_at,
            metadata={"product_code": product_code, "error_code": "UNEXPECTED_ERROR"},
            exc=exc,
        )
        raise

    if outcome.requires_catalog_sync:
        sync_catalog_product_after_commit(session, outcome.response.product_code, event_prefix="admin_inventory")

    log_performance_event(
        "admin_inventory_price_update_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "product_code": outcome.response.product_code,
            "changed": outcome.response.changed,
            "catalog_sync": outcome.requires_catalog_sync,
        },
    )
    return outcome.response


@router.post(
    "/inventory/{product_code}/sale-start",
    response_model=AdminProductSaleStartResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def start_product_sale(
    product_code: str,
    session: Session = Depends(get_db),
) -> AdminProductSaleStartResponse:
    """HIDDEN 상품의 가격·재고·분류 준비 상태를 확인한 뒤 판매를 시작한다."""

    started_at = current_time()
    try:
        response = start_admin_product_sale(session, product_code=product_code)
        session.commit()
    except ApiError as exc:
        session.rollback()
        log_performance_event(
            "admin_product_sale_start_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={"product_code": product_code, "error_code": exc.code},
        )
        raise
    except Exception as exc:
        session.rollback()
        log_error_event(
            "admin_product_sale_start_failed",
            started_at=started_at,
            metadata={"product_code": product_code, "error_code": "UNEXPECTED_ERROR"},
            exc=exc,
        )
        raise

    sync_catalog_product_after_commit(session, response.product_code, event_prefix="admin_inventory")
    log_performance_event(
        "admin_product_sale_start_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={"product_code": response.product_code, "sales_status": response.sales_status},
    )
    return response
