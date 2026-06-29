export type SkinType = "건성" | "지성" | "복합성" | "수부지" | "중성";

export type Sensitivity = "낮음" | "보통" | "높음";

export type SortOption = "score" | "price" | "risk";

export type ContentConfidence = "high" | "medium" | "low" | "unknown";

export type MatchedCategoryConstraint = {
  category_code: string;
  name: string;
  matched_text: string;
};

export type MatchedBrandConstraint = {
  brand_code: string;
  name: string;
  matched_text: string;
};

export type PurchaseConstraints = {
  categories: MatchedCategoryConstraint[];
  brands: MatchedBrandConstraint[];
  price_min: number | null;
  price_max: number | null;
  price_text: string | null;
  price_max_text: string | null;
};

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
  keyword_score: number;
  vector_score: number;
  search_match_score: number;
  risk_penalty: number;
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
  concern_text: string;
  skin_type: string;
  sensitivity: string;
  avoid_ingredients: string[];
  concerns: string[];
  effects: string[];
  purchase_constraints: PurchaseConstraints;
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
  source_title: string | null;
};

export type ProductPrice = {
  mall_name: string;
  price: number;
  product_url: string;
  is_lowest: boolean;
};

export type ProductSource = {
  title: string;
  url: string;
  source_type: string;
};

export type ProductDetail = ProductCardItem & {
  image_urls: string[];
  content_confidence: ContentConfidence;
  related_ingredients: string[];
  purchase_url: string | null;
  evidence: IngredientEvidence[];
  prices: ProductPrice[];
  sources: ProductSource[];
};

export type ApiError = {
  status: number;
  message: string;
};
