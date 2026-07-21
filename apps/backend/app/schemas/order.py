from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.shipping_address import (
    normalize_phone,
    normalize_postal_code,
    normalize_recipient_name,
    normalize_optional_address,
    normalize_required_address,
)

PaymentProvider = Literal["MOCK", "TOSS", "KAKAO_PAY", "NAVER_PAY"]
OrderCancelReasonCode = Literal[
    "CHANGE_OF_MIND",
    "ORDER_MISTAKE",
    "ORDER_INFO_CHANGE",
    "DELIVERY_DELAY",
    "OTHER",
]
OrderCancelRequestStatus = Literal["REQUESTED", "APPROVED", "REJECTED"]


class DirectShippingAddressRequest(BaseModel):
    recipient_name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=1, max_length=30)
    postal_code: str = Field(..., min_length=1, max_length=20)
    address1: str = Field(..., min_length=1, max_length=255)
    address2: str | None = Field(default=None, max_length=255)
    delivery_memo: str | None = Field(default=None, max_length=255)
    save_to_address_book: bool = False
    set_as_default: bool = False

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

    @field_validator("address1")
    @classmethod
    def validate_required_address(cls, value: str, info) -> str:
        return normalize_required_address(value, info.field_name)

    @field_validator("address2")
    @classmethod
    def validate_optional_address(cls, value: str | None) -> str | None:
        return normalize_optional_address(value)


class OrderCreateRequest(BaseModel):
    cart_item_ids: list[int]
    address_id: int | None = None
    shipping_address: DirectShippingAddressRequest | None = None
    payment_provider: PaymentProvider = "TOSS"


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
    order_snapshot: "OrderDetailResponse | None" = None


class OrderCancelResponse(BaseModel):
    order_code: str
    status: str
    request_code: str | None = None


class OrderCancelRequestBody(BaseModel):
    reason_code: OrderCancelReasonCode
    reason_detail: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_other_reason_detail(self) -> "OrderCancelRequestBody":
        if self.reason_code == "OTHER" and not (self.reason_detail or "").strip():
            raise ValueError("reason_detail is required when reason_code is OTHER")
        return self


class OrderCancelRequestDetail(BaseModel):
    request_code: str
    status: OrderCancelRequestStatus
    reason_code: OrderCancelReasonCode | None
    reason_detail: str | None
    decision_reason: str | None
    requested_at: datetime
    processed_at: datetime | None
    payment_canceled_at: datetime | None


class OrderListItem(BaseModel):
    order_code: str
    status: str
    total: int
    currency: str
    item_count: int
    ordered_at: datetime
    paid_at: datetime | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    thumbnail_storage_key: str | None
    title: str


class OrderListResponse(BaseModel):
    items: list[OrderListItem]
    next_cursor: str | None


class OrderSummaryResponse(BaseModel):
    """Current user's order counts grouped by the persisted order status."""

    status_counts: dict[str, int]


class OrderDetailPayment(BaseModel):
    payment_code: str
    provider: PaymentProvider
    status: str
    approved_at: datetime | None


class OrderDetailItem(BaseModel):
    id: int
    product_id: str
    product_name: str
    brand_name: str
    seller_name: str
    thumbnail_storage_key: str | None
    unit_price: int
    quantity: int
    line_subtotal: int
    line_discount_amount: int
    line_total: int
    currency: str
    status: str
    source: str | None
    recommendation_id: str | None
    recommendation_rank: int | None


class OrderDetailShippingAddress(BaseModel):
    recipient_name: str
    phone: str
    postal_code: str
    address1: str
    address2: str | None
    delivery_memo: str | None


class OrderDetailShippingGroup(BaseModel):
    seller_name: str
    item_subtotal: int
    shipping_fee: int
    free_shipping_threshold: int | None


class OrderDetailResponse(BaseModel):
    order_code: str
    status: str
    subtotal: int
    shipping_fee: int
    discount_total: int
    total: int
    currency: str
    ordered_at: datetime
    paid_at: datetime | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    payment_expires_at: datetime | None
    payment: OrderDetailPayment
    items: list[OrderDetailItem]
    shipping_address: OrderDetailShippingAddress | None
    shipping_groups: list[OrderDetailShippingGroup]
    cancel_request: OrderCancelRequestDetail | None = None
