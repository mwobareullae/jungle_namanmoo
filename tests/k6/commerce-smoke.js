import http from "k6/http";
import { check, group, sleep } from "k6";
import { Counter } from "k6/metrics";

const BASE_URL = (__ENV.BASE_URL || "http://localhost:8000/api").replace(/\/$/, "");
const PROFILE = __ENV.PROFILE || "smoke";
const CART_WRITES_ENABLED =
  (__ENV.CART_WRITES || __ENV.ENABLE_CART_WRITES || "false").toLowerCase() === "true";
const DEBUG_ERRORS = (__ENV.DEBUG_ERRORS || "false").toLowerCase() === "true";
const SLA_MS = Number(__ENV.SLA_MS || "3000");
const CATALOG_SEARCH_SLA_MS = Number(__ENV.CATALOG_SEARCH_SLA_MS || "500");
const CATALOG_SUGGESTIONS_SLA_MS = Number(__ENV.CATALOG_SUGGESTIONS_SLA_MS || "200");
const AUTH_COOKIE = __ENV.AUTH_COOKIE || "";
const AUTH_HOME_FOR_YOU_ENABLED =
  (__ENV.AUTH_HOME_FOR_YOU || __ENV.ENABLE_AUTH_HOME_FOR_YOU || "false").toLowerCase() === "true";
const PRODUCT_IDS = (__ENV.PRODUCT_IDS || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const HEAVY_PRODUCT_IDS = (__ENV.HEAVY_PRODUCT_IDS || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const SEARCH_QUERIES = (__ENV.SEARCH_QUERIES || "세럼,수분 크림,나이아신아마이드,진정,선크림")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const SUGGESTION_QUERIES = (__ENV.SUGGESTION_QUERIES || "토리,라운,수분,세럼,ㅌㄹㄷ")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const SEARCH_FEATURE_FILTER = __ENV.SEARCH_FEATURE_FILTER || "moisturizing_calming";
const SEARCH_SKIN_TYPE_FILTER = __ENV.SEARCH_SKIN_TYPE_FILTER || "dehydrated_oily";
const NARRATIVE_ENABLED =
  (__ENV.NARRATIVE || __ENV.ENABLE_RECOMMENDATION_NARRATIVE || "true").toLowerCase() === "true";
const NARRATIVE_USE_LLM = (__ENV.NARRATIVE_USE_LLM || "false").toLowerCase() === "true";

const recommendationIds = new Counter("recommendation_ids_created");
const cartWrites = new Counter("cart_writes_attempted");

const PROFILE_SCENARIOS = {
  smoke: {
    executor: "constant-vus",
    vus: 1,
    duration: "1m",
  },
  baseline: {
    executor: "constant-vus",
    vus: 10,
    duration: "4m",
  },
  target: {
    executor: "ramping-vus",
    startVUs: 0,
    stages: [
      { duration: "30s", target: 20 },
      { duration: "2m", target: 50 },
      { duration: "1m", target: 0 },
    ],
  },
  stress: {
    executor: "ramping-vus",
    startVUs: 0,
    stages: [
      { duration: "30s", target: 50 },
      { duration: "2m", target: 50 },
      { duration: "30s", target: 100 },
      { duration: "2m", target: 100 },
      { duration: "1m", target: 0 },
    ],
  },
  catalog: {
    executor: "constant-vus",
    vus: 10,
    duration: "2m",
  },
};

if (!PROFILE_SCENARIOS[PROFILE]) {
  throw new Error(`Unknown PROFILE: ${PROFILE}. Use smoke, baseline, target, stress, or catalog.`);
}

export const options = {
  scenarios: {
    [PROFILE]: {
      ...PROFILE_SCENARIOS[PROFILE],
      exec: PROFILE === "catalog" ? "catalogSearchJourney" : "userJourney",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{type:fast}": [`p(95)<${SLA_MS}`],
    "http_req_duration{type:home}": [`p(95)<${SLA_MS}`],
    "http_req_duration{type:search}": [`p(95)<${SLA_MS}`],
    "http_req_duration{type:catalog_listing}": [`p(95)<${SLA_MS}`],
    "http_req_duration{type:product_reviews}": [`p(95)<${SLA_MS}`],
    "http_req_duration{type:catalog_search}": [`p(95)<${CATALOG_SEARCH_SLA_MS}`],
    "http_req_duration{type:catalog_suggestions}": [`p(95)<${CATALOG_SUGGESTIONS_SLA_MS}`],
    ...(CART_WRITES_ENABLED ? { "http_req_duration{type:write}": [`p(95)<${SLA_MS}`] } : {}),
  },
};

const RECOMMENDATION_CASES = [
  {
    concern_text: "요즘 피부가 건조하고 각질이 일어나요",
    skin_type: "건성",
    sensitivity: "보통",
    avoid_ingredients: [],
  },
  {
    concern_text: "여드름이랑 트러블이 자꾸 생겨요",
    skin_type: "지성",
    sensitivity: "높음",
    avoid_ingredients: [],
  },
  {
    concern_text: "모공이 넓어지고 피지가 많아요",
    skin_type: "복합성",
    sensitivity: "보통",
    avoid_ingredients: [],
  },
  {
    concern_text: "피부가 예민해서 자극 없는 진정 제품이 필요해요",
    skin_type: "수부지",
    sensitivity: "높음",
    avoid_ingredients: ["알코올"],
  },
  {
    concern_text: "나이아신아마이드 세럼 중 3만원 이하 제품을 찾고 있어요",
    skin_type: "중성",
    sensitivity: "낮음",
    avoid_ingredients: [],
  },
];

export function setup() {
  const health = http.get(`${BASE_URL}/health`, {
    tags: { endpoint: "health", type: "fast" },
  });
  check(health, {
    "health is 200": (response) => response.status === 200,
  });

  if (PROFILE === "catalog") {
    return { productIds: [] };
  }

  const popular = http.get(`${BASE_URL}/products/popular?limit=20`, {
    tags: { endpoint: "popular_products", type: "fast" },
  });
  check(popular, {
    "popular products is 200": (response) => response.status === 200,
  });

  const discoveredProductIds = parseJson(popular)?.items?.map((item) => item.product_id).filter(Boolean) || [];
  const productIds = PRODUCT_IDS.length ? PRODUCT_IDS : discoveredProductIds;
  if (!productIds.length) {
    throw new Error("No product ids found. Set PRODUCT_IDS=prod_001,prod_002 or seed popular products.");
  }

  return { productIds };
}

export function catalogSearchJourney() {
  group("catalog_product_search", () => {
    const query = pick(SEARCH_QUERIES);
    const response = http.get(
      `${BASE_URL}/search/products?q=${encodeURIComponent(query)}&page=1&page_size=20`,
      { tags: { endpoint: "catalog_product_search", type: "catalog_search" } },
    );
    debugFailedResponse("catalog_product_search", response);
    check(response, {
      "catalog product search 200": (res) => res.status === 200,
      "catalog product search contract": (res) => Array.isArray(parseJson(res)?.items),
    });
  });

  group("catalog_product_search_filtered", () => {
    const query = pick(SEARCH_QUERIES);
    const response = http.get(
      `${BASE_URL}/search/products?q=${encodeURIComponent(query)}` +
        `&feature=${encodeURIComponent(SEARCH_FEATURE_FILTER)}` +
        `&skin_type=${encodeURIComponent(SEARCH_SKIN_TYPE_FILTER)}` +
        "&page=1&page_size=20",
      { tags: { endpoint: "catalog_product_search_filtered", type: "catalog_search" } },
    );
    debugFailedResponse("catalog_product_search_filtered", response);
    check(response, {
      "filtered catalog product search 200": (res) => res.status === 200,
      "filtered catalog product search contract": (res) => Array.isArray(parseJson(res)?.items),
    });
  });

  group("catalog_search_suggestions", () => {
    const query = pick(SUGGESTION_QUERIES);
    const response = http.get(
      `${BASE_URL}/search/suggestions?q=${encodeURIComponent(query)}&limit=8`,
      { tags: { endpoint: "catalog_search_suggestions", type: "catalog_suggestions" } },
    );
    debugFailedResponse("catalog_search_suggestions", response);
    check(response, {
      "catalog suggestions 200": (res) => res.status === 200,
      "catalog suggestions contract": (res) => Array.isArray(parseJson(res)?.items),
    });
  });

  sleep(0.2);
}

export function userJourney(data) {
  group("health", () => {
    const response = http.get(`${BASE_URL}/health`, {
      tags: { endpoint: "health", type: "fast" },
    });
    check(response, { "health 200": (res) => res.status === 200 });
  });

  let popularProductIds = [];
  group("popular_products", () => {
    const response = http.get(`${BASE_URL}/products/popular?limit=10`, {
      tags: { endpoint: "popular_products", type: "fast" },
    });
    const ok = check(response, { "popular 200": (res) => res.status === 200 });
    if (ok) {
      popularProductIds = parseJson(response)?.items?.map((item) => item.product_id).filter(Boolean) || [];
    }
  });

  group("product_listing_newest", () => {
    const response = http.get(
      `${BASE_URL}/products?page=1&page_size=20&sort=newest&in_stock=true`,
      { tags: { endpoint: "product_listing_newest", type: "catalog_listing" } },
    );
    debugFailedResponse("product_listing_newest", response);
    check(response, {
      "newest product listing 200": (res) => res.status === 200,
      "newest product listing contract": (res) => Array.isArray(parseJson(res)?.items),
    });
  });

  group("product_listing_filtered", () => {
    const response = http.get(
      `${BASE_URL}/products?page=1&page_size=20&sort=popular&min_rating=4&in_stock=true`,
      { tags: { endpoint: "product_listing_filtered", type: "catalog_listing" } },
    );
    debugFailedResponse("product_listing_filtered", response);
    check(response, {
      "filtered product listing 200": (res) => res.status === 200,
      "filtered product listing contract": (res) => Array.isArray(parseJson(res)?.items),
    });
  });

  const detailProductId = pick(popularProductIds.length ? popularProductIds : data.productIds);
  group("product_detail", () => {
    const response = http.get(`${BASE_URL}/products/${encodeURIComponent(detailProductId)}`, {
      tags: { endpoint: "product_detail", type: "fast" },
    });
    debugFailedResponse("product_detail", response);
    check(response, {
      "detail 200": (res) => res.status === 200,
      "detail has product": (res) => Boolean(parseJson(res)?.product?.product_id),
    });
  });

  group("product_reviews_latest", () => {
    const response = http.get(
      `${BASE_URL}/products/${encodeURIComponent(detailProductId)}/reviews?limit=20&sort=latest`,
      { tags: { endpoint: "product_reviews_latest", type: "product_reviews" } },
    );
    debugFailedResponse("product_reviews_latest", response);
    check(response, {
      "latest product reviews 200": (res) => res.status === 200,
      "latest product reviews contract": (res) => Array.isArray(parseJson(res)?.items),
    });
  });

  group("product_reviews_skin_filtered", () => {
    const response = http.get(
      `${BASE_URL}/products/${encodeURIComponent(detailProductId)}/reviews` +
        `?limit=20&sort=helpful&skin_type=${encodeURIComponent("건성")}`,
      { tags: { endpoint: "product_reviews_skin_filtered", type: "product_reviews" } },
    );
    debugFailedResponse("product_reviews_skin_filtered", response);
    check(response, {
      "skin filtered product reviews 200": (res) => res.status === 200,
      "skin filtered product reviews contract": (res) => Array.isArray(parseJson(res)?.items),
    });
  });

  group("product_search", () => {
    const query = pick(SEARCH_QUERIES);
    const response = http.get(
      `${BASE_URL}/search/products?q=${encodeURIComponent(query)}&page=1&page_size=20`,
      { tags: { endpoint: "catalog_product_search", type: "catalog_search" } },
    );
    debugFailedResponse("product_search", response);
    check(response, {
      "product search 200": (res) => res.status === 200,
    });
  });

  group("product_search_filtered", () => {
    const query = pick(SEARCH_QUERIES);
    const response = http.get(
      `${BASE_URL}/search/products?q=${encodeURIComponent(query)}` +
        `&feature=${encodeURIComponent(SEARCH_FEATURE_FILTER)}` +
        `&skin_type=${encodeURIComponent(SEARCH_SKIN_TYPE_FILTER)}` +
        "&page=1&page_size=20",
      { tags: { endpoint: "catalog_product_search_filtered", type: "catalog_search" } },
    );
    debugFailedResponse("product_search_filtered", response);
    check(response, {
      "filtered product search 200": (res) => res.status === 200,
      "filtered product search contract": (res) => Array.isArray(parseJson(res)?.items),
    });
  });

  group("catalog_search_suggestions", () => {
    const query = pick(SUGGESTION_QUERIES);
    const response = http.get(
      `${BASE_URL}/search/suggestions?q=${encodeURIComponent(query)}&limit=8`,
      { tags: { endpoint: "catalog_search_suggestions", type: "catalog_suggestions" } },
    );
    debugFailedResponse("catalog_search_suggestions", response);
    check(response, { "catalog suggestions 200": (res) => res.status === 200 });
  });

  group("home_layout", () => {
    const response = http.get(`${BASE_URL}/home/layout`, {
      tags: { endpoint: "home_layout", type: "home" },
    });
    debugFailedResponse("home_layout", response);
    check(response, { "home layout 200": (res) => res.status === 200 });
  });

  group("home_market_popular", () => {
    const response = http.get(`${BASE_URL}/home/market-popular?limit=12`, {
      tags: { endpoint: "home_market_popular", type: "home" },
    });
    debugFailedResponse("home_market_popular", response);
    check(response, { "home market popular 200": (res) => res.status === 200 });
  });

  group("home_evidence_picks", () => {
    const response = http.get(`${BASE_URL}/home/evidence-picks?limit=12`, {
      tags: { endpoint: "home_evidence_picks", type: "home" },
    });
    debugFailedResponse("home_evidence_picks", response);
    check(response, { "home evidence picks 200": (res) => res.status === 200 });
  });

  group("home_for_you_fallback", () => {
    const response = http.get(`${BASE_URL}/home/for-you?limit=12`, {
      tags: { endpoint: "home_for_you_fallback", type: "home" },
    });
    debugFailedResponse("home_for_you_fallback", response);
    check(response, { "home for you fallback 200": (res) => res.status === 200 });
  });

  group("home_for_you_selected_dry", () => {
    const response = http.get(
      `${BASE_URL}/home/for-you?skin_type=${encodeURIComponent("건성")}&sensitivity=${encodeURIComponent("높음")}&limit=12`,
      { tags: { endpoint: "home_for_you_selected_dry", type: "home" } },
    );
    debugFailedResponse("home_for_you_selected_dry", response);
    check(response, { "home for you selected dry 200": (res) => res.status === 200 });
  });

  group("home_for_you_selected_trouble", () => {
    const response = http.get(
      `${BASE_URL}/home/for-you?skin_type=${encodeURIComponent("지성")}&sensitivity=${encodeURIComponent("보통")}&concern=${encodeURIComponent("트러블")}&limit=12`,
      { tags: { endpoint: "home_for_you_selected_trouble", type: "home" } },
    );
    debugFailedResponse("home_for_you_selected_trouble", response);
    check(response, { "home for you selected trouble 200": (res) => res.status === 200 });
  });

  if (AUTH_HOME_FOR_YOU_ENABLED && AUTH_COOKIE) {
    group("home_for_you_auth", () => {
      const response = http.get(`${BASE_URL}/home/for-you?limit=12`, {
        headers: { Cookie: AUTH_COOKIE },
        tags: { endpoint: "home_for_you_auth", type: "home" },
      });
      debugFailedResponse("home_for_you_auth", response);
      check(response, { "home for you auth 200": (res) => res.status === 200 });
    });
  }

  if (HEAVY_PRODUCT_IDS.length > 0) {
    group("heavy_product_detail", () => {
      const productId = pick(HEAVY_PRODUCT_IDS);
      const response = http.get(`${BASE_URL}/products/${encodeURIComponent(productId)}`, {
        tags: { endpoint: "heavy_product_detail", type: "fast" },
      });
      debugFailedResponse("heavy_product_detail", response);
      check(response, {
        "heavy detail 200": (res) => res.status === 200,
      });
    });
  }

  let recommendationId = null;
  let recommendedProductIds = [];
  group("recommendations_post", () => {
    const recommendationCase = pick(RECOMMENDATION_CASES);
    const payload = JSON.stringify(recommendationCase);
    const response = http.post(`${BASE_URL}/recommendations?page=1&page_size=10`, payload, {
      headers: { "Content-Type": "application/json" },
      tags: { endpoint: "recommendations_post_anonymous", type: "search" },
    });
    const body = parseJson(response);
    debugFailedResponse("recommendations_post", response);
    const ok = check(response, {
      "recommend 200": (res) => res.status === 200,
      "recommend has products": () => (body?.products || []).length > 0,
    });
    if (ok) {
      recommendationId = body?.recommendation_id || null;
      recommendedProductIds = body?.products?.map((product) => product.product_id).filter(Boolean) || [];
    }

    if (AUTH_COOKIE) {
      const authResponse = http.post(`${BASE_URL}/recommendations?page=1&page_size=10`, payload, {
        headers: {
          "Content-Type": "application/json",
          Cookie: AUTH_COOKIE,
        },
        tags: { endpoint: "recommendations_post_auth", type: "search" },
      });
      const authBody = parseJson(authResponse);
      debugFailedResponse("recommendations_post_auth", authResponse);
      check(authResponse, {
        "authenticated recommend 200": (res) => res.status === 200,
        "authenticated recommend has products": () => (authBody?.products || []).length > 0,
      });
    }
  });

  if (recommendationId) {
    recommendationIds.add(1);
    group("recommendations_get", () => {
      const response = http.get(
        `${BASE_URL}/recommendations/${encodeURIComponent(recommendationId)}?page=1&page_size=10`,
        { tags: { endpoint: "recommendations_get", type: "search" } },
      );
      debugFailedResponse("recommendations_get", response);
      check(response, { "recommend get 200": (res) => res.status === 200 });
    });

    if (NARRATIVE_ENABLED) {
      group("recommendation_narrative", () => {
        const payload = JSON.stringify({
          view: "cards",
          product_limit: 5,
          use_llm: NARRATIVE_USE_LLM,
        });
        const response = http.post(
          `${BASE_URL}/recommendations/${encodeURIComponent(recommendationId)}/narrative`,
          payload,
          {
            headers: { "Content-Type": "application/json" },
            tags: { endpoint: "recommendation_narrative", type: "search" },
          },
        );
        const body = parseJson(response);
        debugFailedResponse("recommendation_narrative", response);
        check(response, {
          "narrative 200": (res) => res.status === 200,
          "narrative has products": () => (body?.narrative?.product_explanations || []).length > 0,
        });
      });
    }
  }

  if (recommendationId && recommendedProductIds.length > 0) {
    group("recommended_product_detail", () => {
      const productId = pick(recommendedProductIds);
      const response = http.get(
        `${BASE_URL}/products/${encodeURIComponent(productId)}?recommendation_id=${encodeURIComponent(recommendationId)}`,
        { tags: { endpoint: "recommended_product_detail", type: "search" } },
      );
      debugFailedResponse("recommended_product_detail", response);
      check(response, {
        "recommended detail 200": (res) => res.status === 200,
      });
    });
  }

  if (CART_WRITES_ENABLED && recommendedProductIds.length > 0) {
    let checkoutCartItemIds = [];
    group("cart_write", () => {
      cartWrites.add(1);
      const productId = pick(recommendedProductIds);
      const payload = JSON.stringify({
        product_id: productId,
        quantity: 1,
        source: "k6_load_test",
        recommendation_id: recommendationId,
        recommendation_rank: 1,
      });
      const response = http.post(`${BASE_URL}/cart/items`, payload, {
        headers: { "Content-Type": "application/json" },
        tags: { endpoint: "cart_write", type: "write" },
      });
      debugFailedResponse("cart_write", response);
      check(response, {
        "cart write 200": (res) => res.status === 200,
      });
      checkoutCartItemIds = (parseJson(response)?.items || [])
        .map((item) => item.id)
        .filter((value) => value !== undefined && value !== null);
    });

    if (checkoutCartItemIds.length > 0) {
      group("checkout_preview", () => {
        const response = http.post(
          `${BASE_URL}/checkout/preview`,
          JSON.stringify({ cart_item_ids: checkoutCartItemIds.slice(0, 3) }),
          {
            headers: { "Content-Type": "application/json" },
            tags: { endpoint: "checkout_preview", type: "write" },
          },
        );
        debugFailedResponse("checkout_preview", response);
        check(response, {
          "checkout preview 200": (res) => res.status === 200,
        });
      });
    }
  }

  sleep(1);
}

function parseJson(response) {
  try {
    return response.json();
  } catch (_) {
    return null;
  }
}

function pick(values) {
  return values[Math.floor(Math.random() * values.length)];
}

function debugFailedResponse(endpoint, response) {
  if (!DEBUG_ERRORS || response.status < 400) {
    return;
  }

  const body = String(response.body || "").slice(0, 500);
  console.error(`[${endpoint}] status=${response.status} body=${body}`);
}
