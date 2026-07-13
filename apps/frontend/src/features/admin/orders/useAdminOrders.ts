import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
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

const PAGE_SIZE = 50;

export type AdminOrderPreviewPatch = Partial<
  Pick<AdminOrderRow, "status" | "orderStatusRaw" | "paymentStatus" | "paymentStatusRaw" | "paymentMissing" | "stockReserved" | "updatedAt">
>;

export type UseAdminOrdersOptions = {
  enabled: boolean;
};

export function useAdminOrders({ enabled }: UseAdminOrdersOptions) {
  const [orderStatusFilter, setOrderStatusFilter] = useState<AdminOrderStatus | null>(null);
  const [paymentStatusFilter, setPaymentStatusFilter] = useState<AdminPaymentStatus | null>(null);

  const [items, setItems] = useState<AdminOrderRow[]>([]);
  const [summary, setSummary] = useState<AdminOrderSummary | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [previewOverrides, setPreviewOverrides] = useState<Record<string, AdminOrderPreviewPatch>>({});

  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 빠른 필터 변경 시 오래된 응답이 최신 결과를 덮지 않도록 요청 순번을 관리한다.
  const requestIdRef = useRef(0);
  // 최신 목록 요청이 진행 중인 동안 배송 전이를 시작하지 않도록 요청 ID를 ref 로 관리한다.
  // state 기반 loading 은 렌더 전에 즉시 바뀌지 않으므로 훅 내부 경합 방어에는 ref 가 필요하다.
  const activeListRequestIdRef = useRef<number | null>(null);
  // 같은 이벤트 루프 안에서 연속 입력이 들어와도 배송 처리와 목록 요청이 겹치지 않게 하는 즉시 잠금이다.
  const actionInFlightRef = useRef(false);

  const fetchPage = useCallback(
    async (options: { cursor: string | null; append: boolean; silent?: boolean }): Promise<boolean> => {
      if (actionInFlightRef.current && !options.silent) return false;
      const requestId = ++requestIdRef.current;
      activeListRequestIdRef.current = requestId;
      // silent: 배송 액션 성공 후 백그라운드 재조회용. 로딩 스피너·전체 에러 배너를 띄우지
      // 않고, 실패해도 이미 화면에 반영된 items 를 비우지 않는다(호출부가 별도 경고로 처리).
      if (!options.silent) {
        if (options.append) {
          setLoadingMore(true);
        } else {
          setLoading(true);
          // 새 기본 조회(필터 변경·새로고침)를 시작하면, 이전에 진행 중이던 "더 보기" 요청의
          // 결과는 버려질 것이므로 그 로딩 상태도 함께 정리한다(그렇지 않으면 더 보기 버튼이
          // loadingMore=true 로 영구히 멈출 수 있음).
          setLoadingMore(false);
        }
        setError(null);
      }

      try {
        const result = await getAdminOrders({
          orderStatus: orderStatusFilter,
          paymentStatus: paymentStatusFilter,
          limit: PAGE_SIZE,
          cursor: options.cursor
        });
        if (requestId !== requestIdRef.current) return false; // 이후 요청이 이미 진행 중 — 이 응답은 버림

        setItems((current) => (options.append ? [...current, ...result.items] : result.items));
        setSummary(result.summary);
        setNextCursor(result.nextCursor);
        if (!options.append) setPreviewOverrides({});
        return true;
      } catch (caughtError: unknown) {
        if (requestId !== requestIdRef.current) return false;
        if (!options.silent) {
          const apiError = caughtError as Partial<ApiError> | undefined;
          setError(apiError?.message ?? "주문 목록을 불러오지 못했습니다.");
          if (!options.append) {
            setItems([]);
            setSummary(null);
            setNextCursor(null);
          }
        }
        return false;
      } finally {
        if (activeListRequestIdRef.current === requestId) {
          activeListRequestIdRef.current = null;
        }
        // 이 요청이 여전히 최신 요청일 때만 로딩 상태를 정리한다(요청 경합 시 stale 요청이
        // 이후 요청의 로딩 상태를 잘못 끄는 것을 방지). 최신 요청이면 append 여부와 무관하게
        // loading·loadingMore 둘 다 정리해 어느 쪽도 영구히 켜진 채로 남지 않게 한다.
        if (requestId === requestIdRef.current && !options.silent) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [orderStatusFilter, paymentStatusFilter]
  );

  useEffect(() => {
    if (!enabled) return;
    void Promise.resolve().then(() => fetchPage({ cursor: null, append: false }));
  }, [enabled, fetchPage]);

  const refresh = useCallback((): Promise<boolean> => {
    if (!enabled || actionInFlightRef.current) return Promise.resolve(false);
    return fetchPage({ cursor: null, append: false });
  }, [enabled, fetchPage]);

  const loadMore = useCallback(() => {
    if (!enabled || !nextCursor || loadingMore || actionInFlightRef.current) return;
    void fetchPage({ cursor: nextCursor, append: true });
  }, [enabled, nextCursor, loadingMore, fetchPage]);

  const resetFilters = useCallback(() => {
    if (actionInFlightRef.current) return;
    setOrderStatusFilter(null);
    setPaymentStatusFilter(null);
  }, []);

  const applyPreviewOverride = useCallback((orderId: string, patch: AdminOrderPreviewPatch) => {
    setPreviewOverrides((current) => ({
      ...current,
      [orderId]: { ...current[orderId], ...patch }
    }));
  }, []);

  // 배송 전이(준비/시작/완료) 실 API 호출. previewOverrides 와 달리 로컬 미리보기가
  // 아니라 서버가 실제로 반영한 값이므로, 성공하면 items 안 해당 행을 서버 응답으로
  // 직접 교체한다(새로고침 없이 즉시 반영). 그 다음 현재 필터 기준 1페이지·summary 를
  // 백그라운드로 다시 조회해 필터에서 벗어난 주문 제거·요약 카드 갱신까지 맞춘다.
  const [actionOrderId, setActionOrderId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [syncWarning, setSyncWarning] = useState<string | null>(null);
  const applyShipmentActionResult = useCallback(
    (orderId: string, result: AdminOrderShipmentActionResult) => {
      setItems((current) =>
        current.map((item) =>
          item.id === orderId
            ? {
                ...item,
                status: result.status,
                orderStatusRaw: result.orderStatusRaw,
                availableActions: result.availableActions,
                updatedAt: result.updatedAt
              }
            : item
        )
      );
    },
    []
  );

  const resyncAfterShipmentAction = useCallback(async () => {
    const succeeded = await fetchPage({ cursor: null, append: false, silent: true });
    setSyncWarning(
      succeeded ? null : "배송 상태는 반영됐지만 목록 재조회에 실패했습니다. 새로고침을 눌러 최신 상태를 확인해 주세요."
    );
  }, [fetchPage]);

  const runShipmentAction = useCallback(
    async (orderId: string, orderCode: string, step: ShipmentStep): Promise<boolean> => {
      // 다른 배송 액션 또는 목록 조회가 진행 중이면 상태 전이를 시작하지 않는다.
      // 화면의 disabled 처리와 별개로 훅 내부에서도 경합을 차단한다.
      if (actionInFlightRef.current || activeListRequestIdRef.current !== null) return false;
      actionInFlightRef.current = true;
      setActionOrderId(orderId);
      setActionError(null);
      try {
        const call =
          step === "prepare" ? postShipPrepare : step === "dispatch" ? postShipDispatch : postShipDeliver;
        const result = await call(orderCode);
        applyShipmentActionResult(orderId, result);
        await resyncAfterShipmentAction();
        return true;
      } catch (caughtError: unknown) {
        const apiError = caughtError as Partial<ApiError> | undefined;
        setActionError(apiError?.message ?? "배송 상태 변경에 실패했습니다.");
        return false;
      } finally {
        actionInFlightRef.current = false;
        setActionOrderId(null);
      }
    },
    [applyShipmentActionResult, resyncAfterShipmentAction]
  );

  const clearShipmentActionFeedback = useCallback(() => {
    setActionError(null);
    setSyncWarning(null);
  }, []);

  const changeOrderStatusFilter = useCallback((value: AdminOrderStatus | null) => {
    if (actionInFlightRef.current) return;
    setOrderStatusFilter(value);
  }, []);

  const changePaymentStatusFilter = useCallback((value: AdminPaymentStatus | null) => {
    if (actionInFlightRef.current) return;
    setPaymentStatusFilter(value);
  }, []);

  // 서버 응답(items) 위에 로컬 미리보기(previewOverrides)만 얹어서 화면에 보여준다.
  // 서버 데이터·필터·summary는 이 과정에서 전혀 바뀌지 않는다.
  const mergedItems = useMemo(
    () =>
      items.map((item) => {
        const override = previewOverrides[item.id];
        return override ? { ...item, ...override } : item;
      }),
    [items, previewOverrides]
  );

  return {
    items: mergedItems,
    summary,
    hasMore: nextCursor !== null,
    loading,
    loadingMore,
    error,
    orderStatusFilter,
    paymentStatusFilter,
    setOrderStatusFilter: changeOrderStatusFilter,
    setPaymentStatusFilter: changePaymentStatusFilter,
    resetFilters,
    refresh,
    loadMore,
    applyPreviewOverride,
    actionOrderId,
    actionError,
    syncWarning,
    runShipmentAction,
    clearShipmentActionFeedback
  };
}
