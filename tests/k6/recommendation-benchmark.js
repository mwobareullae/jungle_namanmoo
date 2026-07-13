import http from "k6/http";
import { check } from "k6";

const BASE_URL = (__ENV.BASE_URL || "http://localhost:8000/api").replace(/\/$/, "");
const DATASET = __ENV.DATASET || "unknown";
const USER_TYPE = __ENV.USER_TYPE || "anonymous";
const AUTH_COOKIE = __ENV.AUTH_COOKIE || "";
const VUS = Number(__ENV.VUS || "1");
const DURATION = __ENV.DURATION || "30s";
const SLA_MS = Number(__ENV.SLA_MS || "3000");
const REQUESTS = JSON.parse(open("../../docs/performance/queries/recommendation-v1.json"));

export const options = {
  scenarios: {
    recommendation_benchmark: {
      executor: "constant-vus",
      vus: VUS,
      duration: DURATION,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{type:recommendation}": [`p(95)<${SLA_MS}`],
  },
};

export default function () {
  const requestCase = REQUESTS[(__VU + __ITER) % REQUESTS.length];
  const payload = JSON.stringify({
    concern_text: requestCase.query,
    skin_type: __ENV.SKIN_TYPE || "건성",
    sensitivity: __ENV.SENSITIVITY || "높음",
    avoid_ingredients: (__ENV.AVOID_INGREDIENTS || "").split(",").filter(Boolean),
  });
  const headers = { "Content-Type": "application/json" };
  if (AUTH_COOKIE) {
    headers.Cookie = AUTH_COOKIE;
  }

  const response = http.post(`${BASE_URL}/recommendations?page=1&page_size=10`, payload, {
    headers,
    tags: {
      endpoint: "recommendations_post",
      type: "recommendation",
      benchmark_dataset: DATASET,
      user_type: USER_TYPE,
      query_type: requestCase.type,
    },
  });
  const body = parseJson(response);
  check(response, {
    "recommendation status is 200": (res) => res.status === 200,
    "recommendation has products": () => Array.isArray(body?.products) && body.products.length > 0,
  });
}

function parseJson(response) {
  try {
    return response.json();
  } catch (_) {
    return null;
  }
}
