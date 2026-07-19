from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.shipping_address import (
    normalize_phone,
    normalize_postal_code,
    normalize_recipient_name,
    normalize_required_address,
)


class UserAddressCreateRequest(BaseModel):
    recipient_name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=1, max_length=30)
    postal_code: str = Field(..., min_length=1, max_length=20)
    address1: str = Field(..., min_length=1, max_length=255)
    address2: str = Field(..., min_length=1, max_length=255)
    delivery_memo: str | None = Field(default=None, max_length=255)
    is_default: bool = False

    @field_validator("recipient_name")
    @classmethod
    def validate_recipient_name(cls, value: str) -> str:
        return normalize_recipient_name(value)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("postal_code")
    @classmethod
    def validate_postal_code(cls, value: str) -> str:
        return normalize_postal_code(value)

    @field_validator("address1", "address2")
    @classmethod
    def validate_required_address(cls, value: str, info) -> str:
        return normalize_required_address(value, info.field_name)


class UserAddressUpdateRequest(BaseModel):
    recipient_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, min_length=1, max_length=30)
    postal_code: str | None = Field(default=None, min_length=1, max_length=20)
    address1: str | None = Field(default=None, min_length=1, max_length=255)
    address2: str | None = Field(default=None, min_length=1, max_length=255)
    delivery_memo: str | None = Field(default=None, max_length=255)
    is_default: bool | None = None

    @field_validator("recipient_name")
    @classmethod
    def validate_recipient_name(cls, value: str | None) -> str | None:
        return normalize_recipient_name(value) if value is not None else None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        return normalize_phone(value) if value is not None else None

    @field_validator("postal_code")
    @classmethod
    def validate_postal_code(cls, value: str | None) -> str | None:
        return normalize_postal_code(value) if value is not None else None

    @field_validator("address1", "address2")
    @classmethod
    def validate_required_address(cls, value: str | None, info) -> str | None:
        return normalize_required_address(value, info.field_name) if value is not None else None

    @model_validator(mode="after")
    def require_submitted_required_values(self) -> "UserAddressUpdateRequest":
        required_fields = ("recipient_name", "phone", "postal_code", "address1", "address2")
        for field_name in required_fields:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} is required")
        return self


class UserAddressResponse(BaseModel):
    id: int
    recipient_name: str
    phone: str
    postal_code: str
    address1: str
    address2: str | None
    delivery_memo: str | None
    is_default: bool
    created_at: datetime
    updated_at: datetime


class UserAddressesResponse(BaseModel):
    items: list[UserAddressResponse]


class DeleteUserAddressResponse(BaseModel):
    success: bool
