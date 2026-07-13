from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.admin.order_cancel_request import (
    AdminOrderCancelRequestDetailResponse,
    AdminOrderCancelRequestListResponse,
)
from app.schemas.common import ErrorResponse
from app.services.admin.order_cancel_request_service import (
    DEFAULT_LIMIT,
    get_admin_cancel_request,
    list_admin_cancel_requests,
)


router = APIRouter()

_DETAIL_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
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
