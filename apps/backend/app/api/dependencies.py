from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.auth import User
from app.db.session import get_db
from app.services.auth_service import AuthServiceError, get_user_from_session_token


def get_current_user(
    session_token: str | None = Cookie(default=None, alias=settings.auth_session_cookie_name),
    session: Session = Depends(get_db),
) -> User:
    return get_user_from_session_token(session, session_token)


def get_optional_current_user(
    session_token: str | None = Cookie(default=None, alias=settings.auth_session_cookie_name),
    session: Session = Depends(get_db),
) -> User | None:
    if not session_token:
        return None
    try:
        return get_user_from_session_token(session, session_token)
    except AuthServiceError:
        return None
