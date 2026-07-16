import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  IngredientMappingDetail,
  IngredientMappingRow,
  IngredientMappingStatusFilter,
  IngredientMappingSummary,
  getIngredientMappingDetail,
  getIngredientMappings
} from "../api/adminIngredientMappingApi";

// 관리자 성분 매핑 검수 조회 훅 (P1-M2-A Chunk 4, 조회 전용).
// 목록은 cursor 기반 "더 보기". 로딩 UX(사용자 확정):
//   - 최초 진입: skeleton(기존 목록 없음).
//   - 필터·검색·더 보기: 기존 목록을 유지한 채 갱신 상태만 표시.
// 승인/보류/반려/재검토(쓰기)는 다음 Chunk에서 추가한다.

const PAGE_LIMIT = 50;

const describeApiError = (caughtError: unknown, fallbackMessage: string): string => {
  const apiError = caughtError as Partial<ApiError> | undefined;
  if (apiError?.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
  if (apiError?.status === 403) return "관리자 권한이 필요합니다.";
  return apiError?.message ?? fallbackMessage;
};

export type UseAdminIngredientMappingsOptions = {
  enabled: boolean;
};

export function useAdminIngredientMappings({ enabled }: UseAdminIngredientMappingsOptions) {
  const [statusFilter, setStatusFilter] = useState<IngredientMappingStatusFilter>("ALL");
  const [queryInput, setQueryInput] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");

  const [items, setItems] = useState<IngredientMappingRow[]>([]);
  const [summary, setSummary] = useState<IngredientMappingSummary | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);

  // 빠른 필터 변경 시 오래된 응답이 최신 결과를 덮지 않도록 순번을 관리한다.
  const requestIdRef = useRef(0);
  // "더 보기" 연타로 같은 cursor 를 중복 append 하지 않도록 단일 실행 가드.
  const loadMoreInFlightRef = useRef(false);

  // 필터·검색(reset)과 더 보기(append)를 하나의 fetch 로 처리한다.
  // reset 이면 목록을 교체(단, 요청 시작 시점에 비우지 않아 기존 목록이 유지됨), append 면 이어붙인다.
  const fetchList = useCallback(
    async (mode: "reset" | "append", cursor: string | null): Promise<boolean> => {
      const requestId = ++requestIdRef.current;
      if (mode === "append") setLoadingMore(true);
      else setLoading(true);
      setError(null);
      try {
        const result = await getIngredientMappings({
          status: statusFilter,
          q: submittedQuery.trim() || null,
          limit: PAGE_LIMIT,
          cursor
        });
        if (requestId !== requestIdRef.current) return false; // 이후 요청 진행 중 — 이 응답 버림
        setItems((prev) => (mode === "append" ? [...prev, ...result.items] : result.items));
        setSummary(result.summary);
        setNextCursor(result.nextCursor);
        setHasLoaded(true);
        return true;
      } catch (caughtError: unknown) {
        if (requestId !== requestIdRef.current) return false;
        // 갱신 실패 시 기존 목록은 유지하고 오류 배너만 표시(사용자 확정 UX).
        setError(describeApiError(caughtError, "성분 매핑 목록을 불러오지 못했습니다."));
        return false;
      } finally {
        if (requestId === requestIdRef.current) {
          if (mode === "append") setLoadingMore(false);
          else setLoading(false);
        }
      }
    },
    [statusFilter, submittedQuery]
  );

  // 필터·검색 변경 시 첫 페이지부터 다시 조회(cursor 초기화).
  useEffect(() => {
    if (!enabled) return;
    void Promise.resolve().then(() => fetchList("reset", null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, statusFilter, submittedQuery]);

  const applySearch = useCallback(() => {
    setSubmittedQuery(queryInput);
  }, [queryInput]);

  const changeStatusFilter = useCallback((value: IngredientMappingStatusFilter) => {
    setStatusFilter(value);
  }, []);

  const resetFilters = useCallback(() => {
    setStatusFilter("ALL");
    setQueryInput("");
    setSubmittedQuery("");
  }, []);

  const refresh = useCallback((): Promise<boolean> => {
    if (!enabled) return Promise.resolve(false);
    return fetchList("reset", null);
  }, [enabled, fetchList]);

  const loadMore = useCallback(async (): Promise<boolean> => {
    if (!enabled || nextCursor === null) return false;
    if (loadMoreInFlightRef.current) return false;
    loadMoreInFlightRef.current = true;
    try {
      return await fetchList("append", nextCursor);
    } finally {
      loadMoreInFlightRef.current = false;
    }
  }, [enabled, nextCursor, fetchList]);

  // 선택 그룹 상세. 목록과 별개 요청이므로 자체 순번 가드를 둔다.
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<IngredientMappingDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const detailRequestIdRef = useRef(0);

  const selectMapping = useCallback(async (pendingCode: string, normalizedSourceName: string) => {
    setSelectedKey(`${pendingCode}::${normalizedSourceName}`);
    const requestId = ++detailRequestIdRef.current;
    // 새 행 선택 중에는 이전 성분의 상세를 보여주지 않는다.
    setDetail(null);
    setDetailLoading(true);
    setDetailError(null);
    try {
      const result = await getIngredientMappingDetail(pendingCode, normalizedSourceName);
      if (requestId !== detailRequestIdRef.current) return;
      setDetail(result);
    } catch (caughtError: unknown) {
      if (requestId !== detailRequestIdRef.current) return;
      setDetail(null);
      setDetailError(describeApiError(caughtError, "성분 매핑 상세를 불러오지 못했습니다."));
    } finally {
      if (requestId === detailRequestIdRef.current) setDetailLoading(false);
    }
  }, []);

  return {
    statusFilter,
    queryInput,
    setQueryInput,
    items,
    summary,
    nextCursor,
    loading,
    loadingMore,
    error,
    hasLoaded,
    applySearch,
    setStatusFilter: changeStatusFilter,
    resetFilters,
    refresh,
    loadMore,
    selectedKey,
    detail,
    detailLoading,
    detailError,
    selectMapping
  };
}
