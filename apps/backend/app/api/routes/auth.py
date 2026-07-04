from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.auth import (
    AvailabilityResponse,
    AuthUser,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
)
from app.services.auth_service import (
    AuthServiceError,
    PASSWORD_RESET_RESPONSE_MESSAGE,
    confirm_password_reset,
    get_user_from_access_token,
    is_email_available,
    is_nickname_available,
    login,
    logout,
    refresh,
    request_password_reset,
    signup,
)


router = APIRouter(tags=["auth"])


@router.get("/auth/check-email", response_model=AvailabilityResponse)
def check_email(
    email: str = Query(...),
    session: Session = Depends(get_db),
) -> AvailabilityResponse | JSONResponse:
    try:
        available = is_email_available(session, email)
    except AuthServiceError as exc:
        return _auth_error(exc)
    if not available:
        return _auth_error(
            AuthServiceError(409, "EMAIL_ALREADY_EXISTS", "이미 가입된 이메일입니다."),
            available=False,
        )
    return AvailabilityResponse(available=True, message="사용 가능한 이메일입니다.")


@router.get("/auth/check-nickname", response_model=AvailabilityResponse)
def check_nickname(
    nickname: str = Query(...),
    session: Session = Depends(get_db),
) -> AvailabilityResponse | JSONResponse:
    try:
        available = is_nickname_available(session, nickname)
    except AuthServiceError as exc:
        return _auth_error(exc)
    if not available:
        return _auth_error(
            AuthServiceError(409, "NICKNAME_ALREADY_EXISTS", "이미 사용 중인 닉네임입니다."),
            available=False,
        )
    return AvailabilityResponse(available=True, message="사용 가능한 닉네임입니다.")


@router.post("/auth/signup", response_model=TokenResponse)
def post_signup(
    request: SignupRequest,
    session: Session = Depends(get_db),
) -> TokenResponse | JSONResponse:
    try:
        response = signup(session, request)
        session.commit()
        return response
    except AuthServiceError as exc:
        session.rollback()
        return _auth_error(exc)


@router.post("/auth/login", response_model=TokenResponse)
def post_login(
    request: LoginRequest,
    session: Session = Depends(get_db),
) -> TokenResponse | JSONResponse:
    try:
        response = login(session, request.email, request.password)
        session.commit()
        return response
    except AuthServiceError as exc:
        session.rollback()
        return _auth_error(exc)


@router.post("/auth/refresh", response_model=TokenResponse)
def post_refresh(
    request: RefreshRequest,
    session: Session = Depends(get_db),
) -> TokenResponse | JSONResponse:
    try:
        response = refresh(session, request.refresh_token)
        session.commit()
        return response
    except AuthServiceError as exc:
        session.rollback()
        return _auth_error(exc)


@router.post("/auth/logout", response_model=MessageResponse)
def post_logout(
    request: LogoutRequest,
    session: Session = Depends(get_db),
) -> MessageResponse:
    logout(session, request.refresh_token)
    session.commit()
    return MessageResponse(message="로그아웃되었습니다.")


@router.post("/auth/password-reset", response_model=MessageResponse)
def post_password_reset(
    request: PasswordResetRequest,
    session: Session = Depends(get_db),
) -> MessageResponse:
    request_password_reset(session, request.email)
    session.commit()
    return MessageResponse(message=PASSWORD_RESET_RESPONSE_MESSAGE)


@router.post("/auth/password-reset/confirm", response_model=MessageResponse)
def post_password_reset_confirm(
    request: PasswordResetConfirmRequest,
    session: Session = Depends(get_db),
) -> MessageResponse | JSONResponse:
    try:
        confirm_password_reset(
            session,
            email=request.email,
            code=request.code,
            new_password=request.new_password,
        )
        session.commit()
        return MessageResponse(message="비밀번호가 변경되었습니다.")
    except AuthServiceError as exc:
        if exc.code in {"INVALID_RESET_CODE", "RESET_CODE_LOCKED"}:
            session.commit()
        else:
            session.rollback()
        return _auth_error(exc)


@router.get("/me", response_model=AuthUser)
def get_me(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_db),
) -> AuthUser | JSONResponse:
    try:
        token = _extract_bearer_token(authorization)
        user = get_user_from_access_token(session, token)
        return AuthUser(
            id=user.id,
            email=user.email,
            nickname=user.display_name,
            role=user.role,
            status=user.status,
            created_at=user.created_at,
        )
    except AuthServiceError as exc:
        return _auth_error(exc)


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthServiceError(401, "INVALID_TOKEN", "인증 정보가 올바르지 않습니다.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthServiceError(401, "INVALID_TOKEN", "인증 정보가 올바르지 않습니다.")
    return token


def _auth_error(error: AuthServiceError, *, available: bool | None = None) -> JSONResponse:
    content = {
        "code": error.code,
        "message": error.message,
        "error": {
            "code": error.code,
            "message": error.message,
        },
    }
    if available is not None:
        content["available"] = available
    return JSONResponse(status_code=error.status_code, content=content)
