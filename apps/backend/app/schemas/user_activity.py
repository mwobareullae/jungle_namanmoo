from datetime import datetime

from pydantic import BaseModel


class UserActivityProduct(BaseModel):
    product_id: str
    brand: str
    name: str
    category_code: str
    category_name: str
    thumbnail_url: str
    lowest_price: int
    sales_status: str = "UNKNOWN"
    stock_status: str = "UNKNOWN"
    available_quantity: int | None = None
    in_stock: bool = False


class WishlistRequest(BaseModel):
    product_id: str


class WishlistItem(BaseModel):
    id: int
    product_id: str
    added_at: datetime
    product: UserActivityProduct


class WishlistResponse(BaseModel):
    items: list[WishlistItem]


class RecentViewRequest(BaseModel):
    product_id: str


class RecentViewItem(BaseModel):
    id: int
    product_id: str
    viewed_at: datetime
    product: UserActivityProduct


class RecentViewsResponse(BaseModel):
    items: list[RecentViewItem]


class DeleteUserActivityResponse(BaseModel):
    success: bool
