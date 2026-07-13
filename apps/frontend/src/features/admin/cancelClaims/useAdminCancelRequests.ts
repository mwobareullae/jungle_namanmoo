import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  AdminCancelRequestRow,
  AdminCancelRequestStatus,
  getAdminCancelRequests
} from "../api/adminOrderCancelRequestApi";

// 관리자 취소 요청 목록 조회 훅 (M1.5-B, 1단계: 조회만). 승인·거절 액션은 2단계에서 추가한다.

// 401/403 은 최초 진입 게이트(useAdminAccess)뿐 아니라 진입 후 세션 만료·권한 변경으로도
// 발생할 수 있으므로 목록 재조회 실패 메시지에서도 구분해 안내한다.
const describeApiError = (caughtError: unknown, fallbackMessage: string): string => {
  const apiError = caughtError as Partial<ApiError> | undefined;
  if (apiError?.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
  if (apiError?.status === 403) return "관리자 권한이 필요합니다.";
  return apiError?.message ?? fallbackMessage;
};

const PAGE_SIZE = 50;

export type UseAdminCancelRequestsOptions = {
  enabled: boolean;
};

export function useAdminCancelRequests({ enabled }: UseAdminCancelRequestsOptions) {
  const [statusFilter, setStatusFilterState] = useState<AdminCancelRequestStatus | null>(null);
  const [items, setItems] = useState<AdminCancelRequestRow[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 빠른 필터 변경 시 오래된 응답이 최신 결과를 덮지 않도록 요청 순번을 관리한다.
  const requestIdRef = useRef(0);

  const fetchPage = useCallback(
    async (options: { cursor: string | null; append: boolean }): Promise<boolean> => {
      const requestId = ++requestIdRef.current;
      if (options.append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
        setLoadingMore(false);
      }
      setError(null);

      try {
        const result = await getAdminCancelRequests({
          status: statusFilter,
          limit: PAGE_SIZE,
          cursor: options.cursor
        });
        if (requestId !== requestIdRef.current) return false; // 이후 요청이 이미 진행 중 — 이 응답은 버림

        setItems((current) => (options.append ? [...current, ...result.items] : result.items));
        setNextCursor(result.nextCursor);
        return true;
      } catch (caughtError: unknown) {
        if (requestId !== requestIdRef.current) return false;
        setError(describeApiError(caughtError, "취소 요청 목록을 불러오지 못했습니다."));
        if (!options.append) {
          setItems([]);
          setNextCursor(null);
        }
        return false;
      } finally {
        if (requestId === requestIdRef.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [statusFilter]
  );

  useEffect(() => {
    if (!enabled) return;
    void Promise.resolve().then(() => fetchPage({ cursor: null, append: false }));
  }, [enabled, fetchPage]);

  const refresh = useCallback((): Promise<boolean> => {
    if (!enabled) return Promise.resolve(false);
    return fetchPage({ cursor: null, append: false });
  }, [enabled, fetchPage]);

  const loadMore = useCallback(() => {
    if (!enabled || !nextCursor || loadingMore) return;
    void fetchPage({ cursor: nextCursor, append: true });
  }, [enabled, nextCursor, loadingMore, fetchPage]);

  const setStatusFilter = useCallback((value: AdminCancelRequestStatus | null) => {
    setStatusFilterState(value);
  }, []);

  const resetFilters = useCallback(() => {
    setStatusFilterState(null);
  }, []);

  return {
    items,
    hasMore: nextCursor !== null,
    loading,
    loadingMore,
    error,
    statusFilter,
    setStatusFilter,
    resetFilters,
    refresh,
    loadMore
  };
}
