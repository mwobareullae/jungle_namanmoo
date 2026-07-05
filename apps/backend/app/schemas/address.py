from datetime import datetime

from pydantic import BaseModel, Field


class UserAddressCreateRequest(BaseModel):
    recipient_name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=1, max_length=30)
    postal_code: str = Field(..., min_length=1, max_length=20)
    address1: str = Field(..., min_length=1, max_length=255)
    address2: str | None = Field(default=None, max_length=255)
    delivery_memo: str | None = Field(default=None, max_length=255)
    is_default: bool = False


class UserAddressUpdateRequest(BaseModel):
    recipient_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, min_length=1, max_length=30)
    postal_code: str | None = Field(default=None, min_length=1, max_length=20)
    address1: str | None = Field(default=None, min_length=1, max_length=255)
    address2: str | None = Field(default=None, max_length=255)
    delivery_memo: str | None = Field(default=None, max_length=255)
    is_default: bool | None = None


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
