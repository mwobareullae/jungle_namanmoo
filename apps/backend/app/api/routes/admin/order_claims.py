import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.session import get_db
from app.schemas.admin.order_claim import (
    AdminClaimCompleteBody,
    AdminClaimRejectBody,
    AdminOrderClaimActionResponse,
    AdminOrderClaimDetailResponse,
    AdminOrderClaimListResponse,
)
from app.schemas.common import ApiError, ErrorResponse
from app.services.admin.order_claim_service import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    approve_admin_claim,
    complete_admin_claim,
    get_admin_claim,
    list_admin_claims,
    reject_admin_claim,
    start_admin_claim,
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


@router.get("/order-claims", response_model=AdminOrderClaimListResponse)
def list_order_claims(
    status: str | None = Query(default=None),
    claim_type: str | None = Query(default=None),
    page: int = Query(default=DEFAULT_PAGE),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE),
    session: Session = Depends(get_db),
) -> AdminOrderClaimListResponse:
    """관리자 클레임 목록 조회. 인증/인가는 admin_router 공통 가드가 적용."""
    return list_admin_claims(session, status=status, claim_type=claim_type, page=page, page_size=page_size)


@router.get(
    "/order-claims/{claim_code}",
    response_model=AdminOrderClaimDetailResponse,
    responses=_DETAIL_RESPONSES,
)
def get_order_claim(
    claim_code: str,
    session: Session = Depends(get_db),
) -> AdminOrderClaimDetailResponse:
    """관리자 클레임 상세 조회. 인증/인가는 admin_router 공통 가드가 적용."""
    return get_admin_claim(session, claim_code)


@router.post(
    "/order-claims/{claim_code}/approve",
    response_model=AdminOrderClaimActionResponse,
    responses=_ACTION_RESPONSES,
)
def post_order_claim_approve(
    claim_code: str,
    session: Session = Depends(get_db),
) -> AdminOrderClaimActionResponse:
    """클레임 승인 — REQUESTED→APPROVED. 인증/인가는 admin_router 공통 가드가 적용."""
    return _run_claim_decision(
        session, lambda: approve_admin_claim(session, claim_code), action="APPROVE", claim_code=claim_code
    )


@router.post(
    "/order-claims/{claim_code}/reject",
    response_model=AdminOrderClaimActionResponse,
    responses=_ACTION_RESPONSES,
)
def post_order_claim_reject(
    claim_code: str,
    body: AdminClaimRejectBody,
    session: Session = Depends(get_db),
) -> AdminOrderClaimActionResponse:
    """클레임 거절 — 사유 필수, REQUESTED→REJECTED. 인증/인가는 admin_router 공통 가드가 적용."""
    return _run_claim_decision(
        session,
        lambda: reject_admin_claim(session, claim_code, rejection_reason=body.rejection_reason),
        action="REJECT",
        claim_code=claim_code,
    )


@router.post(
    "/order-claims/{claim_code}/start",
    response_model=AdminOrderClaimActionResponse,
    responses=_ACTION_RESPONSES,
)
def post_order_claim_start(
    claim_code: str,
    session: Session = Depends(get_db),
) -> AdminOrderClaimActionResponse:
    """클레임 처리 시작 — APPROVED→IN_PROGRESS. 인증/인가는 admin_router 공통 가드가 적용."""
    return _run_claim_decision(
        session, lambda: start_admin_claim(session, claim_code), action="START", claim_code=claim_code
    )


@router.post(
    "/order-claims/{claim_code}/complete",
    response_model=AdminOrderClaimActionResponse,
    responses=_ACTION_RESPONSES,
)
def post_order_claim_complete(
    claim_code: str,
    body: AdminClaimCompleteBody,
    session: Session = Depends(get_db),
) -> AdminOrderClaimActionResponse:
    """클레임 완료 — IN_PROGRESS→COMPLETED. REFUND/RETURN 은 MOCK 환불·재고 복구,

    EXCHANGE 는 상태만 완료 처리. 인증/인가는 admin_router 공통 가드가 적용.
    """
    return _run_claim_decision(
        session,
        lambda: complete_admin_claim(session, claim_code, restock=body.restock),
        action="COMPLETE",
        claim_code=claim_code,
    )


def _run_claim_decision(
    session: Session,
    decision_fn: Callable[[], AdminOrderClaimActionResponse],
    *,
    action: str,
    claim_code: str,
) -> AdminOrderClaimActionResponse:
    """승인·거절 공통 commit/rollback/성능 로그 실행부. 취소 요청 결정 라우터와 동일한 패턴."""
    started_at = current_time()
    try:
        response = decision_fn()
        session.commit()
    except ApiError as exc:
        session.rollback()
        log_performance_event(
            "admin_claim_decision_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={"claim_code": claim_code, "action": action, "error_code": exc.code},
        )
        raise
    except Exception as exc:
        session.rollback()
        log_performance_event(
            "admin_claim_decision_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={
                "claim_code": claim_code,
                "action": action,
                "error_code": "UNEXPECTED_ERROR",
                "error_type": type(exc).__name__,
            },
            level=logging.ERROR,
        )
        raise

    log_performance_event(
        "admin_claim_decision_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "claim_code": claim_code,
            "action": action,
            "order_code": response.order_code,
            "status": response.status,
        },
    )
    return response
