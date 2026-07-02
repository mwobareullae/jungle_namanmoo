import { http, HttpResponse } from "msw";

export const handlers = [
  http.post("http://localhost:8000/api/auth/login", () => {
    return HttpResponse.json({
      access_token: "mock-access-token",
      refresh_token: "mock-refresh-token",
      user: { id: 1, email: "test@example.com" },
    });
  }),
];
