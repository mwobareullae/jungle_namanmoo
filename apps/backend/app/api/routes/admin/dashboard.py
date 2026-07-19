"""관리자 운영 대시보드 집계 라우트 (P1-M5, 조회 전용)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.admin.dashboard import AdminDashboardSummaryResponse
from app.services.admin.dashboard_service import get_admin_dashboard_summary


router = APIRouter()


@router.get("/dashboard/summary", response_model=AdminDashboardSummaryResponse)
def get_dashboard_summary(session: Session = Depends(get_db)) -> AdminDashboardSummaryResponse:
    """현재 주문·검수·상품·이미지·재고 운영 현황을 반환한다."""

    return get_admin_dashboard_summary(session)
