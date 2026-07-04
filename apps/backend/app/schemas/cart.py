from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CartItemAddRequest(BaseModel):
    product_id: str
    quantity: int = Field(default=1, ge=1, le=99)
    source: str | None = Field(default="product_detail", max_length=64)
    recommendation_id: str | None = Field(default=None, max_length=128)
    recommendation_rank: int | None = Field(default=None, ge=1)


class CartItemUpdateRequest(BaseModel):
    quantity: int = Field(..., ge=0, le=99)


class CartProduct(BaseModel):
    product_id: str
    brand: str
    name: str
    category_code: str
    category_name: str
    thumbnail_url: str
    current_price: int | None
    currency: str
    sales_status: str
    stock_status: str
    available_quantity: int | None


class CartWarning(BaseModel):
    code: str
    message: str
    severity: Literal["INFO", "BLOCKING"]
    product_id: str | None = None
    item_id: int | None = None


class CartItem(BaseModel):
    id: int
    product_id: str
    quantity: int
    unit_price_snapshot: int
    current_unit_price: int | None
    currency: str
    line_subtotal: int
    price_changed: bool
    source: str | None = None
    recommendation_id: str | None = None
    recommendation_rank: int | None = None
    added_at: datetime
    updated_at: datetime
    product: CartProduct


class CartResponse(BaseModel):
    cart_id: int | None
    owner_type: Literal["user", "anonymous"]
    items: list[CartItem]
    total_quantity: int
    subtotal: int
    currency: str
    warnings: list[CartWarning]


class DeleteCartItemResponse(BaseModel):
    success: bool
    cart: CartResponse


class CartMergeResponse(BaseModel):
    merged: bool
    cart: CartResponse


class CheckoutPreviewResponse(BaseModel):
    cart_id: int
    items: list[CartItem]
    subtotal: int
    shipping_fee: int
    total: int
    currency: str
    can_checkout: bool
    warnings: list[CartWarning]
