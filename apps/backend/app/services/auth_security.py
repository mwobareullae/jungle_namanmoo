from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings


ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=14)
PASSWORD_RESET_CODE_TTL = timedelta(minutes=10)
PASSWORD_RESET_CODE_LENGTH = 6
PASSWORD_RESET_MAX_ATTEMPTS = 5
PASSWORD_HASH_ITERATIONS = 210_000

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_JWT_ALGORITHM = "HS256"


class TokenDecodeError(ValueError):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_nickname(nickname: str) -> str:
    return nickname.strip()


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_PATTERN.fullmatch(email))


def is_valid_password(password: str) -> bool:
    return len(password) >= 8 and any(char.isalpha() for char in password) and any(
        char.isdigit() for char in password
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return "$".join(
        [
            "pbkdf2_sha256",
            str(PASSWORD_HASH_ITERATIONS),
            _b64encode(salt),
            _b64encode(digest),
        ]
    )


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False

    try:
        algorithm, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = _b64decode(salt_text)
        expected_digest = _b64decode(digest_text)
    except (ValueError, TypeError):
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def create_access_token(
    *,
    user_id: int,
    email: str,
    role: str,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "type": "access",
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + ACCESS_TOKEN_TTL).timestamp()),
    }
    return _encode_jwt(payload)


def decode_access_token(token: str, *, now: datetime | None = None) -> dict[str, Any]:
    payload = _decode_jwt(token)
    if payload.get("type") != "access":
        raise TokenDecodeError("invalid token type")

    expires_at = int(payload.get("exp", 0))
    current = int((now or datetime.now(UTC)).timestamp())
    if expires_at <= current:
        raise TokenDecodeError("expired token")

    if not payload.get("sub"):
        raise TokenDecodeError("missing subject")
    return payload


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def generate_token_family_id() -> str:
    return secrets.token_urlsafe(24)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_password_reset_code() -> str:
    upper_bound = 10**PASSWORD_RESET_CODE_LENGTH
    return f"{secrets.randbelow(upper_bound):0{PASSWORD_RESET_CODE_LENGTH}d}"


def hash_password_reset_code(email: str, code: str) -> str:
    normalized_email = normalize_email(email)
    message = f"{normalized_email}:{code}".encode("utf-8")
    return hmac.new(
        settings.auth_jwt_secret_key.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def _encode_jwt(payload: dict[str, Any]) -> str:
    header = {"alg": _JWT_ALGORITHM, "typ": "JWT"}
    signing_input = ".".join(
        [
            _b64encode_json(header),
            _b64encode_json(payload),
        ]
    )
    signature = hmac.new(
        settings.auth_jwt_secret_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def _decode_jwt(token: str) -> dict[str, Any]:
    try:
        header_text, payload_text, signature_text = token.split(".", 2)
    except ValueError as exc:
        raise TokenDecodeError("invalid token format") from exc

    signing_input = f"{header_text}.{payload_text}"
    expected_signature = hmac.new(
        settings.auth_jwt_secret_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    actual_signature = _b64decode(signature_text)
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise TokenDecodeError("invalid token signature")

    try:
        header = json.loads(_b64decode(header_text))
        payload = json.loads(_b64decode(payload_text))
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenDecodeError("invalid token payload") from exc

    if header.get("alg") != _JWT_ALGORITHM:
        raise TokenDecodeError("invalid token algorithm")
    return payload


def _b64encode_json(value: dict[str, Any]) -> str:
    return _b64encode(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
