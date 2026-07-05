import http from "k6/http";
import { check, group, sleep } from "k6";
import { Counter } from "k6/metrics";

const BASE_URL = (__ENV.BASE_URL || "http://localhost:8000/api").replace(/\/$/, "");
const PROFILE = __ENV.PROFILE || "smoke";
const ENABLE_CART_WRITES = (__ENV.ENABLE_CART_WRITES || "false").toLowerCase() === "true";
const DEBUG_ERRORS = (__ENV.DEBUG_ERRORS || "false").toLowerCase() === "true";
const PRODUCT_IDS = (__ENV.PRODUCT_IDS || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);

const recommendationIds = new Counter("recommendation_ids_created");
const cartWrites = new Counter("cart_writes_attempted");

const profiles = {
  smoke: {
    stages: [
      { duration: "30s", target: 1 },
      { duration: "30s", target: 1 },
    ],
  },
  baseline: {
    stages: [
      { duration: "30s", target: 10 },
      { duration: "3m", target: 10 },
      { duration: "30s", target: 0 },
    ],
  },
  target: {
    stages: [
      { duration: "1m", target: 20 },
      { duration: "5m", target: 20 },
      { duration: "1m", target: 50 },
      { duration: "5m", target: 50 },
      { duration: "1m", target: 0 },
    ],
  },
  stress: {
    stages: [
      { duration: "1m", target: 50 },
      { duration: "3m", target: 50 },
      { duration: "1m", target: 100 },
      { duration: "3m", target: 100 },
      { duration: "1m", target: 0 },
    ],
  },
};

export const options = {
  stages: (profiles[PROFILE] || profiles.smoke).stages,
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{type:fast}": ["p(95)<500"],
    "http_req_duration{type:search}": ["p(95)<1000"],
    ...(ENABLE_CART_WRITES ? { "http_req_duration{type:write}": ["p(95)<1500"] } : {}),
  },
};

export function setup() {
  const health = http.get(`${BASE_URL}/health`, {
    tags: { endpoint: "health", type: "fast" },
  });
  check(health, {
    "health is 200": (response) => response.status === 200,
  });

  const popular = http.get(`${BASE_URL}/products/popular?limit=20`, {
    tags: { endpoint: "popular_products", type: "fast" },
  });
  check(popular, {
    "popular products is 200": (response) => response.status === 200,
  });

  let discoveredProductIds = [];
  if (popular.status === 200) {
    const body = parseJson(popular);
    discoveredProductIds = (body?.items || [])
      .map((item) => item.product_id)
      .filter(Boolean);
  }

  const productIds = PRODUCT_IDS.length ? PRODUCT_IDS : discoveredProductIds;
  if (!productIds.length) {
    throw new Error("No product ids found. Set PRODUCT_IDS=prod_001,prod_002 or seed popular products.");
  }

  return { productIds };
}

export default function (data) {
  const productId = pick(data.productIds);

  group("read: health and popular products", () => {
    const health = http.get(`${BASE_URL}/health`, {
      tags: { endpoint: "health", type: "fast" },
    });
    check(health, {
      "health ok": (response) => response.status === 200,
    });

    const popular = http.get(`${BASE_URL}/products/popular?limit=12`, {
      tags: { endpoint: "popular_products", type: "fast" },
    });
    check(popular, {
      "popular ok": (response) => response.status === 200,
      "popular has items": (response) => (parseJson(response)?.items || []).length > 0,
    });
  });

  group("read: product detail", () => {
    const detail = http.get(`${BASE_URL}/products/${encodeURIComponent(productId)}`, {
      tags: { endpoint: "product_detail", type: "fast" },
    });
    check(detail, {
      "product detail ok": (response) => response.status === 200,
      "product detail has product": (response) => Boolean(parseJson(response)?.product?.product_id),
    });
  });

  group("search: recommendation create and page", () => {
    const requestBody = JSON.stringify({
      concern_text: pick([
        "턱에 뾰루지가 자꾸 나고 피부가 예민해진 것 같아요",
        "수부지인데 모공과 좁쌀이 고민이에요",
        "건조하고 화장이 들떠요",
      ]),
      skin_type: "수부지",
      sensitivity: "민감",
      avoid_ingredients: [],
    });

    const create = http.post(`${BASE_URL}/recommendations?page_size=10`, requestBody, {
      headers: { "Content-Type": "application/json" },
      tags: { endpoint: "recommendations_create", type: "search" },
    });
    const createBody = parseJson(create);
    const recommendationId = createBody?.recommendation_id;
    debugFailedResponse("recommendations_create", create);

    check(create, {
      "recommendation create ok": (response) => response.status === 200,
      "recommendation has products": () => (createBody?.products || []).length > 0,
    });

    if (recommendationId) {
      recommendationIds.add(1);
      const page = http.get(
        `${BASE_URL}/recommendations/${encodeURIComponent(recommendationId)}?page=1&page_size=10`,
        { tags: { endpoint: "recommendations_page", type: "search" } },
      );
      debugFailedResponse("recommendations_page", page);
      check(page, {
        "recommendation page ok": (response) => response.status === 200,
      });
    }
  });

  if (ENABLE_CART_WRITES) {
    group("write: anonymous cart add", () => {
      cartWrites.add(1);
      const add = http.post(
        `${BASE_URL}/cart/items`,
        JSON.stringify({
          product_id: productId,
          quantity: 1,
          source: "k6_load_test",
        }),
        {
          headers: { "Content-Type": "application/json" },
          tags: { endpoint: "cart_add", type: "write" },
        },
      );
      debugFailedResponse("cart_add", add);
      check(add, {
        "cart add ok": (response) => response.status === 200,
      });
    });
  }

  sleep(Math.random() * 1.5 + 0.5);
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
