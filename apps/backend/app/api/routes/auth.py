from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.auth import (
    AuthSessionResponse,
    AuthUser,
    AvailabilityResponse,
    GoogleLoginRequest,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    SignupRequest,
)
from app.services.account_deletion_service import delete_user_account
from app.services.auth_service import (
    AuthServiceError,
    IssuedAuthSession,
    PASSWORD_RESET_RESPONSE_MESSAGE,
    confirm_password_reset,
    is_email_available,
    is_nickname_available,
    login,
    login_with_google,
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


@router.post("/auth/signup", response_model=AuthSessionResponse)
def post_signup(
    request: SignupRequest,
    response: Response,
    session: Session = Depends(get_db),
) -> AuthSessionResponse | JSONResponse:
    try:
        issued = signup(session, request)
        session.commit()
        _set_session_cookie(response, issued)
        return issued.response
    except AuthServiceError as exc:
        session.rollback()
        return _auth_error(exc)


@router.post("/auth/login", response_model=AuthSessionResponse)
def post_login(
    request: LoginRequest,
    response: Response,
    session: Session = Depends(get_db),
) -> AuthSessionResponse | JSONResponse:
    try:
        issued = login(session, request.email, request.password)
        session.commit()
        _set_session_cookie(response, issued)
        return issued.response
    except AuthServiceError as exc:
        session.rollback()
        return _auth_error(exc)


@router.post("/auth/google", response_model=AuthSessionResponse)
def post_google_login(
    request: GoogleLoginRequest,
    response: Response,
    g_csrf_token: str | None = Cookie(default=None),
    session: Session = Depends(get_db),
) -> AuthSessionResponse | JSONResponse:
    try:
        issued = login_with_google(
            session,
            credential=request.credential,
            consents=request.consents,
            csrf_token=request.g_csrf_token,
            csrf_cookie=g_csrf_token,
        )
        session.commit()
        _set_session_cookie(response, issued)
        return issued.response
    except AuthServiceError as exc:
        session.rollback()
        return _auth_error(exc)


@router.post("/auth/refresh", response_model=AuthSessionResponse)
def post_refresh(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=settings.auth_session_cookie_name),
    session: Session = Depends(get_db),
) -> AuthSessionResponse | JSONResponse:
    try:
        issued = refresh(session, session_token)
        session.commit()
        _set_session_cookie(response, issued)
        return issued.response
    except AuthServiceError as exc:
        session.rollback()
        return _auth_error(exc)


@router.post("/auth/logout", response_model=MessageResponse)
def post_logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=settings.auth_session_cookie_name),
    session: Session = Depends(get_db),
) -> MessageResponse:
    logout(session, session_token)
    session.commit()
    _delete_session_cookie(response)
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
    current_user: User = Depends(get_current_user),
) -> AuthUser:
    return AuthUser(
        id=current_user.id,
        email=current_user.email,
        nickname=current_user.display_name,
        role=current_user.role,
        status=current_user.status,
        created_at=current_user.created_at,
    )


@router.delete("/me", response_model=MessageResponse)
def delete_me(
    response: Response,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> MessageResponse:
    delete_user_account(session, current_user)
    session.commit()
    _delete_session_cookie(response)
    return MessageResponse(message="회원탈퇴가 완료되었습니다.")


def _set_session_cookie(response: Response, issued: IssuedAuthSession) -> None:
    max_age = max(0, int((_as_utc(issued.expires_at) - datetime.now(UTC)).total_seconds()))
    response.set_cookie(
        key=settings.auth_session_cookie_name,
        value=issued.session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _delete_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_session_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
