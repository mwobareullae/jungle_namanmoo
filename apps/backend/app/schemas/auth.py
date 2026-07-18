from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AvailabilityResponse(BaseModel):
    available: bool
    code: str | None = None
    message: str


class SignupConsents(BaseModel):
    tos: bool
    privacy: bool
    age14: bool
    marketing: bool = False


class SignupRequest(BaseModel):
    email: str
    password: str
    nickname: str
    consents: SignupConsents


class LoginRequest(BaseModel):
    email: str
    password: str


class UpdateMeRequest(BaseModel):
    nickname: str


class GoogleLoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    credential: str
    consents: SignupConsents | None = None
    g_csrf_token: str | None = Field(default=None, alias="g_csrf_token")


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirmRequest(BaseModel):
    email: str
    code: str
    new_password: str


class AuthUser(BaseModel):
    id: int
    email: str
    nickname: str | None = None
    role: str = "USER"
    status: str = "ACTIVE"
    created_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AuthUser


class AuthSessionResponse(BaseModel):
    user: AuthUser


class MessageResponse(BaseModel):
    message: str
