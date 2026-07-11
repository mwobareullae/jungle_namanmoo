from fastapi import Cookie, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ApiError
from app.services.auth_service import AuthServiceError, get_user_from_session_token


def get_current_user(
    request: Request,
    session_token: str | None = Cookie(default=None, alias=settings.auth_session_cookie_name),
    session: Session = Depends(get_db),
) -> User:
    user = get_user_from_session_token(session, session_token)
    request.state.user_id = user.id
    return user


def get_optional_current_user(
    request: Request,
    session_token: str | None = Cookie(default=None, alias=settings.auth_session_cookie_name),
    session: Session = Depends(get_db),
) -> User | None:
    if not session_token:
        return None
    try:
        user = get_user_from_session_token(session, session_token)
        request.state.user_id = user.id
        return user
    except AuthServiceError:
        return None


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "ADMIN":
        raise ApiError(403, "ADMIN_REQUIRED", "관리자 권한이 필요합니다.")
    return current_user
