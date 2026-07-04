from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import big_integer_pk_type


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("display_name", name="uq_users_display_name"),
        CheckConstraint("length(trim(email)) > 0", name="ck_users_email_not_blank"),
        CheckConstraint("status in ('ACTIVE', 'INACTIVE', 'SUSPENDED', 'DELETED')", name="ck_users_status"),
        CheckConstraint("role in ('USER', 'ADMIN')", name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE", server_default="ACTIVE")
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="USER", server_default="USER")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuthAccount(Base):
    __tablename__ = "auth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_auth_accounts_provider_account"),
        CheckConstraint("length(trim(provider)) > 0", name="ck_auth_accounts_provider_not_blank"),
        CheckConstraint("length(trim(provider_account_id)) > 0", name="ck_auth_accounts_provider_account_not_blank"),
        CheckConstraint("provider <> 'email' OR password_hash IS NOT NULL", name="ck_auth_accounts_email_password_hash"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    family_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_token_id: Mapped[int | None] = mapped_column(ForeignKey("refresh_tokens.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    requested_email: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TermsVersion(Base):
    __tablename__ = "terms_versions"
    __table_args__ = (
        UniqueConstraint("terms_key", "version", name="uq_terms_versions_key_version"),
        CheckConstraint("terms_key in ('tos', 'privacy', 'age14', 'marketing')", name="ck_terms_versions_key"),
        CheckConstraint("length(trim(version)) > 0", name="ck_terms_versions_version_not_blank"),
        CheckConstraint("length(trim(title)) > 0", name="ck_terms_versions_title_not_blank"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    terms_key: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserConsent(Base):
    __tablename__ = "user_consents"
    __table_args__ = (
        UniqueConstraint("user_id", "terms_version_id", name="uq_user_consents_user_terms_version"),
        CheckConstraint("consent_key in ('tos', 'privacy', 'age14', 'marketing')", name="ck_user_consents_key"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    terms_version_id: Mapped[int] = mapped_column(ForeignKey("terms_versions.id"), nullable=False, index=True)
    consent_key: Mapped[str] = mapped_column(String(40), nullable=False)
    agreed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
