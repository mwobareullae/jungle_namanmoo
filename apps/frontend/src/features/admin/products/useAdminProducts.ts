import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  AdminProductDetail,
  AdminProductPagination,
  AdminProductRow,
  AdminSalesStatus,
  getAdminProductDetail,
  getAdminProducts
} from "../api/adminProductApi";

// 관리자 상품 조회 훅 (P1-M3-A, 조회 전용). 목록·필터·페이지네이션 + 선택 상품 상세.
// 쓰기(등록/수정)는 Chunk 4~5에서 별도 추가한다.

const PAGE_SIZE = 50;

// 401/403 은 진입 후 세션 만료·권한 변경으로도 발생할 수 있어 목록 조회 실패 메시지에서도 구분한다.
const describeApiError = (caughtError: unknown, fallbackMessage: string): string => {
  const apiError = caughtError as Partial<ApiError> | undefined;
  if (apiError?.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
  if (apiError?.status === 403) return "관리자 권한이 필요합니다.";
  return apiError?.message ?? fallbackMessage;
};

export type AdminProductActiveFilter = "all" | "active" | "inactive";

export type UseAdminProductsOptions = {
  enabled: boolean;
};

export function useAdminProducts({ enabled }: UseAdminProductsOptions) {
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<AdminProductActiveFilter>("all");
  const [salesStatusFilter, setSalesStatusFilter] = useState<AdminSalesStatus | null>(null);
  const [page, setPage] = useState(1);

  const [items, setItems] = useState<AdminProductRow[]>([]);
  const [pagination, setPagination] = useState<AdminProductPagination | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 빠른 필터 변경 시 오래된 응답이 최신 결과를 덮지 않도록 요청 순번을 관리한다.
  const requestIdRef = useRef(0);

  const isActiveValue = activeFilter === "all" ? null : activeFilter === "active";

  const fetchPage = useCallback(
    async (targetPage: number): Promise<boolean> => {
      const requestId = ++requestIdRef.current;
      setLoading(true);
      setError(null);
      try {
        const result = await getAdminProducts({
          q: query.trim() || null,
          isActive: isActiveValue,
          salesStatus: salesStatusFilter,
          page: targetPage,
          pageSize: PAGE_SIZE
        });
        if (requestId !== requestIdRef.current) return false; // 이후 요청이 이미 진행 중 — 이 응답은 버림
        setItems(result.items);
        setPagination(result.pagination);
        return true;
      } catch (caughtError: unknown) {
        if (requestId !== requestIdRef.current) return false;
        setError(describeApiError(caughtError, "상품 목록을 불러오지 못했습니다."));
        setItems([]);
        setPagination(null);
        return false;
      } finally {
        if (requestId === requestIdRef.current) setLoading(false);
      }
    },
    [query, isActiveValue, salesStatusFilter]
  );

  useEffect(() => {
    if (!enabled) return;
    void Promise.resolve().then(() => fetchPage(page));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, query, activeFilter, salesStatusFilter, page]);

  const applySearch = useCallback((value: string) => {
    setQuery(value);
    setPage(1);
  }, []);

  const changeActiveFilter = useCallback((value: AdminProductActiveFilter) => {
    setActiveFilter(value);
    setPage(1);
  }, []);

  const changeSalesStatusFilter = useCallback((value: AdminSalesStatus | null) => {
    setSalesStatusFilter(value);
    setPage(1);
  }, []);

  const resetFilters = useCallback(() => {
    setQuery("");
    setActiveFilter("all");
    setSalesStatusFilter(null);
    setPage(1);
  }, []);

  const refresh = useCallback((): Promise<boolean> => {
    if (!enabled) return Promise.resolve(false);
    return fetchPage(page);
  }, [enabled, fetchPage, page]);

  const goToPage = useCallback((targetPage: number) => {
    if (targetPage < 1) return;
    setPage(targetPage);
  }, []);

  // 선택 상품 상세. 목록과 별개 요청이므로 자체 순번 가드를 둔다.
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminProductDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const detailRequestIdRef = useRef(0);

  const selectProduct = useCallback(async (productCode: string) => {
    setSelectedCode(productCode);
    const requestId = ++detailRequestIdRef.current;
    setDetailLoading(true);
    setDetailError(null);
    try {
      const result = await getAdminProductDetail(productCode);
      if (requestId !== detailRequestIdRef.current) return;
      setDetail(result);
    } catch (caughtError: unknown) {
      if (requestId !== detailRequestIdRef.current) return;
      setDetail(null);
      setDetailError(describeApiError(caughtError, "상품 상세를 불러오지 못했습니다."));
    } finally {
      if (requestId === detailRequestIdRef.current) setDetailLoading(false);
    }
  }, []);

  return {
    items,
    pagination,
    loading,
    error,
    page,
    query,
    activeFilter,
    salesStatusFilter,
    applySearch,
    setActiveFilter: changeActiveFilter,
    setSalesStatusFilter: changeSalesStatusFilter,
    resetFilters,
    refresh,
    goToPage,
    selectedCode,
    detail,
    detailLoading,
    detailError,
    selectProduct
  };
}
