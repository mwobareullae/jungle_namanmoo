from fastapi import APIRouter

from app.schemas.admin.ping import AdminPingResponse


router = APIRouter()


@router.get("/ping", response_model=AdminPingResponse)
def admin_ping() -> AdminPingResponse:
    """관리자 모듈 연결 확인용 엔드포인트. (인증은 통합 라우터에서 적용)"""
    return AdminPingResponse(status="ok", scope="admin")
