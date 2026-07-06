from datetime import datetime

from pydantic import BaseModel

from app.schemas.recommendation import CartHandoff, ScoreBreakdown


class ProductInfo(BaseModel):
    product_id: str
    brand: str
    name: str
    thumbnail_url: str
    lowest_price: int
    total_score: int | None = None
    reason_summary: str | None = None
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
