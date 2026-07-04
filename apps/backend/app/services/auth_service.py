from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.auth import (
    AuthAccount,
    PasswordResetToken,
    RefreshToken,
    TermsVersion,
    User,
    UserConsent,
)
from app.schemas.auth import AuthUser, SignupConsents, SignupRequest, TokenResponse
from app.services.google_oauth import (
    GoogleAccountInfo,
    GoogleTokenVerificationError,
    verify_google_id_token,
)
from app.services.auth_security import (
    PASSWORD_RESET_CODE_TTL,
    PASSWORD_RESET_MAX_ATTEMPTS,
    REFRESH_TOKEN_TTL,
    TokenDecodeError,
    create_access_token,
    decode_access_token,
    generate_password_reset_code,
    generate_refresh_token,
    generate_token_family_id,
    hash_password,
    hash_password_reset_code,
    hash_refresh_token,
    is_valid_email,
    is_valid_password,
    normalize_email,
    normalize_nickname,
    verify_password,
)
from app.services.email_service import send_password_reset_code


DEFAULT_TERMS_VERSION = "2026-07-09"
PASSWORD_RESET_RESPONSE_MESSAGE = "비밀번호 재설정 안내를 이메일로 보냈습니다."

_TERMS_DEFINITIONS = {
    "tos": ("이용약관", True),
    "privacy": ("개인정보처리방침", True),
    "age14": ("만 14세 이상 확인", True),
    "marketing": ("마케팅 정보 수신 동의", False),
}


@dataclass(frozen=True)
class AuthServiceError(Exception):
    status_code: int
    code: str
    message: str


def is_email_available(session: Session, email: str) -> bool:
    normalized = normalize_email(email)
    if not is_valid_email(normalized):
        raise AuthServiceError(400, "INVALID_EMAIL", "이메일 형식이 올바르지 않습니다.")
    return _find_user_by_email(session, normalized) is None


def is_nickname_available(session: Session, nickname: str) -> bool:
    normalized = normalize_nickname(nickname)
    if not normalized:
        raise AuthServiceError(400, "INVALID_NICKNAME", "닉네임을 입력해 주세요.")
    return _find_user_by_nickname(session, normalized) is None


def signup(session: Session, request: SignupRequest) -> TokenResponse:
    email = normalize_email(request.email)
    nickname = normalize_nickname(request.nickname)
    _validate_signup_input(session, email, nickname, request.password, request.consents)

    now = datetime.now(UTC)
    user = User(
        email=email,
        display_name=nickname,
        status="ACTIVE",
        role="USER",
    )
    session.add(user)
    session.flush()

    account = AuthAccount(
        user_id=user.id,
        provider="email",
        provider_account_id=email,
        provider_email=email,
        password_hash=hash_password(request.password),
        password_updated_at=now,
        is_verified=False,
    )
    session.add(account)
    _save_user_consents(session, user.id, request.consents)

    token_response = _issue_token_response(session, user, now=now)
    session.flush()
    return token_response


def login(session: Session, email: str, password: str) -> TokenResponse:
    normalized = normalize_email(email)
    account = session.execute(
        select(AuthAccount).where(
            AuthAccount.provider == "email",
            AuthAccount.provider_account_id == normalized,
        )
    ).scalar_one_or_none()
    if account is None or not verify_password(password, account.password_hash):
        raise AuthServiceError(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 일치하지 않습니다.")

    user = session.get(User, account.user_id)
    if user is None or user.status != "ACTIVE":
        raise AuthServiceError(403, "USER_NOT_ACTIVE", "이용할 수 없는 계정입니다.")

    now = datetime.now(UTC)
    user.last_login_at = now
    return _issue_token_response(session, user, now=now)


def login_with_google(
    session: Session,
    *,
    credential: str,
    consents: SignupConsents | None = None,
    csrf_token: str | None = None,
    csrf_cookie: str | None = None,
) -> TokenResponse:
    _validate_google_csrf(csrf_token, csrf_cookie)
    try:
        google_account = verify_google_id_token(credential)
    except GoogleTokenVerificationError as exc:
        code = str(exc)
        status_code = 500 if code in {"GOOGLE_LOGIN_NOT_CONFIGURED", "GOOGLE_AUTH_LIBRARY_NOT_INSTALLED"} else 401
        message = "Google login is not configured." if status_code == 500 else "Google login token is invalid."
        raise AuthServiceError(status_code, code, message) from exc

    if not google_account.email_verified or not _is_google_authoritative_email(google_account):
        raise AuthServiceError(400, "GOOGLE_EMAIL_NOT_VERIFIED", "Google email is not verified.")

    now = datetime.now(UTC)
    account = session.execute(
        select(AuthAccount).where(
            AuthAccount.provider == "google",
            AuthAccount.provider_account_id == google_account.sub,
        )
    ).scalar_one_or_none()
    if account is not None:
        user = _load_active_user(session, account.user_id)
        account.provider_email = google_account.email
        account.is_verified = google_account.email_verified
        user.last_login_at = now
        return _issue_token_response(session, user, now=now)

    user = _find_user_by_email(session, google_account.email)
    if user is not None:
        user = _load_active_user(session, user.id)
        session.add(
            AuthAccount(
                user_id=user.id,
                provider="google",
                provider_account_id=google_account.sub,
                provider_email=google_account.email,
                is_verified=google_account.email_verified,
            )
        )
        user.last_login_at = now
        session.flush()
        return _issue_token_response(session, user, now=now)

    if consents is None or not (consents.tos and consents.privacy and consents.age14):
        raise AuthServiceError(400, "REQUIRED_CONSENT_MISSING", "Required terms consent is missing.")

    user = User(
        email=google_account.email,
        display_name=_build_unique_social_nickname(session, google_account),
        status="ACTIVE",
        role="USER",
        last_login_at=now,
    )
    session.add(user)
    session.flush()
    session.add(
        AuthAccount(
            user_id=user.id,
            provider="google",
            provider_account_id=google_account.sub,
            provider_email=google_account.email,
            is_verified=google_account.email_verified,
        )
    )
    _save_user_consents(session, user.id, consents)
    token_response = _issue_token_response(session, user, now=now)
    session.flush()
    return token_response


def refresh(session: Session, refresh_token: str) -> TokenResponse:
    token_row = _load_valid_refresh_token(session, refresh_token)
    user = session.get(User, token_row.user_id)
    if user is None or user.status != "ACTIVE":
        raise AuthServiceError(403, "USER_NOT_ACTIVE", "이용할 수 없는 계정입니다.")

    now = datetime.now(UTC)
    token_row.revoked_at = now
    next_refresh_token = generate_refresh_token()
    next_token_row = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(next_refresh_token),
        family_id=token_row.family_id or generate_token_family_id(),
        expires_at=now + REFRESH_TOKEN_TTL,
    )
    session.add(next_token_row)
    session.flush()
    token_row.replaced_by_token_id = next_token_row.id

    return TokenResponse(
        access_token=create_access_token(user_id=user.id, email=user.email, role=user.role, now=now),
        refresh_token=next_refresh_token,
        user=_to_auth_user(user),
    )


def logout(session: Session, refresh_token: str) -> None:
    token_hash = hash_refresh_token(refresh_token)
    token_row = session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    ).scalar_one_or_none()
    if token_row is not None and token_row.revoked_at is None:
        token_row.revoked_at = datetime.now(UTC)


def get_user_from_access_token(session: Session, access_token: str) -> User:
    try:
        payload = decode_access_token(access_token)
        user_id = int(payload["sub"])
    except (TokenDecodeError, KeyError, ValueError) as exc:
        raise AuthServiceError(401, "INVALID_TOKEN", "인증 정보가 올바르지 않습니다.") from exc

    user = session.get(User, user_id)
    if user is None or user.status != "ACTIVE":
        raise AuthServiceError(401, "INVALID_TOKEN", "인증 정보가 올바르지 않습니다.")
    return user


def request_password_reset(session: Session, email: str) -> None:
    normalized = normalize_email(email)
    if not is_valid_email(normalized):
        return

    user = _find_user_by_email(session, normalized)
    if user is None:
        return

    now = datetime.now(UTC)
    _expire_existing_password_reset_tokens(session, user.id, normalized, now)
    code = generate_password_reset_code()
    token = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_password_reset_code(normalized, code),
        requested_email=normalized,
        expires_at=now + PASSWORD_RESET_CODE_TTL,
    )
    session.add(token)
    session.flush()
    send_password_reset_code(normalized, code)


def confirm_password_reset(
    session: Session,
    *,
    email: str,
    code: str,
    new_password: str,
) -> None:
    normalized = normalize_email(email)
    if not is_valid_email(normalized):
        raise AuthServiceError(400, "INVALID_RESET_CODE", "인증 코드가 올바르지 않습니다.")
    if not is_valid_password(new_password):
        raise AuthServiceError(400, "INVALID_PASSWORD", "비밀번호는 8자 이상, 영문과 숫자를 포함해야 합니다.")

    user = _find_user_by_email(session, normalized)
    if user is None:
        raise AuthServiceError(400, "INVALID_RESET_CODE", "인증 코드가 올바르지 않습니다.")

    token = _load_latest_password_reset_token(session, user.id, normalized)
    if token is None:
        raise AuthServiceError(400, "INVALID_RESET_CODE", "인증 코드가 올바르지 않습니다.")

    now = datetime.now(UTC)
    if token.used_at is not None or _as_utc(token.expires_at) <= now:
        raise AuthServiceError(400, "EXPIRED_RESET_CODE", "인증 코드가 만료되었습니다.")
    if token.failed_attempt_count >= PASSWORD_RESET_MAX_ATTEMPTS:
        raise AuthServiceError(429, "RESET_CODE_LOCKED", "인증 코드 시도 횟수를 초과했습니다.")

    expected_hash = hash_password_reset_code(normalized, code.strip())
    if token.token_hash != expected_hash:
        token.failed_attempt_count += 1
        token.last_attempt_at = now
        raise AuthServiceError(400, "INVALID_RESET_CODE", "인증 코드가 올바르지 않습니다.")

    account = session.execute(
        select(AuthAccount).where(
            AuthAccount.user_id == user.id,
            AuthAccount.provider == "email",
        )
    ).scalar_one_or_none()
    if account is None:
        raise AuthServiceError(400, "EMAIL_LOGIN_NOT_AVAILABLE", "이메일 로그인 계정이 없습니다.")

    account.password_hash = hash_password(new_password)
    account.password_updated_at = now
    token.used_at = now
    token.last_attempt_at = now
    _revoke_user_refresh_tokens(session, user.id, now)


def _validate_signup_input(
    session: Session,
    email: str,
    nickname: str,
    password: str,
    consents: SignupConsents,
) -> None:
    if not is_valid_email(email):
        raise AuthServiceError(400, "INVALID_EMAIL", "이메일 형식이 올바르지 않습니다.")
    if not nickname:
        raise AuthServiceError(400, "INVALID_NICKNAME", "닉네임을 입력해 주세요.")
    if not is_valid_password(password):
        raise AuthServiceError(400, "INVALID_PASSWORD", "비밀번호는 8자 이상, 영문과 숫자를 포함해야 합니다.")
    if not (consents.tos and consents.privacy and consents.age14):
        raise AuthServiceError(400, "REQUIRED_CONSENT_MISSING", "필수 약관에 모두 동의해야 합니다.")
    if _find_user_by_email(session, email) is not None:
        raise AuthServiceError(409, "EMAIL_ALREADY_EXISTS", "이미 가입된 이메일입니다.")
    if _find_user_by_nickname(session, nickname) is not None:
        raise AuthServiceError(409, "NICKNAME_ALREADY_EXISTS", "이미 사용 중인 닉네임입니다.")


def _validate_google_csrf(csrf_token: str | None, csrf_cookie: str | None) -> None:
    if csrf_token is None and csrf_cookie is None:
        return
    if not csrf_token or not csrf_cookie or csrf_token != csrf_cookie:
        raise AuthServiceError(400, "INVALID_CSRF_TOKEN", "Google login CSRF token is invalid.")


def _is_google_authoritative_email(google_account: GoogleAccountInfo) -> bool:
    if not google_account.email_verified:
        return False
    _, _, domain = google_account.email.rpartition("@")
    return domain.lower() == "gmail.com" or bool(google_account.hosted_domain)


def _load_active_user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None or user.status != "ACTIVE":
        raise AuthServiceError(403, "USER_NOT_ACTIVE", "User is not active.")
    return user


def _build_unique_social_nickname(session: Session, google_account: GoogleAccountInfo) -> str:
    raw_base = normalize_nickname(google_account.name or google_account.email.split("@", 1)[0])
    base = raw_base or "google_user"
    base = base[:90]
    if _find_user_by_nickname(session, base) is None:
        return base

    for suffix in range(2, 1000):
        suffix_text = str(suffix)
        candidate = f"{base[:100 - len(suffix_text)]}{suffix_text}"
        if _find_user_by_nickname(session, candidate) is None:
            return candidate

    return f"google_user_{google_account.sub[-12:]}"


def _save_user_consents(session: Session, user_id: int, consents: SignupConsents) -> None:
    versions = _ensure_active_terms_versions(session)
    for key, agreed in consents.model_dump().items():
        version = versions[key]
        session.add(
            UserConsent(
                user_id=user_id,
                terms_version_id=version.id,
                consent_key=key,
                agreed=bool(agreed),
            )
        )


def _ensure_active_terms_versions(session: Session) -> dict[str, TermsVersion]:
    rows = session.execute(
        select(TermsVersion).where(
            TermsVersion.version == DEFAULT_TERMS_VERSION,
            TermsVersion.terms_key.in_(tuple(_TERMS_DEFINITIONS)),
        )
    ).scalars()
    versions_by_key = {row.terms_key: row for row in rows}

    for key, (title, is_required) in _TERMS_DEFINITIONS.items():
        if key in versions_by_key:
            continue
        version = TermsVersion(
            terms_key=key,
            version=DEFAULT_TERMS_VERSION,
            title=title,
            is_required=is_required,
            is_active=True,
        )
        session.add(version)
        versions_by_key[key] = version

    session.flush()
    return versions_by_key


def _issue_token_response(session: Session, user: User, *, now: datetime) -> TokenResponse:
    refresh_token = generate_refresh_token()
    token_row = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(refresh_token),
        family_id=generate_token_family_id(),
        expires_at=now + REFRESH_TOKEN_TTL,
    )
    session.add(token_row)
    return TokenResponse(
        access_token=create_access_token(user_id=user.id, email=user.email, role=user.role, now=now),
        refresh_token=refresh_token,
        user=_to_auth_user(user),
    )


def _load_valid_refresh_token(session: Session, refresh_token: str) -> RefreshToken:
    token_row = session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(refresh_token))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if token_row is None or token_row.revoked_at is not None or _as_utc(token_row.expires_at) <= now:
        raise AuthServiceError(401, "INVALID_REFRESH_TOKEN", "refresh token이 올바르지 않습니다.")
    return token_row


def _find_user_by_email(session: Session, email: str) -> User | None:
    return session.execute(select(User).where(User.email == email)).scalar_one_or_none()


def _find_user_by_nickname(session: Session, nickname: str) -> User | None:
    return session.execute(select(User).where(User.display_name == nickname)).scalar_one_or_none()


def _expire_existing_password_reset_tokens(
    session: Session,
    user_id: int,
    email: str,
    now: datetime,
) -> None:
    rows = session.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.requested_email == email,
            PasswordResetToken.used_at.is_(None),
        )
    ).scalars()
    for row in rows:
        row.used_at = now


def _load_latest_password_reset_token(
    session: Session,
    user_id: int,
    email: str,
) -> PasswordResetToken | None:
    return session.execute(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.requested_email == email,
            PasswordResetToken.used_at.is_(None),
        )
        .order_by(PasswordResetToken.created_at.desc(), PasswordResetToken.id.desc())
    ).scalar_one_or_none()


def _revoke_user_refresh_tokens(session: Session, user_id: int, now: datetime) -> None:
    rows = session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
    ).scalars()
    for row in rows:
        row.revoked_at = now


def _to_auth_user(user: User) -> AuthUser:
    return AuthUser(
        id=user.id,
        email=user.email,
        nickname=user.display_name,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
