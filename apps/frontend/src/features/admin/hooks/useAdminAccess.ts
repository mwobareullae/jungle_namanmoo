import { useEffect, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import { adminApi } from "../api/adminApi";

// 관리자 화면 진입 시 ping 으로 인증/인가 상태를 확인한다.
// checking → authenticated / unauthenticated(401) / forbidden(403) / error(그 외)
export type AdminAccessStatus = "checking" | "authenticated" | "unauthenticated" | "forbidden" | "error";

export type AdminAccessState = {
  status: AdminAccessStatus;
  retry: () => void;
};

export function useAdminAccess(): AdminAccessState {
  const [status, setStatus] = useState<AdminAccessStatus>("checking");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    void Promise.resolve().then(async () => {
      if (cancelled) return;
      setStatus("checking");
      try {
        await adminApi.ping();
        if (!cancelled) setStatus("authenticated");
      } catch (error: unknown) {
        if (cancelled) return;
        const apiError = error as Partial<ApiError> | undefined;
        if (apiError?.status === 401) setStatus("unauthenticated");
        else if (apiError?.status === 403) setStatus("forbidden");
        else setStatus("error");
      }
    });

    return () => {
      cancelled = true;
    };
  }, [attempt]);

  return {
    status,
    retry: () => setAttempt((current) => current + 1)
  };
}
