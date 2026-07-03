import { http, HttpResponse } from "msw";

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

const MOCK_LOGIN_EMAIL = "test@example.com";
const MOCK_LOGIN_PASSWORD = "password123";
const MOCK_DUPLICATE_SIGNUP_EMAIL = "duplicate@example.com";
const MOCK_DUPLICATE_SIGNUP_NICKNAME = "duplicate";
const MOCK_SERVER_ERROR_SIGNUP_EMAIL = "server-error@example.com";

export const handlers = [
  http.post("http://localhost:8000/api/auth/login", async ({ request }) => {
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
  http.get("http://localhost:8000/api/auth/check-email", ({ request }) => {
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
  http.get("http://localhost:8000/api/auth/check-nickname", ({ request }) => {
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
  http.post("http://localhost:8000/api/auth/signup", async ({ request }) => {
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
  http.post("http://localhost:8000/api/auth/password-reset", async ({ request }) => {
    const body = (await request.json()) as PasswordResetRequestBody;

    return HttpResponse.json({
      message: "비밀번호 재설정 안내를 이메일로 보냈습니다.",
      email: body.email,
    });
  }),
];
