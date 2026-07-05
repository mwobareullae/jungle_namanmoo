from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


PaymentProvider = Literal["MOCK", "TOSS", "KAKAO_PAY", "NAVER_PAY"]


class DirectShippingAddressRequest(BaseModel):
    recipient_name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=1, max_length=30)
    postal_code: str = Field(..., min_length=1, max_length=20)
    address1: str = Field(..., min_length=1, max_length=255)
    address2: str | None = Field(default=None, max_length=255)
    delivery_memo: str | None = Field(default=None, max_length=255)
    save_to_address_book: bool = False
    set_as_default: bool = False


class OrderCreateRequest(BaseModel):
    cart_item_ids: list[int]
    address_id: int | None = None
    shipping_address: DirectShippingAddressRequest | None = None
    payment_provider: PaymentProvider = "MOCK"


class OrderPaymentSummary(BaseModel):
    payment_code: str
    provider: PaymentProvider
    status: str
    amount: int
    currency: str


class OrderCreateResponse(BaseModel):
    order_code: str
    status: str
    payment: OrderPaymentSummary
    subtotal: int
    shipping_fee: int
    discount_total: int
    total: int
    currency: str
    payment_expires_at: datetime | None
