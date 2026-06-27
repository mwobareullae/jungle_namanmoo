import { mockRecommendationApi } from "../mocks/recommendation";
import type {
  ApiError,
  ProductCardItem,
  ProductDetail,
  RecommendationRequest,
  RecommendationResponse,
  ScoreBreakdown
} from "../types/recommendation";

type RecommendationApi = {
  createRecommendation: (request: RecommendationRequest) => Promise<RecommendationResponse>;
  getProduct: (productId: string, recommendationId?: string) => Promise<ProductDetail>;
};

type BackendErrorResponse = {
  error?: {
    code?: string;
    message?: string;
  };
};

type BackendScoreBreakdown = {
  ingredient_effect_score: number;
  ingredient_evidence_score: number;
  skin_type_score: number;
  price_score: number;
  search_match_score?: number;
  risk_penalty?: number;
};

type BackendRecommendedProduct = {
  product_id: string;
  rank: number;
  total_score: number;
  reason_summary: string;
  brand: string;
  name: string;
  thumbnail_url: string;
  lowest_price: number;
  evidence_tags: string[];
  key_ingredients: string[];
  score_breakdown: BackendScoreBreakdown;
};

type BackendRecommendationResponse = {
  recommendation_id: string;
  summary: {
    concern_text: string;
    skin_type: string;
    sensitivity: string;
    avoid_ingredients: string[];
    matched_concerns: string[];
    expected_effects: string[];
  };
  unmatched_terms: string[];
  products: BackendRecommendedProduct[];
};

type BackendProductDetailResponse = {
  product: {
    product_id: string;
    brand: string;
    name: string;
    thumbnail_url: string;
    lowest_price: number;
    total_score?: number | null;
    reason_summary?: string | null;
    score_breakdown?: BackendScoreBreakdown | null;
  };
  images: {
    url: string;
    alt: string;
  }[];
  prices: {
    mall_name: string;
    price: number;
    product_url: string;
    is_lowest: boolean;
  }[];
  ingredients: {
    name: string;
    purpose: string;
    risk_note?: string | null;
  }[];
  evidence: {
    ingredient_evidence: {
      ingredient: string;
      effect: string;
      description: string;
      source_title: string;
    }[];
    recommendation_reason?: string | null;
  };
  sources: {
    title: string;
    url: string;
    source_type: string;
  }[];
};

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api").replace(
  /\/$/,
  ""
);

const useMockApi = import.meta.env.VITE_USE_MOCK_API !== "false";

const mapScoreBreakdown = (score?: BackendScoreBreakdown | null): ScoreBreakdown | undefined => {
  if (!score) {
    return undefined;
  }

  return {
    ingredient_effect_score: score.ingredient_effect_score,
    ingredient_evidence_score: score.ingredient_evidence_score,
    skin_type_match_score: score.skin_type_score,
    price_value_score: score.price_score
  };
};

const mapProductCard = (product: BackendRecommendedProduct): ProductCardItem => ({
  product_id: product.product_id,
  rank: product.rank,
  total_score: product.total_score,
  reason_summary: product.reason_summary,
  brand: product.brand,
  name: product.name,
  thumbnail_url: product.thumbnail_url || null,
  lowest_price: product.lowest_price ?? null,
  evidence_tags: product.evidence_tags,
  key_ingredients: product.key_ingredients,
  risk_flags: [],
  score_breakdown: mapScoreBreakdown(product.score_breakdown)
});

const mapRecommendation = (response: BackendRecommendationResponse): RecommendationResponse => ({
  recommendation_id: response.recommendation_id,
  summary: {
    concerns: response.summary.matched_concerns,
    effects: response.summary.expected_effects
  },
  unmatched_terms: response.unmatched_terms,
  products: response.products.map(mapProductCard)
});

const mapProductDetail = (response: BackendProductDetailResponse): ProductDetail => {
  const lowestPrice = response.prices.find((price) => price.is_lowest) ?? response.prices[0];
  const evidenceTags = Array.from(
    new Set(response.evidence.ingredient_evidence.map((item) => item.effect))
  );
  const keyIngredients = response.ingredients.map((ingredient) => ingredient.name);
  const riskFlags = response.ingredients
    .filter((ingredient) => ingredient.risk_note)
    .map((ingredient) => `${ingredient.name}: ${ingredient.risk_note}`);

  return {
    product_id: response.product.product_id,
    rank: 0,
    total_score: response.product.total_score ?? 0,
    reason_summary:
      response.product.reason_summary ??
      response.evidence.recommendation_reason ??
      "추천 근거를 준비 중입니다.",
    brand: response.product.brand,
    name: response.product.name,
    thumbnail_url: response.product.thumbnail_url || response.images[0]?.url || null,
    lowest_price: response.product.lowest_price ?? lowestPrice?.price ?? null,
    evidence_tags: evidenceTags.length > 0 ? evidenceTags : ["근거 없음"],
    key_ingredients: keyIngredients,
    risk_flags: riskFlags,
    score_breakdown: mapScoreBreakdown(response.product.score_breakdown),
    image_urls: response.images.map((image) => image.url),
    content_confidence:
      response.evidence.ingredient_evidence.length >= 2
        ? "medium"
        : response.evidence.ingredient_evidence.length === 1
          ? "low"
          : "unknown",
    related_ingredients: keyIngredients,
    purchase_url: lowestPrice?.product_url ?? null,
    evidence: response.evidence.ingredient_evidence.map((item) => ({
      ingredient_name: item.ingredient,
      effect_name: item.effect,
      evidence_level: "medium",
      evidence_text: item.description
    }))
  };
};

const parseJson = async <T>(response: Response): Promise<T> => {
  const body = (await response.json().catch(() => null)) as T | BackendErrorResponse | null;

  if (!response.ok) {
    const errorBody = body as BackendErrorResponse | null;
    const apiError: ApiError = {
      status: response.status,
      message: errorBody?.error?.message ?? "API 요청에 실패했습니다."
    };
    throw apiError;
  }

  return body as T;
};

const realRecommendationApi: RecommendationApi = {
  async createRecommendation(request) {
    const response = await fetch(`${apiBaseUrl}/recommendations`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(request)
    });
    return mapRecommendation(await parseJson<BackendRecommendationResponse>(response));
  },

  async getProduct(productId, recommendationId) {
    const searchParams = new URLSearchParams();
    if (recommendationId) {
      searchParams.set("recommendation_id", recommendationId);
    }

    const query = searchParams.toString();
    const response = await fetch(`${apiBaseUrl}/products/${productId}${query ? `?${query}` : ""}`);
    return mapProductDetail(await parseJson<BackendProductDetailResponse>(response));
  }
};

export const api: RecommendationApi = useMockApi ? mockRecommendationApi : realRecommendationApi;
