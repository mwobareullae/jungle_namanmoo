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
const USER_FIXTURES = JSON.parse(open("../../docs/performance/benchmark-users.json")).users;
const USER_FIXTURE = USER_FIXTURES.find((user) => user.key === USER_TYPE);

if (!USER_FIXTURE) {
  throw new Error(`Unknown USER_TYPE: ${USER_TYPE}`);
}

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

export function setup() {
  if (!USER_FIXTURE.auth_required || AUTH_COOKIE) {
    return { authCookie: AUTH_COOKIE };
  }

  const email = __ENV[USER_FIXTURE.email_env] || "";
  const password = __ENV[USER_FIXTURE.password_env] || "";
  if (!email || !password) {
    throw new Error(`Credentials are required for USER_TYPE=${USER_TYPE}`);
  }

  const response = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify({ email, password }),
    {
      headers: { "Content-Type": "application/json" },
      tags: { endpoint: "auth_login", type: "auth", user_type: USER_TYPE },
    },
  );
  if (response.status !== 200) {
    throw new Error(`Benchmark login failed: status=${response.status}`);
  }

  const setCookie = response.headers["Set-Cookie"] || response.headers["set-cookie"] || "";
  const authCookie = setCookie.split(";")[0];
  if (!authCookie) {
    throw new Error("Benchmark login response did not include a session cookie");
  }
  return { authCookie };
}

export default function (data) {
  const requestCase = REQUESTS[(__VU + __ITER) % REQUESTS.length];
  const requestContext = USER_FIXTURE.request_context || {};
  const avoidIngredients = __ENV.AVOID_INGREDIENTS
    ? __ENV.AVOID_INGREDIENTS.split(",").filter(Boolean)
    : requestContext.avoid_ingredients || [];
  const payload = JSON.stringify({
    concern_text: requestCase.query,
    skin_type: __ENV.SKIN_TYPE || requestContext.skin_type,
    sensitivity: __ENV.SENSITIVITY || requestContext.sensitivity,
    avoid_ingredients: avoidIngredients,
  });
  const headers = { "Content-Type": "application/json" };
  if (data?.authCookie) {
    headers.Cookie = data.authCookie;
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
