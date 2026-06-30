import type {
  ApiError,
  HomeSectionsResponse,
  Pagination,
  ProductCardItem,
  ProductDetail,
  PurchaseConstraints,
  RecommendationNarrative,
  RecommendationRequest,
  RecommendationResponse,
  ScoreBreakdown
} from "../types/recommendation";

type RecommendationApi = {
  createRecommendation: (
    request: RecommendationRequest,
    page?: number,
    pageSize?: number
  ) => Promise<RecommendationResponse>;
  getRecommendation: (
    recommendationId: string,
    page?: number,
    pageSize?: number
  ) => Promise<RecommendationResponse>;
  getProduct: (productId: string, recommendationId?: string) => Promise<ProductDetail>;
  getHomeSections: (params: {
    skinType: string;
    sensitivity: string;
    categoryCode?: string | null;
    limitPerSection?: number;
  }) => Promise<HomeSectionsResponse>;
  getRecommendationNarrative: (
    recommendationId: string,
    options?: { productLimit?: number; useLlm?: boolean }
  ) => Promise<RecommendationNarrative>;
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

type BackendHomeProduct = {
  product_id: string;
  brand: string;
  name: string;
  category_code: string;
  category_name: string;
  thumbnail_url: string;
  lowest_price: number;
  original_price: number | null;
  discount_rate: number | null;
  purchase_url: string | null;
  badges: string[];
  tags: string[];
  reason_summary: string;
  display_score: number;
};

type BackendHomeSectionsResponse = {
  skin_type: string;
  sensitivity: string;
  category_code: string | null;
  sections: {
    section_id: string;
    title: string;
    subtitle: string;
    section_type: string;
    algorithm: string;
    products: BackendHomeProduct[];
  }[];
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

type BackendPagination = {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
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
  pagination?: BackendPagination;
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

type BackendNarrativeResponse = {
  recommendation_id: string;
  narrative: RecommendationNarrative;
};

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api").replace(
  /\/$/,
  ""
);

const requestTimeoutMs = 15000;
const defaultPageSize = 10;

const emptyPurchaseConstraints: PurchaseConstraints = {
  categories: [],
  brands: [],
  price_min: null,
  price_max: null,
  price_text: null,
  price_max_text: null
};

const defaultPagination = (productCount: number): Pagination => ({
  page: 1,
  page_size: defaultPageSize,
  total_items: productCount,
  total_pages: productCount > 0 ? Math.ceil(productCount / defaultPageSize) : 0,
  has_next: false,
  has_prev: false
});

const mapPagination = (
  pagination: BackendPagination | undefined,
  productCount: number
): Pagination => pagination ?? defaultPagination(productCount);

const mapScoreBreakdown = (score?: BackendScoreBreakdown | null): ScoreBreakdown | undefined => {
  if (!score) {
    return undefined;
  }

  return {
    ingredient_effect_score: score.ingredient_effect_score,
    ingredient_evidence_score: score.ingredient_evidence_score,
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
  thumbnail_url: product.thumbnail_url || null,
  lowest_price: product.lowest_price ?? null,
  evidence_tags: product.evidence_tags,
  key_ingredients: product.key_ingredients,
  risk_flags: [],
  score_breakdown: mapScoreBreakdown(product.score_breakdown)
});

const mapHomeProductCard = (product: BackendHomeProduct, rank: number): ProductCardItem => ({
  product_id: product.product_id,
  rank,
  total_score: product.display_score,
  reason_summary: product.reason_summary,
  brand: product.brand,
  name: product.name,
  thumbnail_url: product.thumbnail_url || null,
  lowest_price: product.lowest_price ?? null,
  evidence_tags: product.badges.length > 0 ? product.badges : product.tags,
  key_ingredients: product.tags,
  risk_flags: [],
  score_breakdown: undefined
});

const mapRecommendation = (response: BackendRecommendationResponse): RecommendationResponse => {
  const products = response.products.map(mapProductCard);

  return {
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
    products,
    pagination: mapPagination(response.pagination, products.length)
  };
};

const mapHomeSections = (response: BackendHomeSectionsResponse): HomeSectionsResponse => ({
  skin_type: response.skin_type,
  sensitivity: response.sensitivity,
  category_code: response.category_code,
  sections: response.sections.map((section) => ({
    section_id: section.section_id,
    title: section.title,
    subtitle: section.subtitle,
    section_type: section.section_type,
    algorithm: section.algorithm,
    products: section.products.map((product, index) => mapHomeProductCard(product, index + 1))
  }))
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
      evidence_text: item.description,
      source_title: item.source_title || null
    })),
    prices: response.prices,
    sources: response.sources
  };
};

const fetchWithTimeout = async (input: RequestInfo | URL, init?: RequestInit) => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);

  try {
    return await fetch(input, {
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

const buildPageQuery = (page = 1, pageSize = defaultPageSize) => {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize)
  });
  return params.toString();
};

export const api: RecommendationApi = {
  async createRecommendation(request, page = 1, pageSize = defaultPageSize) {
    const response = await fetchWithTimeout(`${apiBaseUrl}/recommendations?${buildPageQuery(page, pageSize)}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(request)
    });
    return mapRecommendation(await parseJson<BackendRecommendationResponse>(response));
  },

  async getRecommendation(recommendationId, page = 1, pageSize = defaultPageSize) {
    const response = await fetchWithTimeout(
      `${apiBaseUrl}/recommendations/${encodeURIComponent(recommendationId)}?${buildPageQuery(page, pageSize)}`
    );
    return mapRecommendation(await parseJson<BackendRecommendationResponse>(response));
  },

  async getProduct(productId, recommendationId) {
    const searchParams = new URLSearchParams();
    if (recommendationId) {
      searchParams.set("recommendation_id", recommendationId);
    }

    const query = searchParams.toString();
    const response = await fetchWithTimeout(
      `${apiBaseUrl}/products/${encodeURIComponent(productId)}${query ? `?${query}` : ""}`
    );
    return mapProductDetail(await parseJson<BackendProductDetailResponse>(response));
  },

  async getHomeSections({ skinType, sensitivity, categoryCode, limitPerSection = 8 }) {
    const params = new URLSearchParams({
      skin_type: skinType,
      sensitivity,
      limit_per_section: String(limitPerSection)
    });

    if (categoryCode) {
      params.set("category_code", categoryCode);
    }

    const response = await fetchWithTimeout(`${apiBaseUrl}/home/sections?${params.toString()}`);
    return mapHomeSections(await parseJson<BackendHomeSectionsResponse>(response));
  },

  async getRecommendationNarrative(recommendationId, options = {}) {
    const response = await fetchWithTimeout(
      `${apiBaseUrl}/recommendations/${encodeURIComponent(recommendationId)}/narrative`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          mode: "community_beta",
          product_limit: options.productLimit ?? 10,
          use_llm: options.useLlm ?? false
        })
      }
    );
    const payload = await parseJson<BackendNarrativeResponse>(response);
    return payload.narrative;
  }
};
