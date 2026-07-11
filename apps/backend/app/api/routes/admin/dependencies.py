from fastapi import Depends

from app.api.dependencies import get_current_user
from app.db.models.auth import User
from app.schemas.common import ApiError


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """현재 세션 사용자가 관리자 역할인지 확인한다."""
    if current_user.role != "ADMIN":
        raise ApiError(403, "ADMIN_REQUIRED", "관리자 권한이 필요합니다.")
    return current_user
