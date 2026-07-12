from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ProductListingSort(str, Enum):
    POPULAR = "popular"
    NEWEST = "newest"
    PRICE_LOW = "price_low"
    PRICE_HIGH = "price_high"
    RATING = "rating"
    REVIEW_COUNT = "review_count"


class ProductListingItem(BaseModel):
    product_id: str
    brand_code: str
    brand: str
    name: str
    category_code: str
    category_group: str
    category_name: str
    thumbnail_url: str
    lowest_price: int | None
    rating: float | None
    review_count: int
    sales_status: str
    in_stock: bool
    released_at: datetime | None


class ProductListingPagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool


class ProductListingAppliedFilters(BaseModel):
    brand_codes: list[str]
    category_codes: list[str]
    category_groups: list[str]
    min_price: int | None
    max_price: int | None
    min_rating: float | None
    in_stock: bool | None


class ProductListingResponse(BaseModel):
    items: list[ProductListingItem]
    pagination: ProductListingPagination
    applied_filters: ProductListingAppliedFilters
    sort: ProductListingSort


class CategoryListItem(BaseModel):
    code: str
    name: str
    group: str
    group_name: str
    product_count: int


class CategoryListResponse(BaseModel):
    items: list[CategoryListItem]


class BrandListItem(BaseModel):
    code: str
    name: str
    product_count: int


class BrandListResponse(BaseModel):
    items: list[BrandListItem]
    pagination: ProductListingPagination
