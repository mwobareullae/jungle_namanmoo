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


class OrderCancelResponse(BaseModel):
    order_code: str
    status: str
    request_code: str | None = None


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
