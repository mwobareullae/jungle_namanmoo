from pydantic import BaseModel


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


class ScoreBreakdown(BaseModel):
    ingredient_effect_score: int
    ingredient_evidence_score: int
    skin_type_score: int
    price_score: int
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
