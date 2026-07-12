from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.admin.order import AdminOrderListResponse
from app.services.admin.order_service import DEFAULT_LIMIT, list_admin_orders


router = APIRouter()


@router.get("/orders", response_model=AdminOrderListResponse)
def list_orders(
    order_status: str | None = Query(default=None),
    payment_status: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT),
    cursor: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> AdminOrderListResponse:
    """관리자 주문 목록 조회. 인증/인가는 admin_router 공통 가드가 적용."""
    return list_admin_orders(
        session,
        order_status=order_status,
        payment_status=payment_status,
        limit=limit,
        cursor=cursor,
    )
