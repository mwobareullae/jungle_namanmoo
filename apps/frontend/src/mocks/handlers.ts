import { http, HttpResponse } from "msw";
import type { SkinTestResult, SkinTestSubmitRequest } from "../types/skinTest";

type LoginRequestBody = {
  email?: string;
  password?: string;
};

type SignupRequestBody = LoginRequestBody & {
  nickname?: string;
};

type PasswordResetRequestBody = {
  email?: string;
};

type SkinProfileRequestBody = {
  skinType?: string;
  sensitivity?: string;
  concerns?: string[];
  avoidIngredients?: string[];
};

const MOCK_LOGIN_EMAIL = "test@example.com";
const MOCK_LOGIN_PASSWORD = "password123";
const MOCK_DUPLICATE_SIGNUP_EMAIL = "duplicate@example.com";
const MOCK_DUPLICATE_SIGNUP_NICKNAME = "duplicate";
const MOCK_SERVER_ERROR_SIGNUP_EMAIL = "server-error@example.com";
const useAuthMock = import.meta.env.VITE_USE_AUTH_MOCK === "true";
const MOCK_SKIN_TEST_VERSION = "v1.0";
const MOCK_SKIN_TEST_RESULT_ID = 12001;

const mockSkinTestQuestions = [
  {
    id: 1,
    text: "세안 후 아무것도 바르지 않고 몇 시간 지난 오후, 내 피부는?",
    options: [
      { id: 101, text: "얼굴 전체가 번들거려 기름종이나 파우더가 필요하다" },
      { id: 102, text: "T존은 번들거리지만 볼은 적당하거나 살짝 건조하다" },
      { id: 103, text: "크게 당기진 않지만 만지면 살짝 까끌하고 푸석하다" },
      { id: 104, text: "속당김이 심하고 각질이 일어나며 갈라지는 느낌이다" },
    ],
  },
  {
    id: 2,
    text: "새 화장품을 발랐을 때 내 피부 반응은?",
    options: [
      { id: 201, text: "대부분 문제없이 잘 맞는다" },
      { id: 202, text: "가끔 따갑거나 붉어질 때가 있다" },
      { id: 203, text: "조금만 안 맞아도 쉽게 뒤집어진다" },
      { id: 204, text: "향이나 알코올감이 있으면 바로 자극을 느낀다" },
    ],
  },
  {
    id: 3,
    text: "햇빛을 오래 받았을 때 가장 자주 생기는 변화는?",
    options: [
      { id: 301, text: "금방 붉어졌다가 원래대로 돌아온다" },
      { id: 302, text: "잡티나 색소침착이 남는 편이다" },
      { id: 303, text: "톤이 쉽게 어두워지고 오래 간다" },
      { id: 304, text: "큰 변화는 적지만 건조함이 심해진다" },
    ],
  },
  {
    id: 4,
    text: "피부 표면의 모공과 결은 평소 어떤 편인가요?",
    options: [
      { id: 401, text: "모공이 크고 피지가 눈에 잘 보인다" },
      { id: 402, text: "부위별로 모공 차이가 크다" },
      { id: 403, text: "모공은 작지만 결이 거칠고 푸석하다" },
      { id: 404, text: "얇고 건조해서 잔결이 잘 보인다" },
    ],
  },
  {
    id: 5,
    text: "화장품을 고를 때 가장 먼저 보는 조건은?",
    options: [
      { id: 501, text: "유분감이 적고 산뜻한 사용감" },
      { id: 502, text: "장벽을 편안하게 해주는 저자극 여부" },
      { id: 503, text: "톤과 잡티 케어에 도움 되는 성분" },
      { id: 504, text: "깊은 보습과 탄력 케어" },
    ],
  },
  {
    id: 6,
    text: "손가락으로 볼을 살짝 눌렀다 뗐을 때, 내 피부는?",
    options: [
      { id: 601, text: "금방 통통하게 도로 올라온다" },
      { id: 602, text: "잠시 자국이 남았다가 천천히 돌아온다" },
      { id: 603, text: "누른 자리가 하얗게 각질처럼 일어난다" },
      { id: 604, text: "얇고 예민해 붉게 자국이 남는다" },
    ],
  },
  {
    id: 7,
    text: "환절기나 컨디션이 떨어질 때 가장 먼저 나타나는 신호는?",
    options: [
      { id: 701, text: "피지와 번들거림이 늘어난다" },
      { id: 702, text: "붉어짐과 따가움이 생긴다" },
      { id: 703, text: "잡티와 칙칙함이 도드라진다" },
      { id: 704, text: "당김과 잔주름이 두드러진다" },
    ],
  },
  {
    id: 8,
    text: "지금 가장 해결하고 싶은 피부 고민은?",
    options: [
      { id: 801, text: "피지와 모공" },
      { id: 802, text: "붉어짐과 자극" },
      { id: 803, text: "색소침착과 칙칙함" },
      { id: 804, text: "속건조와 잔주름" },
    ],
  },
];

const mockSkinTestResult: SkinTestResult = {
  result_id: MOCK_SKIN_TEST_RESULT_ID,
  skin_type: "dry",
  sensitivity: "high",
  type_code: "DRPW",
  title: "속부터 채우는 게 답인 타입",
  subtitle: "겉은 단단해도, 안에서부터 채워주는 케어가 필요해요.",
  recommended_effects: ["고보습", "미백", "안티에이징"],
  concern_tags: ["당김", "색소침착", "잔주름", "푸석함"],
  avoid_hint: ["강한 각질 제거", "건조감을 남기는 클렌징", "향이 강한 제품"],
  image_storage_key: "skin-types/DRPW/DRPW.png",
};

const skinTestHandlers = [
  http.get("*/api/skin-test/questions", () => {
    return HttpResponse.json({
      version: MOCK_SKIN_TEST_VERSION,
      questions: mockSkinTestQuestions,
    });
  }),
  http.post("*/api/skin-test/submit", async ({ request }) => {
    const body = (await request.json()) as SkinTestSubmitRequest;

    if (body.version !== MOCK_SKIN_TEST_VERSION || body.answers.length < mockSkinTestQuestions.length) {
      return HttpResponse.json(
        {
          error: {
            code: "INVALID_INPUT",
            message: "모든 문항에 답변해 주세요.",
          },
        },
        { status: 400 },
      );
    }

    return HttpResponse.json(mockSkinTestResult);
  }),
  http.get("*/api/skin-test/results/:resultId", ({ params }) => {
    const resultId = Number(params.resultId);

    if (resultId !== MOCK_SKIN_TEST_RESULT_ID) {
      return HttpResponse.json(
        {
          error: {
            code: "NOT_FOUND",
            message: "피부 타입 테스트 결과를 찾을 수 없습니다.",
          },
        },
        { status: 404 },
      );
    }

    return HttpResponse.json({
      result: mockSkinTestResult,
    });
  }),
  http.post("*/api/skin-test/apply-to-profile", async ({ request }) => {
    const body = (await request.json()) as { result_id?: number };

    if (body.result_id !== MOCK_SKIN_TEST_RESULT_ID) {
      return HttpResponse.json(
        {
          error: {
            code: "NOT_FOUND",
            message: "피부 타입 테스트 결과를 찾을 수 없습니다.",
          },
        },
        { status: 404 },
      );
    }

    return HttpResponse.json({
      success: true,
      skin_profile: {
        skin_type: mockSkinTestResult.skin_type,
        sensitivity: mockSkinTestResult.sensitivity,
        latest_skin_test_result_id: mockSkinTestResult.result_id,
      },
    });
  }),
];

const authHandlers = [
  http.post("*/api/auth/login", async ({ request }) => {
    const body = (await request.json()) as LoginRequestBody;

    if (body.email !== MOCK_LOGIN_EMAIL || body.password !== MOCK_LOGIN_PASSWORD) {
      return HttpResponse.json(
        {
          code: "INVALID_CREDENTIALS",
          message: "이메일 또는 비밀번호가 일치하지 않습니다.",
        },
        { status: 401 },
      );
    }

    return HttpResponse.json({
      access_token: "mock-access-token",
      refresh_token: "mock-refresh-token",
      user: { id: 1, email: body.email },
    });
  }),
  http.get("*/api/auth/check-email", ({ request }) => {
    const url = new URL(request.url);
    const email = url.searchParams.get("email");

    if (email === MOCK_DUPLICATE_SIGNUP_EMAIL) {
      return HttpResponse.json(
        {
          available: false,
          code: "EMAIL_ALREADY_EXISTS",
          message: "이미 가입된 이메일입니다.",
        },
        { status: 409 },
      );
    }

    return HttpResponse.json({
      available: true,
      message: "사용 가능한 이메일입니다.",
    });
  }),
  http.get("*/api/auth/check-nickname", ({ request }) => {
    const url = new URL(request.url);
    const nickname = url.searchParams.get("nickname");

    if (nickname === MOCK_DUPLICATE_SIGNUP_NICKNAME) {
      return HttpResponse.json(
        {
          available: false,
          code: "NICKNAME_ALREADY_EXISTS",
          message: "이미 사용 중인 닉네임입니다.",
        },
        { status: 409 },
      );
    }

    return HttpResponse.json({
      available: true,
      message: "사용 가능한 닉네임입니다.",
    });
  }),
  http.post("*/api/auth/signup", async ({ request }) => {
    const body = (await request.json()) as SignupRequestBody;

    if (body.email === MOCK_DUPLICATE_SIGNUP_EMAIL) {
      return HttpResponse.json(
        {
          code: "EMAIL_ALREADY_EXISTS",
          message: "이미 가입된 이메일입니다.",
        },
        { status: 409 },
      );
    }

    if (body.email === MOCK_SERVER_ERROR_SIGNUP_EMAIL) {
      return HttpResponse.json(
        {
          code: "INTERNAL_SERVER_ERROR",
          message: "서버 오류가 발생했습니다.",
        },
        { status: 500 },
      );
    }

    if (body.nickname === MOCK_DUPLICATE_SIGNUP_NICKNAME) {
      return HttpResponse.json(
        {
          code: "NICKNAME_ALREADY_EXISTS",
          message: "이미 사용 중인 닉네임입니다.",
        },
        { status: 409 },
      );
    }

    return HttpResponse.json({
      access_token: "mock-access-token",
      refresh_token: "mock-refresh-token",
      user: { id: 1, email: body.email, nickname: body.nickname, created_at: new Date().toISOString() },
    });
  }),
  http.post("*/api/auth/password-reset", async ({ request }) => {
    const body = (await request.json()) as PasswordResetRequestBody;

    return HttpResponse.json({
      message: "비밀번호 재설정 안내를 이메일로 보냈습니다.",
      email: body.email,
    });
  }),
];

const skinProfileHandlers = [
  http.post("*/api/skin-profile", async ({ request }) => {
    const body = (await request.json()) as SkinProfileRequestBody;

    if (body.skinType === "dry") {
      return HttpResponse.json(
        {
          code: "SKIN_PROFILE_SAVE_FAILED",
          message: "피부 타입 저장에 실패했습니다.",
        },
        { status: 500 },
      );
    }

    return HttpResponse.json(
      {
        skinProfile: {
          id: "mock-skin-profile-id",
          ...body,
        },
      },
      { status: 201 },
    );
  }),
];

export const handlers = [
  ...skinTestHandlers,
  ...skinProfileHandlers,
  ...(useAuthMock ? authHandlers : []),
];
