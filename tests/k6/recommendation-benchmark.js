import http from "k6/http";
import { check } from "k6";

const BASE_URL = (__ENV.BASE_URL || "http://localhost:8000/api").replace(/\/$/, "");
const DATASET = __ENV.DATASET || "unknown";
const USER_TYPE = __ENV.USER_TYPE || "anonymous";
const AUTH_COOKIE = __ENV.AUTH_COOKIE || "";
const VUS = Number(__ENV.VUS || "1");
const DURATION = __ENV.DURATION || "30s";
const SLA_MS = Number(__ENV.SLA_MS || "3000");
const FAILURE_SAMPLE_LIMIT = Number(__ENV.FAILURE_SAMPLE_LIMIT || "20");
const REQUESTS = JSON.parse(open("../../docs/performance/queries/recommendation-v1.json"));
const USER_FIXTURES = JSON.parse(open("../../docs/performance/benchmark-users.json")).users;
const USER_FIXTURE = USER_FIXTURES.find((user) => user.key === USER_TYPE);
let failureSampleCount = 0;

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
  if (!USER_FIXTURE.auth_required) {
    return { authCookies: AUTH_COOKIE ? [AUTH_COOKIE] : [] };
  }

  if (AUTH_COOKIE) {
    return { authCookies: [AUTH_COOKIE] };
  }

  if (USER_FIXTURE.email_list_env) {
    const emails = resolveEmailList(USER_FIXTURE);
    const password = __ENV[USER_FIXTURE.password_env] || "";
    if (!emails.length || !password) {
      throw new Error(`Credentials are required for USER_TYPE=${USER_TYPE}`);
    }
    return { authCookies: emails.map((email) => loginBenchmarkUser(email, password)) };
  }

  const email = __ENV[USER_FIXTURE.email_env] || "";
  const password = __ENV[USER_FIXTURE.password_env] || "";
  if (!email || !password) {
    throw new Error(`Credentials are required for USER_TYPE=${USER_TYPE}`);
  }
  return { authCookies: [loginBenchmarkUser(email, password)] };
}

function resolveEmailList(userFixture) {
  const configuredEmails = (__ENV[userFixture.email_list_env] || "")
    .split(",")
    .map((email) => email.trim())
    .filter(Boolean);
  if (configuredEmails.length) {
    return configuredEmails;
  }

  const count = Number(__ENV[userFixture.email_count_env] || userFixture.generated_email_count || "0");
  const prefix = __ENV[userFixture.email_prefix_env] || userFixture.generated_email_prefix || "";
  const domain = __ENV[userFixture.email_domain_env] || userFixture.generated_email_domain || "";
  if (!count || !prefix || !domain) {
    return [];
  }
  return Array.from({ length: count }, (_, index) => {
    const paddedIndex = String(index + 1).padStart(2, "0");
    return `${prefix}_${paddedIndex}@${domain}`;
  });
}

function loginBenchmarkUser(email, password) {
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
  return authCookie;
}

export default function (data) {
  const requestCase = REQUESTS[(__VU + __ITER) % REQUESTS.length];
  const requestContext = USER_FIXTURE.request_context || {};
  const avoidIngredients = __ENV.AVOID_INGREDIENTS
    ? __ENV.AVOID_INGREDIENTS.split(",").filter(Boolean)
    : requestContext.avoid_ingredients || [];
  const payloadObject = {
    concern_text: requestCase.query,
    avoid_ingredients: avoidIngredients,
  };
  const skinType = __ENV.SKIN_TYPE || requestContext.skin_type;
  const sensitivity = __ENV.SENSITIVITY || requestContext.sensitivity;
  if (skinType !== undefined) {
    payloadObject.skin_type = skinType;
  }
  if (sensitivity !== undefined) {
    payloadObject.sensitivity = sensitivity;
  }
  const payload = JSON.stringify(payloadObject);
  const headers = { "Content-Type": "application/json" };
  const authCookie = pickAuthCookie(data);
  if (authCookie) {
    headers.Cookie = authCookie;
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
  const hasProducts = Array.isArray(body?.products) && body.products.length > 0;
  if ((response.status !== 200 || !hasProducts) && failureSampleCount < FAILURE_SAMPLE_LIMIT) {
    failureSampleCount += 1;
    console.error(
      JSON.stringify({
        event: "recommendation_benchmark_failure_sample",
        dataset: DATASET,
        user_type: USER_TYPE,
        vu: __VU,
        iter: __ITER,
        status: response.status,
        duration_ms: response.timings.duration,
        query_type: requestCase.type,
        query: requestCase.query,
        payload: payloadObject,
        response_body: truncate(response.body || "", 1000),
      }),
    );
  }
  check(response, {
    "recommendation status is 200": (res) => res.status === 200,
    "recommendation has products": () => hasProducts,
  });
}

function pickAuthCookie(data) {
  const authCookies = data?.authCookies || [];
  if (!authCookies.length) {
    return "";
  }
  return authCookies[(__VU + __ITER) % authCookies.length];
}

function parseJson(response) {
  try {
    return response.json();
  } catch (_) {
    return null;
  }
}

function truncate(value, maxLength) {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength)}...`;
}
