from collections.abc import Callable

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_error_event, log_performance_event
from app.db.session import get_db
from app.schemas.admin.order import AdminOrderListResponse, AdminOrderShipmentActionResponse
from app.schemas.common import ApiError, ErrorResponse
from app.services.admin.order_service import (
    ACTION_COMPLETE_DELIVERY,
    ACTION_START_PREPARATION,
    ACTION_START_SHIPMENT,
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    ShipmentTransitionResult,
    complete_delivery,
    list_admin_orders,
    start_preparation,
    start_shipment,
)


router = APIRouter()

_SHIPMENT_ACTION_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


@router.get("/orders", response_model=AdminOrderListResponse)
def list_orders(
    order_status: str | None = Query(default=None),
    payment_status: str | None = Query(default=None),
    page: int = Query(default=DEFAULT_PAGE),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE),
    session: Session = Depends(get_db),
) -> AdminOrderListResponse:
    """관리자 주문 목록 조회. 인증/인가는 admin_router 공통 가드가 적용."""
    return list_admin_orders(
        session,
        order_status=order_status,
        payment_status=payment_status,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/orders/{order_code}/ship/prepare",
    response_model=AdminOrderShipmentActionResponse,
    responses=_SHIPMENT_ACTION_RESPONSES,
)
def post_order_ship_prepare(
    order_code: str,
    session: Session = Depends(get_db),
) -> AdminOrderShipmentActionResponse:
    """결제완료(PAID) → 배송준비중. 인증/인가는 admin_router 공통 가드가 적용."""
    return _run_shipment_transition(
        session, start_preparation, action=ACTION_START_PREPARATION, order_code=order_code
    )


@router.post(
    "/orders/{order_code}/ship/dispatch",
    response_model=AdminOrderShipmentActionResponse,
    responses=_SHIPMENT_ACTION_RESPONSES,
)
def post_order_ship_dispatch(
    order_code: str,
    session: Session = Depends(get_db),
) -> AdminOrderShipmentActionResponse:
    """배송준비중 → 배송중. 인증/인가는 admin_router 공통 가드가 적용."""
    return _run_shipment_transition(
        session, start_shipment, action=ACTION_START_SHIPMENT, order_code=order_code
    )


@router.post(
    "/orders/{order_code}/ship/deliver",
    response_model=AdminOrderShipmentActionResponse,
    responses=_SHIPMENT_ACTION_RESPONSES,
)
def post_order_ship_deliver(
    order_code: str,
    session: Session = Depends(get_db),
) -> AdminOrderShipmentActionResponse:
    """배송중 → 배송완료(최종 상태). 인증/인가는 admin_router 공통 가드가 적용."""
    return _run_shipment_transition(
        session, complete_delivery, action=ACTION_COMPLETE_DELIVERY, order_code=order_code
    )


def _run_shipment_transition(
    session: Session,
    transition_fn: Callable[..., ShipmentTransitionResult],
    *,
    action: str,
    order_code: str,
) -> AdminOrderShipmentActionResponse:
    """세 배송 라우터가 공유하는 commit/rollback/성능 로그 실행부.

    성공 로그는 commit 이 실제로 성공한 뒤에만 남긴다 — 커밋 전에 로그부터 찍으면
    롤백됐는데 로그만 성공으로 남는 불일치가 생기기 때문이다. 그래서 session.commit()
    도 try 안에 포함한다 — commit 자체가 실패(DB 연결 끊김, 제약조건 위반 등)해도
    rollback·실패 로그가 빠지면 안 되기 때문이다. 실패 시에는 rollback 한 뒤 실패 로그를
    남기고 예외를 그대로 다시 던진다(응답은 ApiError 면 FastAPI의 전용 핸들러가, 그 외
    예외면 기본 500 처리가 만든다). 로그에는 예외 메시지나 개인정보를 넣지 않는다 —
    ApiError 는 이미 정해진 error_code, 그 외 예외는 타입명(type(exc).__name__)만 남긴다.
    """
    started_at = current_time()
    try:
        result = transition_fn(session, order_code=order_code)
        session.commit()
    except ApiError as exc:
        session.rollback()
        log_performance_event(
            "admin_order_shipping_transition_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={
                "order_code": order_code,
                "action": action,
                "error_code": exc.code,
            },
        )
        raise
    except Exception as exc:
        session.rollback()
        log_error_event(
            "admin_order_shipping_transition_failed",
            started_at=started_at,
            metadata={"order_code": order_code, "action": action, "error_code": "UNEXPECTED_ERROR"},
            exc=exc,
        )
        raise

    log_performance_event(
        "admin_order_shipping_transition_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "order_code": order_code,
            "action": result.action,
            "previous_status": result.previous_status,
            "next_status": result.response.order_status,
            "updated_item_count": result.updated_item_count,
            "idempotent_replay": result.idempotent_replay,
        },
    )
    return result.response
