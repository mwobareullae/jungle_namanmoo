import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  AdminOrderRow,
  AdminOrderStatus,
  AdminOrderSummary,
  AdminPaymentStatus,
  getAdminOrders
} from "../api/adminOrderApi";

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

  const fetchPage = useCallback(
    async (options: { cursor: string | null; append: boolean }): Promise<boolean> => {
      const requestId = ++requestIdRef.current;
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
        const apiError = caughtError as Partial<ApiError> | undefined;
        setError(apiError?.message ?? "주문 목록을 불러오지 못했습니다.");
        if (!options.append) {
          setItems([]);
          setSummary(null);
          setNextCursor(null);
        }
        return false;
      } finally {
        // 이 요청이 여전히 최신 요청일 때만 로딩 상태를 정리한다(요청 경합 시 stale 요청이
        // 이후 요청의 로딩 상태를 잘못 끄는 것을 방지). 최신 요청이면 append 여부와 무관하게
        // loading·loadingMore 둘 다 정리해 어느 쪽도 영구히 켜진 채로 남지 않게 한다.
        if (requestId === requestIdRef.current) {
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
    if (!enabled) return Promise.resolve(false);
    return fetchPage({ cursor: null, append: false });
  }, [enabled, fetchPage]);

  const loadMore = useCallback(() => {
    if (!enabled || !nextCursor || loadingMore) return;
    void fetchPage({ cursor: nextCursor, append: true });
  }, [enabled, nextCursor, loadingMore, fetchPage]);

  const resetFilters = useCallback(() => {
    setOrderStatusFilter(null);
    setPaymentStatusFilter(null);
  }, []);

  const applyPreviewOverride = useCallback((orderId: string, patch: AdminOrderPreviewPatch) => {
    setPreviewOverrides((current) => ({
      ...current,
      [orderId]: { ...current[orderId], ...patch }
    }));
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
    setOrderStatusFilter,
    setPaymentStatusFilter,
    resetFilters,
    refresh,
    loadMore,
    applyPreviewOverride
  };
}
