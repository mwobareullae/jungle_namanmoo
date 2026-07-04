from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class GoogleAccountInfo:
    sub: str
    email: str
    email_verified: bool
    name: str | None = None
    picture: str | None = None
    hosted_domain: str | None = None


class GoogleTokenVerificationError(ValueError):
    pass


def verify_google_id_token(credential: str) -> GoogleAccountInfo:
    if not settings.google_client_id:
        raise GoogleTokenVerificationError("GOOGLE_LOGIN_NOT_CONFIGURED")

    try:
        from google.auth.transport import requests
        from google.oauth2 import id_token
    except ImportError as exc:
        raise GoogleTokenVerificationError("GOOGLE_AUTH_LIBRARY_NOT_INSTALLED") from exc

    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            requests.Request(),
            settings.google_client_id,
        )
    except ValueError as exc:
        raise GoogleTokenVerificationError("INVALID_GOOGLE_TOKEN") from exc

    issuer = idinfo.get("iss")
    if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
        raise GoogleTokenVerificationError("INVALID_GOOGLE_ISSUER")

    sub = str(idinfo.get("sub") or "").strip()
    email = str(idinfo.get("email") or "").strip().lower()
    if not sub or not email:
        raise GoogleTokenVerificationError("INVALID_GOOGLE_PROFILE")

    return GoogleAccountInfo(
        sub=sub,
        email=email,
        email_verified=bool(idinfo.get("email_verified")),
        name=idinfo.get("name"),
        picture=idinfo.get("picture"),
        hosted_domain=idinfo.get("hd"),
    )
