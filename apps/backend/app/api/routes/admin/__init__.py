"""관리자(admin) 통합 라우터.

모든 관리자 하위 라우터를 여기 include 하고, main.py 는 `admin_router` 하나만
등록한다. 관리자 전용 인증 가드도 여기서 공통 적용한다.
  - prefix: /admin  (최종 URL 예: /api/admin/ping)
  - 인증/인가: require_admin 공통 의존성
"""

from fastapi import APIRouter, Depends

from app.api.routes.admin import ping
from app.api.routes.admin.dependencies import require_admin


admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

admin_router.include_router(ping.router)
