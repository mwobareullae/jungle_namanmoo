from typing import Literal

from pydantic import BaseModel, Field


class MatchedCategoryConstraint(BaseModel):
    category_code: str
    name: str
    matched_text: str


class MatchedBrandConstraint(BaseModel):
    brand_code: str
    name: str
    matched_text: str


class PurchaseConstraints(BaseModel):
    categories: list[MatchedCategoryConstraint]
    brands: list[MatchedBrandConstraint]
    price_min: int | None = None
    price_max: int | None = None
    price_text: str | None = None
    price_max_text: str | None = None


class RecommendationRequest(BaseModel):
    concern_text: str | None = None
    skin_type: str | None = None
    sensitivity: str | None = None
    avoid_ingredients: list[str] | None = None


class RecommendationSummary(BaseModel):
    concern_text: str
    skin_type: str
    sensitivity: str
    avoid_ingredients: list[str]
    matched_concerns: list[str]
    expected_effects: list[str]
    purchase_constraints: PurchaseConstraints


class ScoreBreakdown(BaseModel):
    ingredient_effect_score: int
    ingredient_evidence_score: int
    functional_claim_score: int = 0
    concentration_fit_score: int = 50
    concentration_bucket: str | None = None
    concentration_warning: str | None = None
    skin_profile_score: int = 0
    skin_type_score: int
    sensitivity_score: int = 0
    price_score: int
    keyword_score: int = 0
    vector_score: int = 0
    search_match_score: int
    risk_penalty: int
    risk_flag_count: int = 0
    risk_warnings: list[str] = Field(default_factory=list)
    risk_policy: str | None = None


class CartHandoff(BaseModel):
    product_id: str
    quantity: int = 1
    source: Literal["ai_recommendation"] = "ai_recommendation"
    recommendation_id: str
    recommendation_rank: int


class RecommendedProduct(BaseModel):
    product_id: str
    rank: int
    total_score: int
    reason_summary: str
    brand: str
    name: str
    thumbnail_url: str
    lowest_price: int
    evidence_tags: list[str]
    key_ingredients: list[str]
    score_breakdown: ScoreBreakdown
    cart_handoff: CartHandoff


class Pagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool


class RecommendationResponse(BaseModel):
    recommendation_id: str
    summary: RecommendationSummary
    unmatched_terms: list[str]
    products: list[RecommendedProduct]
    pagination: Pagination


class RecommendationNarrativeRequest(BaseModel):
    mode: str = "community_beta"
    view: Literal["cards", "detail", "full"] = "cards"
    product_id: str | None = None
    product_limit: int = Field(default=5, ge=1, le=10)
    use_llm: bool = True


class RecommendationNarrativeOverview(BaseModel):
    headline: str
    summary: str
    key_points: list[str]


class RecommendationNarrativeCard(BaseModel):
    headline: str
    reason: str
    chips: list[str]


class RecommendationNarrativeDetailSection(BaseModel):
    title: str
    body: str


class RecommendationNarrativeProduct(BaseModel):
    product_id: str
    rank: int
    role: str
    cart_handoff: CartHandoff
    card: RecommendationNarrativeCard
    detail_sections: list[RecommendationNarrativeDetailSection]
    caution: str | None = None


class RecommendationNarrative(BaseModel):
    generation_source: str
    fallback_reason: str | None = None
    overview: RecommendationNarrativeOverview
    product_explanations: list[RecommendationNarrativeProduct]
    selection_guide: str | None = None


class RecommendationNarrativeResponse(BaseModel):
    recommendation_id: str
    narrative: RecommendationNarrative
