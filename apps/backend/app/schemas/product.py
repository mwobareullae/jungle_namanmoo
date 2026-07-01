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
    url: str
    alt: str


class ProductPrice(BaseModel):
    mall_name: str
    price: int
    product_url: str
    is_lowest: bool


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
    ingredients: list[ProductIngredient]
    evidence: ProductEvidence
    sources: list[SourceInfo]
