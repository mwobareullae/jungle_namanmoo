import { API_BASE_URL } from "./api";
import type { AuthUser } from "../contexts/authContextValue";

type AccountErrorBody = {
  message?: string;
  error?: { message?: string };
};

async function accountApiError(response: Response, fallbackMessage: string): Promise<Error> {
  const errorBody = (await response.json().catch(() => null)) as AccountErrorBody | null;
  return new Error(errorBody?.message ?? errorBody?.error?.message ?? fallbackMessage);
}

export async function updateNickname(nickname: string): Promise<AuthUser> {
  const response = await fetch(`${API_BASE_URL}/me`, {
    method: "PATCH",
    credentials: "include",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ nickname })
  });

  if (!response.ok) {
    throw await accountApiError(response, "닉네임을 변경하지 못했습니다.");
  }

  return response.json() as Promise<AuthUser>;
}

export async function deleteAccount(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/me`, {
    method: "DELETE",
    credentials: "include"
  });

  if (response.ok) {
    return;
  }

  throw await accountApiError(response, "회원탈퇴 요청을 처리하지 못했습니다.");
}
