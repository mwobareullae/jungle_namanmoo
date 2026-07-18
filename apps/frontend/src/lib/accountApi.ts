import { API_BASE_URL } from "./api";

export async function deleteAccount(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/me`, {
    method: "DELETE",
    credentials: "include"
  });

  if (response.ok) {
    return;
  }

  const errorBody = (await response.json().catch(() => null)) as {
    message?: string;
    error?: { message?: string };
  } | null;
  throw new Error(
    errorBody?.message ?? errorBody?.error?.message ?? "회원탈퇴 요청을 처리하지 못했습니다."
  );
}
