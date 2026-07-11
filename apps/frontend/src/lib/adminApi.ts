import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";

// 관리자 API 공통 호출 기반. 기존 api.ts 의 base URL / fetch 래퍼 / JSON 파서를 재사용한다.
// fetchWithTimeout 은 credentials: "include" 라 세션 쿠키가 함께 전송되어 관리자 인증에 필요.
export const ADMIN_API_BASE = `${API_BASE_URL}/admin`;

export type AdminPingResponse = {
  status: string;
  scope: string;
};

export const adminApi = {
  async ping(): Promise<AdminPingResponse> {
    const response = await fetchWithTimeout(`${ADMIN_API_BASE}/ping`);
    return parseJson<AdminPingResponse>(response);
  }
};
