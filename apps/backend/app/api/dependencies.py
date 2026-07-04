from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.session import get_db
from app.services.auth_service import AuthServiceError, get_user_from_access_token


def get_current_user(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_db),
) -> User:
    token = extract_bearer_token(authorization)
    return get_user_from_access_token(session, token)


def get_optional_current_user(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_db),
) -> User | None:
    if not authorization:
        return None
    token = extract_bearer_token(authorization)
    return get_user_from_access_token(session, token)


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthServiceError(401, "INVALID_TOKEN", "인증 정보가 올바르지 않습니다.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthServiceError(401, "INVALID_TOKEN", "인증 정보가 올바르지 않습니다.")
    return token
