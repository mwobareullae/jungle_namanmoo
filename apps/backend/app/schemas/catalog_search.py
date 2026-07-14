from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class CatalogSearchSort(str, Enum):
    RELEVANCE = "relevance"
    POPULAR = "popular"
    NEWEST = "newest"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    RATING = "rating"


class CatalogSearchItem(BaseModel):
    product_id: str
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
    stock_status: str = "UNKNOWN"
    available_quantity: int | None = None
    in_stock: bool = False


class CatalogSearchPagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool


class CatalogSearchFacetItem(BaseModel):
    value: str
    label: str
    count: int


class CatalogSearchFacets(BaseModel):
    brands: list[CatalogSearchFacetItem]
    categories: list[CatalogSearchFacetItem]
    features: list[CatalogSearchFacetItem]
    skin_types: list[CatalogSearchFacetItem]
    price_ranges: list[CatalogSearchFacetItem]
    availability: list[CatalogSearchFacetItem]


class CatalogSearchAppliedFilters(BaseModel):
    brands: list[str]
    categories: list[str]
    features: list[str]
    skin_types: list[str]
    min_price: int | None
    max_price: int | None
    min_rating: float | None
    in_stock: bool | None


class CatalogSearchResponse(BaseModel):
    query: str
    corrected_query: str | None
    items: list[CatalogSearchItem]
    pagination: CatalogSearchPagination
    facets: CatalogSearchFacets
    applied_filters: CatalogSearchAppliedFilters
    sort: CatalogSearchSort


class CatalogSuggestionType(str, Enum):
    PRODUCT = "PRODUCT"
    BRAND = "BRAND"
    CATEGORY = "CATEGORY"
    CORRECTION = "CORRECTION"


class CatalogSuggestionItem(BaseModel):
    text: str
    type: CatalogSuggestionType
    product_id: str | None = None


class CatalogSuggestionsResponse(BaseModel):
    query: str
    items: list[CatalogSuggestionItem]
