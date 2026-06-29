from pydantic import BaseModel


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
    concentration_fit_score: int = 50
    concentration_bucket: str | None = None
    concentration_warning: str | None = None
    skin_type_score: int
    price_score: int
    keyword_score: int = 0
    vector_score: int = 0
    search_match_score: int
    risk_penalty: int


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


class RecommendationResponse(BaseModel):
    recommendation_id: str
    summary: RecommendationSummary
    unmatched_terms: list[str]
    products: list[RecommendedProduct]
