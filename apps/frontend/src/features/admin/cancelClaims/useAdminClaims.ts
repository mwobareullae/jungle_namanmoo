import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  AdminClaimRow,
  AdminClaimStatus,
  AdminClaimType,
  getAdminClaims
} from "../api/adminOrderClaimApi";

// 관리자 클레임 목록 조회 훅 (M1.5-B, 1단계: 조회만). 승인·거절·처리시작·완료 액션은 3단계에서 추가한다.
// 취소 요청과 달리 클레임 목록은 계약대로 page/page_size 방식 페이지네이션을 쓴다(cursor 아님).

// 401/403 은 최초 진입 게이트(useAdminAccess)뿐 아니라 진입 후 세션 만료·권한 변경으로도
// 발생할 수 있으므로 목록 재조회 실패 메시지에서도 구분해 안내한다.
const describeApiError = (caughtError: unknown, fallbackMessage: string): string => {
  const apiError = caughtError as Partial<ApiError> | undefined;
  if (apiError?.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
  if (apiError?.status === 403) return "관리자 권한이 필요합니다.";
  return apiError?.message ?? fallbackMessage;
};

const PAGE_SIZE = 20;

export type UseAdminClaimsOptions = {
  enabled: boolean;
};

export function useAdminClaims({ enabled }: UseAdminClaimsOptions) {
  const [statusFilter, setStatusFilterState] = useState<AdminClaimStatus | null>(null);
  const [claimTypeFilter, setClaimTypeFilterState] = useState<AdminClaimType | null>(null);
  const [page, setPage] = useState(1);

  const [items, setItems] = useState<AdminClaimRow[]>([]);
  const [totalCount, setTotalCount] = useState(0);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 빠른 필터 변경 시 오래된 응답이 최신 결과를 덮지 않도록 요청 순번을 관리한다.
  const requestIdRef = useRef(0);

  const fetchPage = useCallback(
    async (targetPage: number): Promise<boolean> => {
      const requestId = ++requestIdRef.current;
      setLoading(true);
      setError(null);

      try {
        const result = await getAdminClaims({
          status: statusFilter,
          claimType: claimTypeFilter,
          page: targetPage,
          pageSize: PAGE_SIZE
        });
        if (requestId !== requestIdRef.current) return false; // 이후 요청이 이미 진행 중 — 이 응답은 버림

        setItems(result.items);
        setTotalCount(result.totalCount);
        return true;
      } catch (caughtError: unknown) {
        if (requestId !== requestIdRef.current) return false;
        setError(describeApiError(caughtError, "클레임 목록을 불러오지 못했습니다."));
        setItems([]);
        setTotalCount(0);
        return false;
      } finally {
        if (requestId === requestIdRef.current) {
          setLoading(false);
        }
      }
    },
    [statusFilter, claimTypeFilter]
  );

  useEffect(() => {
    if (!enabled) return;
    void Promise.resolve().then(() => fetchPage(page));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, statusFilter, claimTypeFilter, page]);

  const refresh = useCallback((): Promise<boolean> => {
    if (!enabled) return Promise.resolve(false);
    return fetchPage(page);
  }, [enabled, fetchPage, page]);

  const goToPage = useCallback(
    (targetPage: number) => {
      if (targetPage < 1) return;
      setPage(targetPage);
    },
    []
  );

  const setStatusFilter = useCallback((value: AdminClaimStatus | null) => {
    setStatusFilterState(value);
    setPage(1);
  }, []);

  const setClaimTypeFilter = useCallback((value: AdminClaimType | null) => {
    setClaimTypeFilterState(value);
    setPage(1);
  }, []);

  const resetFilters = useCallback(() => {
    setStatusFilterState(null);
    setClaimTypeFilterState(null);
    setPage(1);
  }, []);

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  return {
    items,
    page,
    pageSize: PAGE_SIZE,
    totalCount,
    totalPages,
    loading,
    error,
    statusFilter,
    claimTypeFilter,
    setStatusFilter,
    setClaimTypeFilter,
    resetFilters,
    refresh,
    goToPage
  };
}
