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

export type RecommendationProfile = {
  skin: SkinType;
  sensitivity: Sensitivity;
  avoidIngredients: string[];
};

export type ScoreBreakdown = {
  ingredient_effect_score: number;
  ingredient_evidence_score: number;
  concentration_fit_score: number;
  concentration_bucket: string | null;
  concentration_warning: string | null;
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

export type HomeSectionProduct = {
  product_id: string;
  brand: string;
  name: string;
  category_code: string;
  category_name: string;
  thumbnail_url: string | null;
  lowest_price: number | null;
  original_price: number | null;
  discount_rate: number | null;
  purchase_url: string | null;
  badges: string[];
  tags: string[];
  reason_summary: string;
  display_score: number;
};

export type HomeSection = {
  section_id: string;
  title: string;
  subtitle: string;
  section_type: string;
  algorithm: string;
  category_code: string | null;
  limit: number;
  products: HomeSectionProduct[];
  skin_type: string | null;
  sensitivity: string | null;
  personalization_sources: string[];
};

export type HomeLayoutSection = {
  section_id: string;
  title: string;
  subtitle: string;
  section_type: string;
  endpoint: string;
  lazy_load: boolean;
};

export type HomeLayoutResponse = {
  sections: HomeLayoutSection[];
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
  pagination: RecommendationPagination;
};

export type RecommendationNarrativeRequest = {
  mode?: string;
  view?: "cards" | "detail" | "full";
  product_id?: string;
  product_limit?: number;
  use_llm?: boolean;
};

export type RecommendationNarrativeOverview = {
  headline: string;
  summary: string;
  key_points: string[];
};

export type RecommendationNarrativeCard = {
  headline: string;
  reason: string;
  chips: string[];
};

export type RecommendationNarrativeDetailSection = {
  title: string;
  body: string;
};

export type RecommendationNarrativeProduct = {
  product_id: string;
  rank: number;
  role: string;
  card: RecommendationNarrativeCard;
  detail_sections: RecommendationNarrativeDetailSection[];
  caution: string | null;
};

export type RecommendationNarrativeResponse = {
  recommendation_id: string;
  narrative: {
    generation_source: string;
    fallback_reason: string | null;
    overview: RecommendationNarrativeOverview;
    product_explanations: RecommendationNarrativeProduct[];
    selection_guide: string | null;
  };
};

export type RecommendationPagination = {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
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

export type ProductIngredient = {
  name: string;
  purpose: string;
  risk_note: string | null;
};

export type ProductPurchaseInfo = {
  seller_code: string;
  seller_name: string;
  seller_type: string;
  price: number | null;
  currency: string | null;
  purchase_url: string | null;
  can_purchase: boolean;
  sales_status: string;
  stock_status: string;
  available_quantity: number | null;
};

export type ProductDetail = ProductCardItem & {
  image_urls: string[];
  content_confidence: ContentConfidence;
  related_ingredients: string[];
  ingredients: ProductIngredient[];
  purchase_url: string | null;
  purchase_info?: ProductPurchaseInfo;
  evidence: IngredientEvidence[];
  prices: ProductPrice[];
  sources: ProductSource[];
};

export type ApiError = {
  code?: string;
  status: number;
  message: string;
};
