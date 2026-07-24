import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import { useAdminRowAction } from "../hooks/useAdminRowAction";
import {
  AdminOrderPagination,
  AdminOrderRow,
  AdminOrderShipmentActionResult,
  AdminOrderStatus,
  AdminOrderSummary,
  AdminPaymentStatus,
  getAdminOrders,
  postShipDeliver,
  postShipDispatch,
  postShipPrepare
} from "../api/adminOrderApi";

export type ShipmentStep = "prepare" | "dispatch" | "deliver";

const DEFAULT_PAGE_SIZE = 50;
const AUTO_REFRESH_INTERVAL_MS = 30_000;

const describeApiError = (caughtError: unknown, fallbackMessage: string): string => {
  const apiError = caughtError as Partial<ApiError> | undefined;
  return apiError?.message ?? fallbackMessage;
};

export type UseAdminOrdersOptions = {
  enabled: boolean;
};

export function useAdminOrders({ enabled }: UseAdminOrdersOptions) {
  const [orderStatusFilter, setOrderStatusFilter] = useState<AdminOrderStatus | null>(null);
  const [paymentStatusFilter, setPaymentStatusFilter] = useState<AdminPaymentStatus | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const [items, setItems] = useState<AdminOrderRow[]>([]);
  const [summary, setSummary] = useState<AdminOrderSummary | null>(null);
  const [pagination, setPagination] = useState<AdminOrderPagination | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 빠른 필터 변경 시 오래된 응답이 최신 결과를 덮지 않도록 요청 순번을 관리한다.
  const requestIdRef = useRef(0);
  // 최신 목록 요청이 진행 중인 동안 배송 전이를 시작하지 않도록 요청 ID를 ref 로 관리한다.
  // state 기반 loading 은 렌더 전에 즉시 바뀌지 않으므로 훅 내부 경합 방어에는 ref 가 필요하다.
  const activeListRequestIdRef = useRef<number | null>(null);
  // 최신 page/pageSize/필터를 담아둔다 — 자동 새로고침·resync 콜백이 클로저에 갇힌 값이
  // 아니라 항상 "지금 보고 있는 페이지"를 다시 조회하도록 하기 위함이다.
  const currentQueryRef = useRef({ page, pageSize, orderStatusFilter, paymentStatusFilter });
  useEffect(() => {
    currentQueryRef.current = { page, pageSize, orderStatusFilter, paymentStatusFilter };
  }, [orderStatusFilter, page, pageSize, paymentStatusFilter]);

  // useAdminRowAction 의 resync 콜백은 아래 fetchPage 를 가리켜야 하는데, fetchPage 자체가
  // useAdminRowAction 이 돌려주는 actionInFlightRef 를 필요로 해 서로를 참조한다. ref 로
  // "최신 fetchPage" 를 담아 이 순환을 끊는다.
  const fetchPageRef = useRef<
    (options: { targetPage: number; silent?: boolean }) => Promise<"success" | "stale" | "error">
  >(() => Promise.resolve("stale"));

  const { actionInFlightRef, actionTargetKey, actionError, syncWarning, runAction, clearFeedback } =
    useAdminRowAction<AdminOrderRow, AdminOrderShipmentActionResult>({
      setItems,
      getKey: (row) => row.id,
      applyResult: (row, result) => ({
        ...row,
        status: result.status,
        orderStatusRaw: result.orderStatusRaw,
        shippedAt: result.shippedAt,
        deliveredAt: result.deliveredAt,
        availableActions: result.availableActions,
        updatedAt: result.updatedAt
      }),
      // 배송 액션 성공 후에는 지금 보고 있는 페이지를 그대로 다시 조회한다(페이지 1로
      // 돌아가지 않음 — 관리자가 다른 페이지를 보던 중이었다면 그 자리를 유지).
      // superseded(다른 요청에 새치기당함)는 실패가 아니므로 syncWarning을 띄우지 않는다.
      resync: async () => {
        const outcome = await fetchPageRef.current({ targetPage: currentQueryRef.current.page, silent: true });
        return outcome !== "error";
      },
      resyncFailureMessage: "배송 상태는 반영됐지만 목록 재조회에 실패했습니다. 새로고침을 눌러 최신 상태를 확인해 주세요.",
      describeError: describeApiError
    });

  // superseded(다른 요청에 새치기당함)와 실제 오류를 구분해야 호출부가 "새로고침 실패"를
  // 오발생시키지 않는다 — 둘 다 false로 뭉뚱그리면 새로고침 도중 필터를 바꾸는 정상적인
  // 조작에도 실패 알림이 잘못 뜬다.
  const fetchPage = useCallback(
    async (options: { targetPage: number; silent?: boolean }): Promise<"success" | "stale" | "error"> => {
      if (actionInFlightRef.current && !options.silent) return "stale";
      const requestId = ++requestIdRef.current;
      activeListRequestIdRef.current = requestId;
      // silent: 배송 액션 성공 후·30초 자동 새로고침용. 로딩 스피너·전체 에러 배너를 띄우지
      // 않고, 실패해도 이미 화면에 반영된 items 를 비우지 않는다(호출부가 별도 경고로 처리).
      if (!options.silent) {
        setLoading(true);
        setError(null);
      }

      try {
        const result = await getAdminOrders({
          orderStatus: orderStatusFilter,
          paymentStatus: paymentStatusFilter,
          page: options.targetPage,
          pageSize
        });
        if (requestId !== requestIdRef.current) return "stale"; // 이후 요청이 이미 진행 중 — 이 응답은 버림

        setItems(result.items);
        setSummary(result.summary);
        setPagination(result.pagination);
        return "success";
      } catch (caughtError: unknown) {
        if (requestId !== requestIdRef.current) return "stale";
        if (!options.silent) {
          setError(describeApiError(caughtError, "주문 목록을 불러오지 못했습니다."));
          setItems([]);
          setSummary(null);
          setPagination(null);
        }
        return "error";
      } finally {
        if (activeListRequestIdRef.current === requestId) {
          activeListRequestIdRef.current = null;
        }
        if (requestId === requestIdRef.current && !options.silent) {
          setLoading(false);
        }
      }
    },
    [orderStatusFilter, paymentStatusFilter, pageSize, actionInFlightRef]
  );

  useEffect(() => {
    fetchPageRef.current = fetchPage;
  }, [fetchPage]);

  useEffect(() => {
    if (!enabled) return;
    void Promise.resolve().then(() => fetchPage({ targetPage: page }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, orderStatusFilter, paymentStatusFilter, pageSize, page]);

  // 고객 결제·결제 만료 배치 등 다른 화면/프로세스에서 바뀐 상태를 열린 관리자 화면에도 반영한다.
  // 화면이 보일 때만 30초마다 조용히 재조회하고, 다른 탭에서 돌아오거나 창이 다시 포커스되면 즉시 갱신한다.
  // 배송 액션·목록 조회 중에는 새 요청을 겹치지 않아 기존 요청의 상태와 응답 순서를 보존한다.
  // 지금 보고 있는 페이지를 그대로 다시 조회한다(다른 페이지를 보고 있었는데 1페이지로
  // 조용히 되돌아가면, 관리자가 원래 보던 주문을 잃어버린 것처럼 느낄 수 있다).
  useEffect(() => {
    if (!enabled) return;

    const refreshIfAvailable = () => {
      if (document.visibilityState !== "visible") return;
      if (actionInFlightRef.current || activeListRequestIdRef.current !== null) return;
      void fetchPage({ targetPage: currentQueryRef.current.page, silent: true });
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") refreshIfAvailable();
    };

    const intervalId = window.setInterval(refreshIfAvailable, AUTO_REFRESH_INTERVAL_MS);
    window.addEventListener("focus", refreshIfAvailable);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", refreshIfAvailable);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [enabled, fetchPage, actionInFlightRef]);

  const refresh = useCallback((): Promise<"success" | "stale" | "error"> => {
    if (!enabled || actionInFlightRef.current) return Promise.resolve("stale");
    return fetchPage({ targetPage: page });
  }, [enabled, fetchPage, actionInFlightRef, page]);

  const goToPage = useCallback((targetPage: number) => {
    if (targetPage < 1) return;
    setPage(targetPage);
  }, []);

  const changePageSize = useCallback((value: number) => {
    setPageSize(value);
    setPage(1);
  }, []);

  const resetFilters = useCallback(() => {
    if (actionInFlightRef.current) return;
    setOrderStatusFilter(null);
    setPaymentStatusFilter(null);
    setPage(1);
  }, [actionInFlightRef]);

  // 배송 전이(준비/시작/완료) 실 API 호출. 성공하면 items 안 해당 행을 서버 응답으로
  // 직접 교체한다(새로고침 없이 즉시 반영). 그 다음 현재 페이지·summary 를 백그라운드로
  // 다시 조회해 필터에서 벗어난 주문 제거·요약 카드 갱신까지 맞춘다.
  const runShipmentAction = useCallback(
    (orderId: string, orderCode: string, step: ShipmentStep): Promise<boolean> => {
      // 다른 배송 액션 또는 목록 조회가 진행 중이면 상태 전이를 시작하지 않는다.
      // 화면의 disabled 처리와 별개로 훅 내부에서도 경합을 차단한다.
      if (activeListRequestIdRef.current !== null) return Promise.resolve(false);
      const call = step === "prepare" ? postShipPrepare : step === "dispatch" ? postShipDispatch : postShipDeliver;
      return runAction(orderId, () => call(orderCode), "배송 상태 변경에 실패했습니다.");
    },
    [runAction]
  );

  const changeOrderStatusFilter = useCallback(
    (value: AdminOrderStatus | null) => {
      if (actionInFlightRef.current) return;
      setOrderStatusFilter(value);
      setPage(1);
    },
    [actionInFlightRef]
  );

  const changePaymentStatusFilter = useCallback(
    (value: AdminPaymentStatus | null) => {
      if (actionInFlightRef.current) return;
      setPaymentStatusFilter(value);
      setPage(1);
    },
    [actionInFlightRef]
  );

  return {
    items,
    summary,
    pagination,
    loading,
    error,
    page,
    pageSize,
    orderStatusFilter,
    paymentStatusFilter,
    setOrderStatusFilter: changeOrderStatusFilter,
    setPaymentStatusFilter: changePaymentStatusFilter,
    setPageSize: changePageSize,
    resetFilters,
    refresh,
    goToPage,
    actionOrderId: actionTargetKey,
    actionError,
    syncWarning,
    runShipmentAction,
    clearShipmentActionFeedback: clearFeedback
  };
}
