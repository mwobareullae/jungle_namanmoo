import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  CanonicalIngredientSearchItem,
  IngredientMappingDetail,
  IngredientMappingRow,
  IngredientMappingStatusFilter,
  IngredientMappingSummary,
  approveIngredientMapping,
  getIngredientMappingDetail,
  getIngredientMappings,
  holdIngredientMapping,
  rejectIngredientMapping,
  reopenIngredientMapping,
  searchCanonicalIngredients
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
  const filterScopeKey = `${statusFilter}::${submittedQuery}`;

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

  // 판정 후 상세 재조회를 위해 현재 선택 그룹을 ref 로 보관(selectedKey 는 표시용).
  const selectedRef = useRef<{ pendingCode: string; normalizedSourceName: string } | null>(null);
  const [selectedFilterScopeKey, setSelectedFilterScopeKey] = useState<string | null>(null);

  // 목록 조건이 바뀌면 이전 상세가 새 목록과 섞여 보이지 않도록 선택을 해제한다.
  // 진행 중인 상세 요청도 순번을 올려 늦게 도착한 응답을 버린다.
  const clearSelectedMapping = useCallback(() => {
    detailRequestIdRef.current += 1;
    selectedRef.current = null;
    setSelectedFilterScopeKey(null);
    setSelectedKey(null);
    setDetail(null);
    setDetailLoading(false);
    setDetailError(null);
  }, []);

  const applySearch = useCallback(() => {
    clearSelectedMapping();
    setSubmittedQuery(queryInput);
  }, [clearSelectedMapping, queryInput]);

  const changeStatusFilter = useCallback(
    (value: IngredientMappingStatusFilter) => {
      clearSelectedMapping();
      setStatusFilter(value);
    },
    [clearSelectedMapping]
  );

  const resetFilters = useCallback(() => {
    clearSelectedMapping();
    setStatusFilter("ALL");
    setQueryInput("");
    setSubmittedQuery("");
  }, [clearSelectedMapping]);

  const fetchDetail = useCallback(async (pendingCode: string, normalizedSourceName: string) => {
    const requestId = ++detailRequestIdRef.current;
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

  const selectMapping = useCallback(
    async (pendingCode: string, normalizedSourceName: string) => {
      setSelectedFilterScopeKey(filterScopeKey);
      setSelectedKey(`${pendingCode}::${normalizedSourceName}`);
      selectedRef.current = { pendingCode, normalizedSourceName };
      // 새 행 선택 중에는 이전 성분의 상세를 보여주지 않는다.
      setDetail(null);
      await fetchDetail(pendingCode, normalizedSourceName);
    },
    [fetchDetail, filterScopeKey]
  );

  // --- 판정 액션 (쓰기) ----------------------------------------------------
  const [decisionSubmitting, setDecisionSubmitting] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const decisionInFlightRef = useRef(false);

  const clearDecisionError = useCallback(() => setDecisionError(null), []);

  // 확인 모달 이후 즉시 실행. 중복 클릭을 막고, 성공 시 상세·목록을 재조회한다(계약 §10).
  const runDecision = useCallback(
    async (call: () => Promise<unknown>): Promise<boolean> => {
      const selected = selectedRef.current;
      if (!selected || decisionInFlightRef.current) return false;
      decisionInFlightRef.current = true;
      setDecisionSubmitting(true);
      setDecisionError(null);
      try {
        await call();
        await fetchDetail(selected.pendingCode, selected.normalizedSourceName);
        void fetchList("reset", null); // 상태·summary 갱신(기존 목록 유지)
        return true;
      } catch (caughtError: unknown) {
        setDecisionError(describeApiError(caughtError, "판정을 저장하지 못했습니다."));
        return false;
      } finally {
        decisionInFlightRef.current = false;
        setDecisionSubmitting(false);
      }
    },
    [fetchDetail, fetchList]
  );

  const approve = useCallback(
    (targetIngredientCode: string, decisionReason: string | null): Promise<boolean> => {
      const selected = selectedRef.current;
      if (!selected) return Promise.resolve(false);
      return runDecision(() =>
        approveIngredientMapping(
          selected.pendingCode,
          selected.normalizedSourceName,
          targetIngredientCode,
          decisionReason
        )
      );
    },
    [runDecision]
  );

  const hold = useCallback(
    (decisionReason: string): Promise<boolean> => {
      const selected = selectedRef.current;
      if (!selected) return Promise.resolve(false);
      return runDecision(() =>
        holdIngredientMapping(selected.pendingCode, selected.normalizedSourceName, decisionReason)
      );
    },
    [runDecision]
  );

  const reject = useCallback(
    (decisionReason: string): Promise<boolean> => {
      const selected = selectedRef.current;
      if (!selected) return Promise.resolve(false);
      return runDecision(() =>
        rejectIngredientMapping(selected.pendingCode, selected.normalizedSourceName, decisionReason)
      );
    },
    [runDecision]
  );

  const reopen = useCallback(
    (decisionReason: string): Promise<boolean> => {
      const selected = selectedRef.current;
      if (!selected) return Promise.resolve(false);
      return runDecision(() =>
        reopenIngredientMapping(selected.pendingCode, selected.normalizedSourceName, decisionReason)
      );
    },
    [runDecision]
  );

  // --- canonical 검색 (승인 target 선택용) ---------------------------------
  const [canonicalResults, setCanonicalResults] = useState<CanonicalIngredientSearchItem[]>([]);
  const [canonicalSearching, setCanonicalSearching] = useState(false);
  const [canonicalError, setCanonicalError] = useState<string | null>(null);
  const canonicalRequestIdRef = useRef(0);

  const searchCanonicals = useCallback(async (q: string) => {
    const trimmed = q.trim();
    const requestId = ++canonicalRequestIdRef.current;
    if (!trimmed) {
      setCanonicalResults([]);
      setCanonicalError(null);
      setCanonicalSearching(false);
      return;
    }
    setCanonicalSearching(true);
    setCanonicalError(null);
    try {
      const result = await searchCanonicalIngredients(trimmed, 20, null);
      if (requestId !== canonicalRequestIdRef.current) return;
      setCanonicalResults(result.items);
    } catch (caughtError: unknown) {
      if (requestId !== canonicalRequestIdRef.current) return;
      setCanonicalResults([]);
      setCanonicalError(describeApiError(caughtError, "canonical 성분 검색에 실패했습니다."));
    } finally {
      if (requestId === canonicalRequestIdRef.current) setCanonicalSearching(false);
    }
  }, []);

  const resetCanonicalSearch = useCallback(() => {
    canonicalRequestIdRef.current += 1;
    setCanonicalResults([]);
    setCanonicalError(null);
    setCanonicalSearching(false);
  }, []);

  const isSelectedInCurrentFilterScope = selectedFilterScopeKey === filterScopeKey;

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
    selectedKey: isSelectedInCurrentFilterScope ? selectedKey : null,
    detail: isSelectedInCurrentFilterScope ? detail : null,
    detailLoading: isSelectedInCurrentFilterScope && detailLoading,
    detailError: isSelectedInCurrentFilterScope ? detailError : null,
    selectMapping,
    decisionSubmitting,
    decisionError,
    clearDecisionError,
    approve,
    hold,
    reject,
    reopen,
    canonicalResults,
    canonicalSearching,
    canonicalError,
    searchCanonicals,
    resetCanonicalSearch
  };
}
