import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import { getAdminDashboardSummary, type AdminDashboardSummary } from "../api/adminDashboardApi";

const describeApiError = (caughtError: unknown): string => {
  const apiError = caughtError as Partial<ApiError> | undefined;
  if (apiError?.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
  if (apiError?.status === 403) return "관리자 권한이 필요합니다.";
  return apiError?.message ?? "운영 현황을 불러오지 못했습니다.";
};

export type UseAdminDashboardSummaryOptions = {
  enabled: boolean;
};

export function useAdminDashboardSummary({ enabled }: UseAdminDashboardSummaryOptions) {
  const [data, setData] = useState<AdminDashboardSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  const fetchSummary = useCallback(async (): Promise<void> => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const result = await getAdminDashboardSummary();
      if (requestId !== requestIdRef.current) return;
      setData(result);
    } catch (caughtError: unknown) {
      if (requestId !== requestIdRef.current) return;
      setError(describeApiError(caughtError));
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void Promise.resolve().then(() => fetchSummary());
  }, [enabled, fetchSummary]);

  return { data, loading, error, refresh: fetchSummary };
}
