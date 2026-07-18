from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.models.auth import AuthAccount, AuthSession, PasswordResetToken, TermsVersion, User, UserConsent
from app.db.session import get_db
from app.main import app
from app.services.google_oauth import GoogleAccountInfo, GoogleTokenVerificationError


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def client(db_engine: Engine) -> Generator[TestClient, None, None]:
    def override_get_db():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_signup_creates_user_auth_account_consents_and_session(
    client: TestClient,
    db_engine: Engine,
) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": "USER@example.com",
            "password": "password123",
            "nickname": "원우",
            "consents": {
                "tos": True,
                "privacy": True,
                "age14": True,
                "marketing": False,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" not in data
    assert "refresh_token" not in data
    assert response.cookies.get(settings.auth_session_cookie_name)
    assert data["user"]["email"] == "user@example.com"
    assert data["user"]["nickname"] == "원우"

    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == "user@example.com")).scalar_one()
        account = session.execute(select(AuthAccount).where(AuthAccount.user_id == user.id)).scalar_one()
        auth_session = session.execute(select(AuthSession).where(AuthSession.user_id == user.id)).scalar_one()
        consents = session.execute(select(UserConsent).where(UserConsent.user_id == user.id)).scalars().all()
        terms_versions = session.execute(select(TermsVersion)).scalars().all()

    assert account.provider == "email"
    assert account.provider_account_id == "user@example.com"
    assert account.password_hash
    assert auth_session.token_hash != response.cookies.get(settings.auth_session_cookie_name)
    assert auth_session.revoked_at is None
    assert len(consents) == 4
    assert {consent.consent_key: consent.agreed for consent in consents} == {
        "tos": True,
        "privacy": True,
        "age14": True,
        "marketing": False,
    }
    assert {terms.terms_key for terms in terms_versions} == {"tos", "privacy", "age14", "marketing"}


def test_check_email_and_nickname_return_409_for_duplicates(client: TestClient) -> None:
    _signup(client, email="duplicate@example.com", nickname="중복")

    email_response = client.get("/api/auth/check-email", params={"email": "duplicate@example.com"})
    nickname_response = client.get("/api/auth/check-nickname", params={"nickname": "중복"})

    assert email_response.status_code == 409
    assert email_response.json()["code"] == "EMAIL_ALREADY_EXISTS"
    assert email_response.json()["available"] is False
    assert nickname_response.status_code == 409
    assert nickname_response.json()["code"] == "NICKNAME_ALREADY_EXISTS"
    assert nickname_response.json()["available"] is False


def test_signup_rejects_missing_required_consents(client: TestClient) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": "consent@example.com",
            "password": "password123",
            "nickname": "동의부족",
            "consents": {
                "tos": True,
                "privacy": False,
                "age14": True,
                "marketing": False,
            },
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "REQUIRED_CONSENT_MISSING"


def test_login_refresh_me_and_logout_flow(client: TestClient) -> None:
    _signup(client, email="login@example.com", nickname="로그인")

    login_response = client.post(
        "/api/auth/login",
        json={"email": "login@example.com", "password": "password123"},
    )
    assert login_response.status_code == 200
    login_data = login_response.json()
    first_session_cookie = login_response.cookies.get(settings.auth_session_cookie_name)

    assert "access_token" not in login_data
    assert "refresh_token" not in login_data
    assert first_session_cookie

    me_response = client.get("/api/me")
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "login@example.com"

    refresh_response = client.post("/api/auth/refresh")
    assert refresh_response.status_code == 200
    refreshed = refresh_response.json()
    refreshed_session_cookie = refresh_response.cookies.get(settings.auth_session_cookie_name)
    assert "access_token" not in refreshed
    assert "refresh_token" not in refreshed
    assert refreshed_session_cookie
    assert refreshed_session_cookie != first_session_cookie

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200

    me_after_logout_response = client.get("/api/me")
    assert me_after_logout_response.status_code == 401
    assert me_after_logout_response.json()["code"] == "INVALID_SESSION"


def test_login_distinguishes_invalid_password(client: TestClient) -> None:
    _signup(client, email="wrong@example.com", nickname="비번틀림")

    response = client.post(
        "/api/auth/login",
        json={"email": "wrong@example.com", "password": "wrong1234"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_PASSWORD"
    assert response.json()["message"] == "비밀번호가 일치하지 않습니다."


def test_login_distinguishes_missing_account(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "password123"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "ACCOUNT_NOT_FOUND"
    assert response.json()["message"] == "가입되지 않은 이메일입니다."


def test_email_login_guides_google_only_account(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.auth_service.verify_google_id_token",
        lambda credential: GoogleAccountInfo(
            sub="google-only-login",
            email="google-only-login@gmail.com",
            email_verified=True,
            name="Google Only",
        ),
    )
    google_response = client.post(
        "/api/auth/google",
        json={
            "credential": "valid-google-token",
            "consents": {
                "tos": True,
                "privacy": True,
                "age14": True,
                "marketing": False,
            },
        },
    )
    assert google_response.status_code == 200

    response = client.post(
        "/api/auth/login",
        json={"email": "google-only-login@gmail.com", "password": "password123"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "EMAIL_LOGIN_NOT_AVAILABLE"
    assert response.json()["message"] == "소셜 로그인으로 가입한 계정입니다."


def test_google_login_creates_user_auth_account_consents_and_tokens(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.auth_service.verify_google_id_token",
        lambda credential: GoogleAccountInfo(
            sub="google-sub-1",
            email="social-user@gmail.com",
            email_verified=True,
            name="Social User",
        ),
    )

    response = client.post(
        "/api/auth/google",
        json={
            "credential": "valid-google-token",
            "consents": {
                "tos": True,
                "privacy": True,
                "age14": True,
                "marketing": False,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" not in data
    assert "refresh_token" not in data
    assert response.cookies.get(settings.auth_session_cookie_name)
    assert data["user"]["email"] == "social-user@gmail.com"
    assert data["user"]["nickname"] == "Social User"

    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == "social-user@gmail.com")).scalar_one()
        account = session.execute(select(AuthAccount).where(AuthAccount.user_id == user.id)).scalar_one()
        consents = session.execute(select(UserConsent).where(UserConsent.user_id == user.id)).scalars().all()

    assert account.provider == "google"
    assert account.provider_account_id == "google-sub-1"
    assert account.provider_email == "social-user@gmail.com"
    assert account.password_hash is None
    assert account.is_verified is True
    assert {consent.consent_key: consent.agreed for consent in consents} == {
        "tos": True,
        "privacy": True,
        "age14": True,
        "marketing": False,
    }


def test_google_login_links_existing_email_user(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signup_data = _signup(client, email="link-user@gmail.com", nickname="link-user")
    monkeypatch.setattr(
        "app.services.auth_service.verify_google_id_token",
        lambda credential: GoogleAccountInfo(
            sub="google-sub-link",
            email="link-user@gmail.com",
            email_verified=True,
            name="Linked User",
        ),
    )

    response = client.post("/api/auth/google", json={"credential": "valid-google-token"})

    assert response.status_code == 200
    data = response.json()
    assert data["user"]["id"] == signup_data["user"]["id"]
    with Session(db_engine) as session:
        accounts = session.execute(
            select(AuthAccount).where(AuthAccount.user_id == signup_data["user"]["id"])
        ).scalars().all()
    assert {account.provider for account in accounts} == {"email", "google"}


def test_google_login_reuses_existing_google_account(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.auth_service.verify_google_id_token",
        lambda credential: GoogleAccountInfo(
            sub="google-sub-repeat",
            email="repeat-user@gmail.com",
            email_verified=True,
            name="Repeat User",
        ),
    )
    body = {
        "credential": "valid-google-token",
        "consents": {
            "tos": True,
            "privacy": True,
            "age14": True,
            "marketing": False,
        },
    }

    first_response = client.post("/api/auth/google", json=body)
    second_response = client.post("/api/auth/google", json={"credential": "valid-google-token"})

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["user"]["id"] == first_response.json()["user"]["id"]
    with Session(db_engine) as session:
        user_count = len(session.execute(select(User).where(User.email == "repeat-user@gmail.com")).scalars().all())
        account_count = len(
            session.execute(
                select(AuthAccount).where(
                    AuthAccount.provider == "google",
                    AuthAccount.provider_account_id == "google-sub-repeat",
                )
            ).scalars().all()
        )
    assert user_count == 1
    assert account_count == 1


def test_google_login_rejects_new_user_without_required_consents(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.auth_service.verify_google_id_token",
        lambda credential: GoogleAccountInfo(
            sub="google-sub-no-consent",
            email="no-consent@gmail.com",
            email_verified=True,
            name="No Consent",
        ),
    )

    response = client.post("/api/auth/google", json={"credential": "valid-google-token"})

    assert response.status_code == 400
    assert response.json()["code"] == "REQUIRED_CONSENT_MISSING"


def test_google_login_rejects_non_authoritative_email(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.auth_service.verify_google_id_token",
        lambda credential: GoogleAccountInfo(
            sub="google-sub-example",
            email="external@example.com",
            email_verified=True,
            name="External User",
        ),
    )

    response = client.post(
        "/api/auth/google",
        json={
            "credential": "valid-google-token",
            "consents": {
                "tos": True,
                "privacy": True,
                "age14": True,
                "marketing": False,
            },
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "GOOGLE_EMAIL_NOT_VERIFIED"


def test_google_login_rejects_invalid_google_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_invalid_token(credential: str) -> GoogleAccountInfo:
        raise GoogleTokenVerificationError("INVALID_GOOGLE_TOKEN")

    monkeypatch.setattr("app.services.auth_service.verify_google_id_token", raise_invalid_token)

    response = client.post("/api/auth/google", json={"credential": "invalid-google-token"})

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_GOOGLE_TOKEN"


def test_password_reset_request_hides_email_existence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_codes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.services.auth_service.send_password_reset_code",
        lambda email, code: sent_codes.append((email, code)),
    )
    _signup(client, email="reset@example.com", nickname="재설정")

    existing_response = client.post("/api/auth/password-reset", json={"email": "reset@example.com"})
    missing_response = client.post("/api/auth/password-reset", json={"email": "missing@example.com"})

    assert existing_response.status_code == 200
    assert missing_response.status_code == 200
    assert existing_response.json() == missing_response.json()
    assert sent_codes and sent_codes[0][0] == "reset@example.com"


def test_password_reset_request_skips_google_only_account(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.auth_service.verify_google_id_token",
        lambda credential: GoogleAccountInfo(
            sub="google-sub-reset-only",
            email="google-only@gmail.com",
            email_verified=True,
            name="Google Only",
        ),
    )
    google_response = client.post(
        "/api/auth/google",
        json={
            "credential": "valid-google-token",
            "consents": {
                "tos": True,
                "privacy": True,
                "age14": True,
                "marketing": False,
            },
        },
    )
    assert google_response.status_code == 200

    sent_codes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.services.auth_service.send_password_reset_code",
        lambda email, code: sent_codes.append((email, code)),
    )

    response = client.post("/api/auth/password-reset", json={"email": "google-only@gmail.com"})

    assert response.status_code == 200
    assert sent_codes == []


def test_password_reset_confirm_changes_password_and_revokes_sessions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_codes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.services.auth_service.send_password_reset_code",
        lambda email, code: sent_codes.append((email, code)),
    )
    signup_data = _signup(client, email="confirm@example.com", nickname="확정")
    client.post("/api/auth/password-reset", json={"email": "confirm@example.com"})

    response = client.post(
        "/api/auth/password-reset/confirm",
        json={
            "email": "confirm@example.com",
            "code": sent_codes[0][1],
            "new_password": "newpass123",
        },
    )

    assert response.status_code == 200
    assert client.get("/api/me").status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "confirm@example.com", "password": "password123"},
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "confirm@example.com", "password": "newpass123"},
    ).status_code == 200


def test_password_reset_confirm_locks_after_too_many_failures(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_codes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.services.auth_service.send_password_reset_code",
        lambda email, code: sent_codes.append((email, code)),
    )
    _signup(client, email="lock@example.com", nickname="잠김")
    client.post("/api/auth/password-reset", json={"email": "lock@example.com"})

    for _ in range(5):
        response = client.post(
            "/api/auth/password-reset/confirm",
            json={"email": "lock@example.com", "code": "000000", "new_password": "newpass123"},
        )
        assert response.status_code == 400

    locked_response = client.post(
        "/api/auth/password-reset/confirm",
        json={"email": "lock@example.com", "code": sent_codes[0][1], "new_password": "newpass123"},
    )

    assert locked_response.status_code == 429
    with Session(db_engine) as session:
        token = session.execute(select(PasswordResetToken)).scalar_one()
        assert token.failed_attempt_count == 5


def _signup(client: TestClient, *, email: str, nickname: str) -> dict:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "password123",
            "nickname": nickname,
            "consents": {
                "tos": True,
                "privacy": True,
                "age14": True,
                "marketing": False,
            },
        },
    )
    assert response.status_code == 200
    return response.json()
