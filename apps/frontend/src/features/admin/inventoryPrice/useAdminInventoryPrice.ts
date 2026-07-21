import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  AdminProductMasterOption,
  AdminProductPagination,
  getAdminProductBrands,
  getAdminProductCategories,
  updateAdminProduct
} from "../api/adminProductApi";
import {
  adjustAdminInventoryStock,
  getAdminInventoryHistory,
  getAdminInventorySummary,
  listAdminInventoryPrices,
  startAdminProductSale,
  updateAdminInventoryPrice,
  type AdminInventoryMovement,
  type AdminInventoryPriceItem,
  type AdminInventorySummary
} from "../api/adminInventoryPriceApi";

// 재고/가격 확인 목록 훅. 상품 조회(useAdminProducts)와 같은 page 방식 + 필터
// 소유 구조로 맞춘다 — 필터를 바꾸면 그 자리에서 바로 1페이지로 다시 조회한다.

const DEFAULT_PAGE_SIZE = 50;

type PendingAction = "stock" | "price" | "sale" | "hide" | null;

export type AdminInventoryActiveFilter = "all" | "active" | "inactive";
export type AdminInventorySalesStatusFilter = "" | "ON_SALE" | "SOLD_OUT" | "HIDDEN";
export type AdminInventoryStockStatusFilter = "" | "IN_STOCK" | "LOW_STOCK" | "SOLD_OUT" | "HIDDEN";

const describeApiError = (caughtError: unknown, fallbackMessage: string): string => {
  const apiError = caughtError as Partial<ApiError> | undefined;
  if (apiError?.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
  if (apiError?.status === 403) return "관리자 권한이 필요합니다.";

  switch (apiError?.code) {
    case "PRODUCT_NOT_HIDDEN":
      return "이미 판매 시작 대상이 아닌 상품입니다. 목록을 새로고침해 상태를 확인해 주세요.";
    case "PRICE_NOT_READY":
      return "판매 시작 전 자사몰 가격을 1원 이상으로 설정해 주세요.";
    case "INSUFFICIENT_STOCK_FOR_SALE":
      return "판매 시작에 필요한 가용 재고가 없습니다.";
    case "BRAND_INACTIVE":
      return "현재 브랜드가 비활성 상태라 판매를 시작할 수 없습니다.";
    case "CATEGORY_INACTIVE":
      return "현재 카테고리가 비활성 상태라 판매를 시작할 수 없습니다.";
    case "INVENTORY_AVAILABLE_QUANTITY_NEGATIVE":
      return "예약·안전 재고보다 적은 수량으로는 재고를 저장할 수 없습니다.";
    case "INVENTORY_ROW_NOT_FOUND":
      return "재고 정보가 없는 상품입니다.";
    case "INVALID_INVENTORY_STOCK":
      return "재고는 0 이상 1,000,000 이하의 정수로 입력해 주세요.";
    case "INVALID_PRICE":
      return "가격은 1원 이상 100,000,000원 이하의 정수로 입력해 주세요.";
    default:
      return apiError?.message ?? fallbackMessage;
  }
};

export function useAdminInventoryPrice({ enabled }: { enabled: boolean }) {
  const [query, setQuery] = useState("");
  const [brandCodeFilter, setBrandCodeFilterState] = useState<string | null>(null);
  const [categoryCodeFilter, setCategoryCodeFilterState] = useState<string | null>(null);
  const [activeFilter, setActiveFilterState] = useState<AdminInventoryActiveFilter>("all");
  const [salesStatusFilter, setSalesStatusFilterState] = useState<AdminInventorySalesStatusFilter>("");
  const [stockStatusFilter, setStockStatusFilterState] = useState<AdminInventoryStockStatusFilter>("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const [items, setItems] = useState<AdminInventoryPriceItem[]>([]);
  const [pagination, setPagination] = useState<AdminProductPagination | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [brands, setBrands] = useState<AdminProductMasterOption[]>([]);
  const [categories, setCategories] = useState<AdminProductMasterOption[]>([]);

  const [summary, setSummary] = useState<AdminInventorySummary | null>(null);
  const summaryRequestIdRef = useRef(0);

  const [selectedProductCode, setSelectedProductCode] = useState<string | null>(null);
  const [history, setHistory] = useState<AdminInventoryMovement[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);

  const listRequestIdRef = useRef(0);
  const historyRequestIdRef = useRef(0);
  const actionInFlightRef = useRef(false);

  const isActiveValue = activeFilter === "all" ? undefined : activeFilter === "active";

  const fetchPage = useCallback(
    async (targetPage: number): Promise<boolean> => {
      const requestId = ++listRequestIdRef.current;
      setLoading(true);
      setError(null);
      try {
        const result = await listAdminInventoryPrices({
          query: query.trim() || undefined,
          brandCode: brandCodeFilter ?? undefined,
          categoryCode: categoryCodeFilter ?? undefined,
          isActive: isActiveValue,
          salesStatus: salesStatusFilter || undefined,
          stockStatus: stockStatusFilter || undefined,
          page: targetPage,
          pageSize
        });
        if (requestId !== listRequestIdRef.current) return false;
        setItems(result.items);
        setPagination(result.pagination);
        return true;
      } catch (caughtError: unknown) {
        if (requestId !== listRequestIdRef.current) return false;
        setError(describeApiError(caughtError, "재고·가격 목록을 불러오지 못했습니다."));
        setItems([]);
        setPagination(null);
        return false;
      } finally {
        if (requestId === listRequestIdRef.current) setLoading(false);
      }
    },
    [query, brandCodeFilter, categoryCodeFilter, isActiveValue, salesStatusFilter, stockStatusFilter, pageSize]
  );

  useEffect(() => {
    if (!enabled) return;
    void Promise.resolve().then(() => fetchPage(page));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    enabled,
    query,
    brandCodeFilter,
    categoryCodeFilter,
    activeFilter,
    salesStatusFilter,
    stockStatusFilter,
    pageSize,
    page
  ]);

  // 운영 현황 요약 카드(품절임박/판매 시작 전/재고 정보 없음)는 판매·재고 상태 드롭다운과는
  // 무관하게 항상 전체 집계를 보여준다 — 그 두 필터가 바로 이 요약이 나누는 축이라, 반영하면
  // 필터링할수록 나머지 카드가 0에 가까워져 상시 운영 현황판 역할을 못 하기 때문이다.
  const fetchSummary = useCallback(async (): Promise<void> => {
    const requestId = ++summaryRequestIdRef.current;
    try {
      const result = await getAdminInventorySummary({
        query: query.trim() || undefined,
        brandCode: brandCodeFilter ?? undefined,
        categoryCode: categoryCodeFilter ?? undefined,
        isActive: isActiveValue
      });
      if (requestId !== summaryRequestIdRef.current) return;
      setSummary(result);
    } catch {
      if (requestId !== summaryRequestIdRef.current) return;
      setSummary(null);
    }
  }, [query, brandCodeFilter, categoryCodeFilter, isActiveValue]);

  useEffect(() => {
    if (!enabled) return;
    void Promise.resolve().then(() => fetchSummary());
  }, [enabled, fetchSummary]);

  // 카테고리·브랜드 옵션은 필터 변경과 무관하게 한 번만 불러온다.
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void Promise.all([getAdminProductBrands(), getAdminProductCategories()]).then(
      ([brandOptions, categoryOptions]) => {
        if (cancelled) return;
        setBrands(brandOptions);
        setCategories(categoryOptions);
      },
      () => {
        // 옵션 로드 실패는 필터를 "전체"로 비워두는 정도로 충분하며 목록 조회 자체를 막지 않는다.
      }
    );
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  const applySearch = useCallback((value: string) => {
    setQuery(value);
    setPage(1);
  }, []);

  const setBrandCodeFilter = useCallback((value: string | null) => {
    setBrandCodeFilterState(value);
    setPage(1);
  }, []);

  const setCategoryCodeFilter = useCallback((value: string | null) => {
    setCategoryCodeFilterState(value);
    setPage(1);
  }, []);

  const setActiveFilter = useCallback((value: AdminInventoryActiveFilter) => {
    setActiveFilterState(value);
    setPage(1);
  }, []);

  const setSalesStatusFilter = useCallback((value: AdminInventorySalesStatusFilter) => {
    setSalesStatusFilterState(value);
    setPage(1);
  }, []);

  const setStockStatusFilter = useCallback((value: AdminInventoryStockStatusFilter) => {
    setStockStatusFilterState(value);
    setPage(1);
  }, []);

  const changePageSize = useCallback((value: number) => {
    setPageSize(value);
    setPage(1);
  }, []);

  const resetFilters = useCallback(() => {
    setQuery("");
    setBrandCodeFilterState(null);
    setCategoryCodeFilterState(null);
    setActiveFilterState("all");
    setSalesStatusFilterState("");
    setStockStatusFilterState("");
    setPage(1);
  }, []);

  const refresh = useCallback((): Promise<boolean> => {
    if (!enabled) return Promise.resolve(false);
    void fetchSummary();
    return fetchPage(page);
  }, [enabled, fetchPage, page, fetchSummary]);

  const goToPage = useCallback((targetPage: number) => {
    if (targetPage < 1) return;
    setPage(targetPage);
  }, []);

  const selectedItem = items.find((item) => item.productCode === selectedProductCode) ?? null;

  const loadHistory = useCallback(async (productCode: string) => {
    const requestId = ++historyRequestIdRef.current;
    setLoadingHistory(true);
    setHistoryError(null);
    try {
      const nextHistory = await getAdminInventoryHistory(productCode);
      if (requestId !== historyRequestIdRef.current) return;
      setHistory(nextHistory);
    } catch (caughtError: unknown) {
      if (requestId !== historyRequestIdRef.current) return;
      setHistory([]);
      setHistoryError(describeApiError(caughtError, "재고 이력을 불러오지 못했습니다."));
    } finally {
      if (requestId === historyRequestIdRef.current) setLoadingHistory(false);
    }
  }, []);

  useEffect(() => {
    void Promise.resolve().then(() => {
      if (!selectedProductCode) {
        setHistory([]);
        setHistoryError(null);
        return;
      }
      return loadHistory(selectedProductCode);
    });
  }, [loadHistory, selectedProductCode]);

  const runAction = useCallback(
    async <T>(
      action: Exclude<PendingAction, null>,
      request: () => Promise<T>,
      successMessage: (result: T) => string
    ): Promise<{ result: T | null; message: string | null }> => {
      if (actionInFlightRef.current) return { result: null, message: null };

      actionInFlightRef.current = true;
      setPendingAction(action);
      setActionError(null);
      try {
        const result = await request();
        await fetchPage(page);
        void fetchSummary();
        if (selectedProductCode) await loadHistory(selectedProductCode);
        return { result, message: successMessage(result) };
      } catch (caughtError: unknown) {
        const message = describeApiError(
          caughtError,
          "요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."
        );
        setActionError(message);
        return { result: null, message };
      } finally {
        actionInFlightRef.current = false;
        setPendingAction(null);
      }
    },
    [fetchPage, page, fetchSummary, loadHistory, selectedProductCode]
  );

  const adjustStock = useCallback(
    (productCode: string, stockQuantity: number, reason: string) =>
      runAction(
        "stock",
        () => adjustAdminInventoryStock(productCode, stockQuantity, reason),
        (result) =>
          result.changed ? "재고를 저장했습니다." : "현재 재고와 같아 변경하지 않았습니다."
      ),
    [runAction]
  );

  const updatePrice = useCallback(
    (productCode: string, price: number) =>
      runAction(
        "price",
        () => updateAdminInventoryPrice(productCode, price),
        (result) =>
          result.changed ? "가격을 저장했습니다." : "현재 가격과 같아 변경하지 않았습니다."
      ),
    [runAction]
  );

  const startSale = useCallback(
    (productCode: string) =>
      runAction(
        "sale",
        () => startAdminProductSale(productCode),
        () => "판매를 시작했습니다."
      ),
    [runAction]
  );

  const hideProduct = useCallback(
    (productCode: string) =>
      runAction(
        "hide",
        () => updateAdminProduct(productCode, { isActive: false }),
        () => "상품을 숨김 처리했습니다."
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
    query,
    brandCodeFilter,
    categoryCodeFilter,
    activeFilter,
    salesStatusFilter,
    stockStatusFilter,
    brands,
    categories,
    summary,
    applySearch,
    setBrandCodeFilter,
    setCategoryCodeFilter,
    setActiveFilter,
    setSalesStatusFilter,
    setStockStatusFilter,
    setPageSize: changePageSize,
    resetFilters,
    refresh,
    goToPage,
    selectedItem,
    selectedProductCode,
    setSelectedProductCode,
    history,
    loadingHistory,
    historyError,
    actionError,
    pendingAction,
    adjustStock,
    updatePrice,
    startSale,
    hideProduct
  };
}
