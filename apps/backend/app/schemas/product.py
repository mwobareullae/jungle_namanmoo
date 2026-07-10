from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.recommendation import CartHandoff, ScoreBreakdown


class ProductInfo(BaseModel):
    product_id: str
    brand: str
    name: str
    thumbnail_url: str
    lowest_price: int
    total_score: int | None = None
    reason_summary: str | None = None
    recommended_key_ingredients: list[str] = Field(default_factory=list)
    score_breakdown: ScoreBreakdown | None = None
    cart_handoff: CartHandoff | None = None


class ProductImage(BaseModel):
    image_type: str
    storage_key: str
    display_order: int
    alt: str


class ProductPrice(BaseModel):
    mall_name: str
    price: int
    product_url: str
    is_lowest: bool


class ProductPurchaseInfo(BaseModel):
    seller_code: str
    seller_name: str
    seller_type: str
    price: int | None
    currency: str | None
    purchase_url: str | None
    can_purchase: bool
    sales_status: str
    stock_status: str
    available_quantity: int | None


class ProductPopularityMetrics(BaseModel):
    view_count: int
    click_count: int
    cart_add_count: int
    order_count: int
    units_sold: int
    wishlist_add_count: int
    checkout_start_count: int
    paid_order_count: int
    home_product_impression_count: int
    home_product_click_count: int
    search_result_impression_count: int
    search_result_click_count: int
    wishlist_remove_count: int
    cart_remove_count: int
    cart_quantity_change_count: int
    payment_failed_count: int
    order_cancel_count: int
    review_count: int
    average_rating: float | None


class PopularProductItem(BaseModel):
    product_id: str
    brand: str
    name: str
    category_code: str
    category_name: str
    thumbnail_url: str
    lowest_price: int
    purchase_url: str | None
    popularity_score: float
    score_version: str
    computed_at: datetime
    metrics: ProductPopularityMetrics


class PopularProductsResponse(BaseModel):
    window_days: int
    items: list[PopularProductItem]


class ProductSearchItem(BaseModel):
    product_id: str
    brand: str
    name: str
    category_code: str
    category_name: str
    thumbnail_url: str
    lowest_price: int
    search_score: float | None = None
    match_source: str


class ProductSearchPagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool


class ProductSearchDiagnostics(BaseModel):
    backend: str
    fallback_used: bool
    es_attempted: bool
    es_failure_reason: str | None = None
    es_duration_ms: int | None = None
    vector_attempted: bool = False
    vector_failure_reason: str | None = None
    vector_duration_ms: int | None = None
    vector_result_count: int = 0
    vector_embedding_coverage: float | None = None


class ProductSearchResponse(BaseModel):
    query: str
    items: list[ProductSearchItem]
    pagination: ProductSearchPagination
    diagnostics: ProductSearchDiagnostics


class ProductIngredient(BaseModel):
    name: str
    purpose: str
    risk_note: str | None = None


class IngredientEvidence(BaseModel):
    ingredient: str
    effect: str
    description: str
    source_title: str


class ProductEvidence(BaseModel):
    ingredient_evidence: list[IngredientEvidence]
    recommendation_reason: str | None = None


class SourceInfo(BaseModel):
    title: str
    url: str
    source_type: str


class ProductDetailResponse(BaseModel):
    product: ProductInfo
    images: list[ProductImage]
    prices: list[ProductPrice]
    purchase_info: ProductPurchaseInfo
    ingredients: list[ProductIngredient]
    evidence: ProductEvidence
    sources: list[SourceInfo]
