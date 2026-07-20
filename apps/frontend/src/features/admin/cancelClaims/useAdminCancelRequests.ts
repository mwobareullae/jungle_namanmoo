import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import { useAdminRowAction } from "../hooks/useAdminRowAction";
import {
  AdminCancelRequestAction,
  AdminCancelRequestActionResult,
  AdminCancelRequestPagination,
  AdminCancelRequestRow,
  AdminCancelRequestStatus,
  getAdminCancelRequests,
  postApproveCancelRequest,
  postRejectCancelRequest
} from "../api/adminOrderCancelRequestApi";

// 관리자 취소 요청 목록 조회 + 승인·거절 액션 훅 (M1.5-B, 2단계).
// 재고/가격 확인·주문 상태 확인과 같은 page/page_size 방식 페이지네이션을 쓴다(cursor 아님).

const describeApiError = (caughtError: unknown, fallbackMessage: string): string => {
  const apiError = caughtError as Partial<ApiError> | undefined;
  if (apiError?.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
  if (apiError?.status === 403) return "관리자 권한이 필요합니다.";
  return apiError?.message ?? fallbackMessage;
};

const DEFAULT_PAGE_SIZE = 50;

export type UseAdminCancelRequestsOptions = {
  enabled: boolean;
};

export function useAdminCancelRequests({ enabled }: UseAdminCancelRequestsOptions) {
  const [statusFilter, setStatusFilterState] = useState<AdminCancelRequestStatus | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const [items, setItems] = useState<AdminCancelRequestRow[]>([]);
  const [pagination, setPagination] = useState<AdminCancelRequestPagination | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 빠른 필터 변경 시 오래된 응답이 최신 결과를 덮지 않도록 요청 순번을 관리한다.
  const requestIdRef = useRef(0);
  const pageRef = useRef(page);
  useEffect(() => {
    pageRef.current = page;
  }, [page]);

  // useAdminRowAction 의 resync 콜백은 아래 fetchPage(현재 page 기준) 를 가리켜야 하는데,
  // fetchPage 자체가 useAdminRowAction 이 돌려주는 actionInFlightRef 를 필요로 해 서로를
  // 참조한다. ref 로 "최신 fetchPage" 를 담아 이 순환을 끊는다.
  const fetchPageRef = useRef<(targetPage: number, options?: { silent?: boolean }) => Promise<boolean>>(() =>
    Promise.resolve(false)
  );

  const { actionInFlightRef, actionTargetKey, actionError, syncWarning, runAction, clearActionError, clearSyncWarning } =
    useAdminRowAction<AdminCancelRequestRow, AdminCancelRequestActionResult>({
      setItems,
      getKey: (row) => row.requestCode,
      applyResult: (row, result) => ({
        ...row,
        status: result.status,
        statusLabel: result.statusLabel,
        decisionReason: result.decisionReason,
        processedAt: result.processedAt,
        availableActions: result.availableActions
      }),
      resync: () => fetchPageRef.current(pageRef.current, { silent: true }),
      resyncFailureMessage: "처리는 성공했지만 최신 목록 동기화에 실패했습니다. 새로고침을 눌러 최신 상태를 확인해 주세요.",
      describeError: describeApiError
    });

  const fetchPage = useCallback(
    async (targetPage: number, options?: { silent?: boolean }): Promise<boolean> => {
      // 액션 진행 중에는(승인·거절 호출이 아직 서버 응답을 기다리는 동안) 일반 조회(새로고침·페이지
      // 이동)를 시작하지 않는다 — 그렇지 않으면 이 조회와 액션 자신의 resync 가 같은 요청 순번
      // 경쟁에 들어가, 액션이 서버에 반영되기 전 상태를 담은 응답이 나중에 도착해 방금 낙관적으로
      // 반영한 행을 다시 예전 상태로 덮어쓸 수 있다.
      if (actionInFlightRef.current && !options?.silent) return false;
      const requestId = ++requestIdRef.current;
      // silent: 액션 성공 후 백그라운드 재조회용. 로딩 스피너·전체 에러 배너를 띄우지 않고,
      // 실패해도 이미 액션 응답으로 반영된 items 를 비우지 않는다(호출부가 별도 경고로 처리).
      if (!options?.silent) {
        setLoading(true);
        setError(null);
      }

      try {
        const result = await getAdminCancelRequests({
          status: statusFilter,
          page: targetPage,
          pageSize
        });
        if (requestId !== requestIdRef.current) return false; // 이후 요청이 이미 진행 중 — 이 응답은 버림

        setItems(result.items);
        setPagination(result.pagination);
        if (!options?.silent) clearSyncWarning(); // 정상 조회(새로고침·필터 변경) 성공 시 이전 동기화 경고를 해제
        return true;
      } catch (caughtError: unknown) {
        if (requestId !== requestIdRef.current) return false;
        if (!options?.silent) {
          setError(describeApiError(caughtError, "취소 요청 목록을 불러오지 못했습니다."));
          setItems([]);
          setPagination(null);
        }
        return false;
      } finally {
        if (requestId === requestIdRef.current && !options?.silent) {
          setLoading(false);
        }
      }
    },
    [statusFilter, pageSize, actionInFlightRef, clearSyncWarning]
  );

  useEffect(() => {
    fetchPageRef.current = fetchPage;
  }, [fetchPage]);

  useEffect(() => {
    if (!enabled) return;
    void Promise.resolve().then(() => fetchPage(page));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, statusFilter, pageSize, page]);

  const refresh = useCallback((): Promise<boolean> => {
    if (!enabled || actionInFlightRef.current) return Promise.resolve(false);
    return fetchPage(page);
  }, [enabled, fetchPage, page, actionInFlightRef]);

  const goToPage = useCallback(
    (targetPage: number) => {
      if (targetPage < 1 || actionInFlightRef.current) return;
      setPage(targetPage);
    },
    [actionInFlightRef]
  );

  const changePageSize = useCallback((value: number) => {
    setPageSize(value);
    setPage(1);
  }, []);

  const setStatusFilter = useCallback(
    (value: AdminCancelRequestStatus | null) => {
      if (actionInFlightRef.current) return;
      setStatusFilterState(value);
      setPage(1);
      clearActionError();
    },
    [actionInFlightRef, clearActionError]
  );

  const resetFilters = useCallback(() => {
    if (actionInFlightRef.current) return;
    setStatusFilterState(null);
    setPage(1);
    clearActionError();
  }, [actionInFlightRef, clearActionError]);

  const runCancelRequestAction = useCallback(
    (requestCode: string, action: AdminCancelRequestAction, rejectionReason?: string): Promise<boolean> =>
      runAction(
        requestCode,
        () =>
          action === "APPROVE"
            ? postApproveCancelRequest(requestCode)
            : postRejectCancelRequest(requestCode, rejectionReason ?? ""),
        action === "APPROVE" ? "승인에 실패했습니다." : "거절에 실패했습니다."
      ),
    [runAction]
  );

  return {
    items,
    pagination,
    loading,
    error,
    page,
    pageSize,
    statusFilter,
    setStatusFilter,
    setPageSize: changePageSize,
    resetFilters,
    refresh,
    goToPage,
    actionRequestCode: actionTargetKey,
    actionError,
    syncWarning,
    runCancelRequestAction,
    clearActionError
  };
}
