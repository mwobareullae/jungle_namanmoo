import type {
  ApiError,
  HomeSection,
  ProductCardItem,
  ProductDetail,
  ProductIngredient,
  PurchaseConstraints,
  RecommendationNarrativeRequest,
  RecommendationNarrativeResponse,
  RecommendationRequest,
  RecommendationResponse,
  ScoreBreakdown
} from "../types/recommendation";
import type {
  ApplySkinTestResultResponse,
  SkinTestQuestionsResponse,
  SkinTestResultResponse,
  SkinTestSubmitRequest,
  SkinTestSubmitResponse
} from "../types/skinTest";
import type {
  AgentChatRequest,
  AgentChatResponse,
  AgentToolConfirmRequest,
  AgentToolConfirmResponse
} from "../types/agent";
import type { PopularProductsResponse } from "../types/product";
import { getProductImageUrl } from "./imageUrls";

type RecommendationApi = {
  createRecommendation: (
    request: RecommendationRequest,
    params?: { page?: number; pageSize?: number }
  ) => Promise<RecommendationResponse>;
  getRecommendation: (
    recommendationId: string,
    params?: { page?: number; pageSize?: number }
  ) => Promise<RecommendationResponse>;
  createRecommendationNarrative: (
    recommendationId: string,
    request?: RecommendationNarrativeRequest
  ) => Promise<RecommendationNarrativeResponse>;
  getMarketPopular: (params?: { categoryCode?: string | null; limit?: number }) => Promise<HomeSection>;
  getEvidencePicks: (params?: { categoryCode?: string | null; limit?: number }) => Promise<HomeSection>;
  getForYou: (params?: {
    skinType?: string;
    sensitivity?: string;
    concern?: string;
    effect?: string;
    categoryCode?: string | null;
    limit?: number;
  }) => Promise<HomeSection>;
  searchCatalogProducts: (params: { page?: number; pageSize?: number; query: string }) => Promise<RecommendationResponse>;
  getPopularProducts: (params?: { categoryCode?: string; limit?: number }) => Promise<PopularProductsResponse>;
  getProduct: (productId: string, recommendationId?: string) => Promise<ProductDetail>;
  getSkinTestQuestions: () => Promise<SkinTestQuestionsResponse>;
  submitSkinTest: (request: SkinTestSubmitRequest) => Promise<SkinTestSubmitResponse>;
  getSkinTestResult: (resultId: number) => Promise<SkinTestResultResponse>;
  applySkinTestResult: (resultId: number) => Promise<ApplySkinTestResultResponse>;
  sendAgentMessage: (request: AgentChatRequest) => Promise<AgentChatResponse>;
  confirmAgentToolCall: (
    toolCallId: string,
    request: AgentToolConfirmRequest
  ) => Promise<AgentToolConfirmResponse>;
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
  concentration_fit_score?: number;
  concentration_bucket?: string | null;
  concentration_warning?: string | null;
  skin_type_score: number;
  price_score: number;
  keyword_score?: number;
  vector_score?: number;
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

type BackendPurchaseConstraints = {
  categories: {
    category_code: string;
    name: string;
    matched_text: string;
  }[];
  brands: {
    brand_code: string;
    name: string;
    matched_text: string;
  }[];
  price_min: number | null;
  price_max: number | null;
  price_text: string | null;
  price_max_text: string | null;
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
    purchase_constraints: BackendPurchaseConstraints;
  };
  unmatched_terms: string[];
  products: BackendRecommendedProduct[];
  pagination: {
    page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
    has_next: boolean;
    has_prev: boolean;
  };
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
    recommended_key_ingredients?: string[];
    score_breakdown?: BackendScoreBreakdown | null;
  };
  images: {
    image_type: string;
    storage_key: string;
    alt: string;
  }[];
  prices: {
    mall_name: string;
    price: number;
    product_url: string;
    is_lowest: boolean;
  }[];
  purchase_info: {
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

type BackendHomeSection = HomeSection;

type BackendCatalogSearchResponse = {
  items: Array<{
    brand: string;
    category_name: string;
    lowest_price: number | null;
    name: string;
    product_id: string;
    thumbnail_url: string | null;
  }>;
  pagination: { page: number; page_size: number; total_items: number; total_pages: number; has_next: boolean; has_prev: boolean };
  query: string;
};

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api").replace(
  /\/$/,
  ""
);

const requestTimeoutMs = 120000;

const emptyPurchaseConstraints: PurchaseConstraints = {
  categories: [],
  brands: [],
  price_min: null,
  price_max: null,
  price_text: null,
  price_max_text: null
};

const mapScoreBreakdown = (score?: BackendScoreBreakdown | null): ScoreBreakdown | undefined => {
  if (!score) {
    return undefined;
  }

  return {
    ingredient_effect_score: score.ingredient_effect_score,
    ingredient_evidence_score: score.ingredient_evidence_score,
    concentration_fit_score: score.concentration_fit_score ?? 50,
    concentration_bucket: score.concentration_bucket ?? null,
    concentration_warning: score.concentration_warning ?? null,
    skin_type_match_score: score.skin_type_score,
    price_value_score: score.price_score,
    keyword_score: score.keyword_score ?? 0,
    vector_score: score.vector_score ?? 0,
    search_match_score: score.search_match_score ?? 0,
    risk_penalty: score.risk_penalty ?? 0
  };
};

const mapProductCard = (product: BackendRecommendedProduct): ProductCardItem => ({
  product_id: product.product_id,
  rank: product.rank,
  total_score: product.total_score,
  reason_summary: product.reason_summary,
  brand: product.brand,
  name: product.name,
  thumbnail_url: getProductImageUrl(product.thumbnail_url, "w400") || null,
  lowest_price: product.lowest_price ?? null,
  evidence_tags: product.evidence_tags,
  key_ingredients: product.key_ingredients,
  risk_flags: [],
  score_breakdown: mapScoreBreakdown(product.score_breakdown)
});

const mapHomeSection = (section: BackendHomeSection): HomeSection => ({
  ...section,
  products: section.products.map((product) => ({
    ...product,
    thumbnail_url: getProductImageUrl(product.thumbnail_url, "w400") || null
  }))
});

const mapPopularProducts = (response: PopularProductsResponse): PopularProductsResponse => ({
  ...response,
  items: response.items.map((item) => ({
    ...item,
    thumbnail_url: getProductImageUrl(item.thumbnail_url, "w400") || ""
  }))
});

const mapRecommendation = (response: BackendRecommendationResponse): RecommendationResponse => ({
  recommendation_id: response.recommendation_id,
  summary: {
    concern_text: response.summary.concern_text,
    skin_type: response.summary.skin_type,
    sensitivity: response.summary.sensitivity,
    avoid_ingredients: response.summary.avoid_ingredients,
    concerns: response.summary.matched_concerns,
    effects: response.summary.expected_effects,
    purchase_constraints: response.summary.purchase_constraints ?? emptyPurchaseConstraints
  },
  unmatched_terms: response.unmatched_terms,
  products: response.products.map(mapProductCard),
  pagination: response.pagination
});

const mapProductIngredient = (
  ingredient: BackendProductDetailResponse["ingredients"][number]
): ProductIngredient => ({
  name: ingredient.name,
  purpose: ingredient.purpose,
  risk_note: ingredient.risk_note ?? null
});

const uniqueStrings = (values: string[]) =>
  Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));

const mapProductDetail = (response: BackendProductDetailResponse): ProductDetail => {
  const lowestPrice = response.prices.find((price) => price.is_lowest) ?? response.prices[0];
  const evidenceTags = Array.from(
    new Set(response.evidence.ingredient_evidence.map((item) => item.effect))
  );
  const recommendedKeyIngredients = uniqueStrings(response.product.recommended_key_ingredients ?? []);
  const evidenceKeyIngredients = uniqueStrings(
    response.evidence.ingredient_evidence.map((item) => item.ingredient)
  );
  const keyIngredients =
    recommendedKeyIngredients.length > 0
      ? recommendedKeyIngredients
      : evidenceKeyIngredients;
  const riskFlags = response.ingredients
    .filter((ingredient) => ingredient.risk_note)
    .map((ingredient) => `${ingredient.name}: ${ingredient.risk_note}`);
  const thumbnailUrl = getProductImageUrl(
    response.product.thumbnail_url || response.images[0]?.storage_key,
    "w400"
  );
  const imageUrls = response.images
    .map((image) =>
      getProductImageUrl(image.storage_key, image.image_type === "thumbnail" ? "w400" : "w1200")
    )
    .filter(Boolean);

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
    thumbnail_url: thumbnailUrl || imageUrls[0] || null,
    lowest_price: response.product.lowest_price ?? lowestPrice?.price ?? null,
    evidence_tags: evidenceTags.length > 0 ? evidenceTags : ["근거 없음"],
    key_ingredients: keyIngredients,
    risk_flags: riskFlags,
    score_breakdown: mapScoreBreakdown(response.product.score_breakdown),
    image_urls: imageUrls,
    content_confidence:
      response.evidence.ingredient_evidence.length >= 2
        ? "medium"
        : response.evidence.ingredient_evidence.length === 1
          ? "low"
          : "unknown",
    related_ingredients: keyIngredients,
    ingredients: response.ingredients.map(mapProductIngredient),
    purchase_url: lowestPrice?.product_url ?? null,
    purchase_info: response.purchase_info,
    evidence: response.evidence.ingredient_evidence.map((item) => ({
      ingredient_name: item.ingredient,
      effect_name: item.effect,
      evidence_level: "medium",
      evidence_text: item.description,
      source_title: item.source_title || null
    })),
    prices: response.prices,
    sources: response.sources
  };
};

export const fetchWithTimeout = async (input: RequestInfo | URL, init?: RequestInit) => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);

  try {
    return await fetch(input, {
      credentials: "include",
      ...init,
      signal: controller.signal
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      const apiError: ApiError = {
        status: 408,
        message: "분석 요청이 지연되고 있어요. 잠시 후 다시 시도해주세요."
      };
      throw apiError;
    }

    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
};

export const parseJson = async <T>(response: Response): Promise<T> => {
  const body = (await response.json().catch(() => null)) as T | BackendErrorResponse | null;

  if (!response.ok) {
    const errorBody = body as BackendErrorResponse | null;
    const apiError: ApiError = {
      code: errorBody?.error?.code,
      status: response.status,
      message: errorBody?.error?.message ?? "API 요청에 실패했습니다."
    };
    throw apiError;
  }

  return body as T;
};

export const api: RecommendationApi = {
  async createRecommendation(request, params = {}) {
    const searchParams = new URLSearchParams();
    if (params.page) searchParams.set("page", String(params.page));
    if (params.pageSize) searchParams.set("page_size", String(params.pageSize));
    const query = searchParams.toString();

    const response = await fetchWithTimeout(`${API_BASE_URL}/recommendations${query ? `?${query}` : ""}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(request)
    });
    return mapRecommendation(await parseJson<BackendRecommendationResponse>(response));
  },

  async getRecommendation(recommendationId, params = {}) {
    const searchParams = new URLSearchParams();
    if (params.page) searchParams.set("page", String(params.page));
    if (params.pageSize) searchParams.set("page_size", String(params.pageSize));

    const query = searchParams.toString();
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/recommendations/${encodeURIComponent(recommendationId)}${query ? `?${query}` : ""}`
    );
    return mapRecommendation(await parseJson<BackendRecommendationResponse>(response));
  },

  async createRecommendationNarrative(recommendationId, request = {}) {
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/recommendations/${encodeURIComponent(recommendationId)}/narrative`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(request)
      }
    );
    return parseJson<RecommendationNarrativeResponse>(response);
  },

  async searchCatalogProducts(params) {
    const searchParams = new URLSearchParams({ q: params.query });
    if (params.page) searchParams.set("page", String(params.page));
    if (params.pageSize) searchParams.set("page_size", String(params.pageSize));
    const response = await fetchWithTimeout(`${API_BASE_URL}/search/products?${searchParams.toString()}`);
    const data = await parseJson<BackendCatalogSearchResponse>(response);
    return {
      recommendation_id: "catalog-search",
      pagination: data.pagination,
      summary: {
        concern_text: data.query,
        skin_type: "",
        sensitivity: "",
        avoid_ingredients: [],
        concerns: [],
        effects: [],
        purchase_constraints: emptyPurchaseConstraints
      },
      unmatched_terms: [],
      products: data.items.map((item, index) => ({
        product_id: item.product_id,
        rank: (data.pagination.page - 1) * data.pagination.page_size + index + 1,
        total_score: 0,
        reason_summary: item.category_name,
        brand: item.brand,
        name: item.name,
        thumbnail_url: item.thumbnail_url,
        lowest_price: item.lowest_price,
        evidence_tags: [],
        key_ingredients: [],
        risk_flags: []
      }))
    };
  },

  async getMarketPopular(params = {}) {
    const searchParams = new URLSearchParams();
    if (params.categoryCode) searchParams.set("category_code", params.categoryCode);
    if (params.limit) searchParams.set("limit", String(params.limit));

    const query = searchParams.toString();
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/home/market-popular${query ? `?${query}` : ""}`
    );
    return mapHomeSection(await parseJson<BackendHomeSection>(response));
  },

  async getEvidencePicks(params = {}) {
    const searchParams = new URLSearchParams();
    if (params.categoryCode) searchParams.set("category_code", params.categoryCode);
    if (params.limit) searchParams.set("limit", String(params.limit));

    const query = searchParams.toString();
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/home/evidence-picks${query ? `?${query}` : ""}`
    );
    return mapHomeSection(await parseJson<BackendHomeSection>(response));
  },

  async getForYou(params = {}) {
    const searchParams = new URLSearchParams();
    if (params.skinType) searchParams.set("skin_type", params.skinType);
    if (params.sensitivity) searchParams.set("sensitivity", params.sensitivity);
    if (params.concern) searchParams.set("concern", params.concern);
    if (params.effect) searchParams.set("effect", params.effect);
    if (params.categoryCode) searchParams.set("category_code", params.categoryCode);
    if (params.limit) searchParams.set("limit", String(params.limit));

    const query = searchParams.toString();
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/home/for-you${query ? `?${query}` : ""}`
    );
    return mapHomeSection(await parseJson<BackendHomeSection>(response));
  },

  async getPopularProducts(params = {}) {
    const searchParams = new URLSearchParams();
    if (params.categoryCode) searchParams.set("category_code", params.categoryCode);
    if (params.limit) searchParams.set("limit", String(params.limit));

    const query = searchParams.toString();
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/products/popular${query ? `?${query}` : ""}`
    );
    return mapPopularProducts(await parseJson<PopularProductsResponse>(response));
  },

  async getProduct(productId, recommendationId) {
    const searchParams = new URLSearchParams();
    if (recommendationId) {
      searchParams.set("recommendation_id", recommendationId);
    }

    const query = searchParams.toString();
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/products/${productId}${query ? `?${query}` : ""}`
    );
    return mapProductDetail(await parseJson<BackendProductDetailResponse>(response));
  },

  async getSkinTestQuestions() {
    const response = await fetchWithTimeout(`${API_BASE_URL}/skin-test/questions`);
    return parseJson<SkinTestQuestionsResponse>(response);
  },

  async submitSkinTest(request) {
    const response = await fetchWithTimeout(`${API_BASE_URL}/skin-test/submit`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(request)
    });
    return parseJson<SkinTestSubmitResponse>(response);
  },

  async getSkinTestResult(resultId) {
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/skin-test/results/${encodeURIComponent(String(resultId))}`
    );
    return parseJson<SkinTestResultResponse>(response);
  },

  async applySkinTestResult(resultId) {
    const response = await fetchWithTimeout(`${API_BASE_URL}/skin-test/apply-to-profile`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ result_id: resultId })
    });
    return parseJson<ApplySkinTestResultResponse>(response);
  },

  async sendAgentMessage(request) {
    const response = await fetchWithTimeout(`${API_BASE_URL}/agent/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(request)
    });
    return parseJson<AgentChatResponse>(response);
  },

  async confirmAgentToolCall(toolCallId, request) {
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/agent/tool-calls/${encodeURIComponent(toolCallId)}/confirm`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(request)
      }
    );
    return parseJson<AgentToolConfirmResponse>(response);
  }
};
