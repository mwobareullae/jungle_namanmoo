export type SkinType = "건성" | "지성" | "복합성" | "수부지" | "중성";

export type Sensitivity = "낮음" | "보통" | "높음";

export type SortOption = "score" | "price" | "risk";

export type ContentConfidence = "high" | "medium" | "low" | "unknown";

export type RecommendationRequest = {
  skin_type: SkinType;
  sensitivity: Sensitivity;
  avoid_ingredients: string[];
  concern_text: string;
};

export type ScoreBreakdown = {
  ingredient_effect_score: number;
  ingredient_evidence_score: number;
  skin_type_match_score: number;
  price_value_score: number;
};

export type ProductCardItem = {
  product_id: string;
  rank: number;
  total_score: number;
  reason_summary: string;
  brand: string;
  name: string;
  thumbnail_url: string | null;
  lowest_price: number | null;
  evidence_tags: string[];
  key_ingredients: string[];
  risk_flags: string[];
  score_breakdown?: ScoreBreakdown;
};

export type RecommendationSummary = {
  concerns: string[];
  effects: string[];
};

export type RecommendationResponse = {
  recommendation_id: string;
  summary: RecommendationSummary;
  unmatched_terms: string[];
  products: ProductCardItem[];
};

export type IngredientEvidence = {
  ingredient_name: string;
  effect_name: string;
  evidence_level: "high" | "medium" | "low";
  evidence_text: string;
};

export type ProductDetail = ProductCardItem & {
  image_urls: string[];
  content_confidence: ContentConfidence;
  related_ingredients: string[];
  purchase_url: string | null;
  evidence: IngredientEvidence[];
};

export type ApiError = {
  status: number;
  message: string;
};
