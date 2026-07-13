import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.session import get_db
from app.schemas.admin.order_cancel_request import (
    AdminCancelRequestRejectBody,
    AdminOrderCancelRequestActionResponse,
    AdminOrderCancelRequestDetailResponse,
    AdminOrderCancelRequestListResponse,
)
from app.schemas.common import ApiError, ErrorResponse
from app.services.admin.order_cancel_request_service import (
    DEFAULT_LIMIT,
    approve_admin_cancel_request,
    get_admin_cancel_request,
    list_admin_cancel_requests,
    reject_admin_cancel_request,
)


router = APIRouter()

_DETAIL_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}

_ACTION_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


@router.get("/order-cancel-requests", response_model=AdminOrderCancelRequestListResponse)
def list_order_cancel_requests(
    status: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT),
    cursor: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> AdminOrderCancelRequestListResponse:
    """관리자 취소 요청 목록 조회. 인증/인가는 admin_router 공통 가드가 적용."""
    return list_admin_cancel_requests(session, status=status, limit=limit, cursor=cursor)


@router.get(
    "/order-cancel-requests/{request_code}",
    response_model=AdminOrderCancelRequestDetailResponse,
    responses=_DETAIL_RESPONSES,
)
def get_order_cancel_request(
    request_code: str,
    session: Session = Depends(get_db),
) -> AdminOrderCancelRequestDetailResponse:
    """관리자 취소 요청 상세 조회. 인증/인가는 admin_router 공통 가드가 적용."""
    return get_admin_cancel_request(session, request_code)


@router.post(
    "/order-cancel-requests/{request_code}/approve",
    response_model=AdminOrderCancelRequestActionResponse,
    responses=_ACTION_RESPONSES,
)
def post_order_cancel_request_approve(
    request_code: str,
    session: Session = Depends(get_db),
) -> AdminOrderCancelRequestActionResponse:
    """취소 요청 승인 — cancel_paid_order() 재사용. 인증/인가는 admin_router 공통 가드가 적용."""
    return _run_cancel_request_decision(
        session, lambda: approve_admin_cancel_request(session, request_code), action="APPROVE", request_code=request_code
    )


@router.post(
    "/order-cancel-requests/{request_code}/reject",
    response_model=AdminOrderCancelRequestActionResponse,
    responses=_ACTION_RESPONSES,
)
def post_order_cancel_request_reject(
    request_code: str,
    body: AdminCancelRequestRejectBody,
    session: Session = Depends(get_db),
) -> AdminOrderCancelRequestActionResponse:
    """취소 요청 거절 — 사유 필수, Order 를 PAID 로 복구. 인증/인가는 admin_router 공통 가드가 적용."""
    return _run_cancel_request_decision(
        session,
        lambda: reject_admin_cancel_request(session, request_code, rejection_reason=body.rejection_reason),
        action="REJECT",
        request_code=request_code,
    )


def _run_cancel_request_decision(
    session: Session,
    decision_fn: Callable[[], AdminOrderCancelRequestActionResponse],
    *,
    action: str,
    request_code: str,
) -> AdminOrderCancelRequestActionResponse:
    """승인·거절 공통 commit/rollback/성능 로그 실행부. 배송 전이 라우터와 동일한 패턴.

    성공 로그는 commit 이 실제로 성공한 뒤에만 남긴다 — commit 도 try 안에 포함해 commit
    자체가 실패해도 rollback·실패 로그가 빠지지 않게 한다.
    """
    started_at = current_time()
    try:
        response = decision_fn()
        session.commit()
    except ApiError as exc:
        session.rollback()
        log_performance_event(
            "admin_cancel_request_decision_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={"request_code": request_code, "action": action, "error_code": exc.code},
        )
        raise
    except Exception as exc:
        session.rollback()
        log_performance_event(
            "admin_cancel_request_decision_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={
                "request_code": request_code,
                "action": action,
                "error_code": "UNEXPECTED_ERROR",
                "error_type": type(exc).__name__,
            },
            level=logging.ERROR,
        )
        raise

    log_performance_event(
        "admin_cancel_request_decision_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "request_code": request_code,
            "action": action,
            "order_code": response.order_code,
            "order_status": response.order_status,
        },
    )
    return response
