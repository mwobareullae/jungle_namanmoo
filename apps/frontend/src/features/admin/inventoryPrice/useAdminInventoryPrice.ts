import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  adjustAdminInventoryStock,
  getAdminInventoryHistory,
  listAdminInventoryPrices,
  startAdminProductSale,
  updateAdminInventoryPrice,
  type AdminInventoryFilters,
  type AdminInventoryMovement,
  type AdminInventoryPriceItem
} from "../api/adminInventoryPriceApi";

type PendingAction = "stock" | "price" | "sale" | null;

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

export function useAdminInventoryPrice(filters: AdminInventoryFilters) {
  const [items, setItems] = useState<AdminInventoryPriceItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [selectedProductCode, setSelectedProductCode] = useState<string | null>(null);
  const [history, setHistory] = useState<AdminInventoryMovement[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const listRequestIdRef = useRef(0);
  const historyRequestIdRef = useRef(0);
  const actionInFlightRef = useRef(false);

  const load = useCallback(
    async (options?: { append?: boolean; cursor?: string | null }) => {
      const requestId = ++listRequestIdRef.current;
      setLoading(true);
      setError(null);
      try {
        const result = await listAdminInventoryPrices({
          ...filters,
          cursor: options?.cursor ?? undefined,
          limit: 50
        });
        if (requestId !== listRequestIdRef.current) return false;

        setItems((currentItems) =>
          options?.append ? [...currentItems, ...result.items] : result.items
        );
        setNextCursor(result.nextCursor);
        setSelectedProductCode((currentCode) => {
          if (currentCode && result.items.some((item) => item.productCode === currentCode))
            return currentCode;
          return options?.append ? currentCode : (result.items[0]?.productCode ?? null);
        });
        return true;
      } catch (caughtError: unknown) {
        if (requestId !== listRequestIdRef.current) return false;
        setError(describeApiError(caughtError, "재고·가격 목록을 불러오지 못했습니다."));
        return false;
      } finally {
        if (requestId === listRequestIdRef.current) setLoading(false);
      }
    },
    [filters]
  );

  useEffect(() => {
    void Promise.resolve().then(() => load());
  }, [load]);

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
        await load();
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
    [load, loadHistory, selectedProductCode]
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

  return {
    items,
    nextCursor,
    selectedItem,
    selectedProductCode,
    setSelectedProductCode,
    history,
    loading,
    loadingHistory,
    error,
    historyError,
    actionError,
    pendingAction,
    reload: () => load(),
    loadMore: () =>
      nextCursor ? load({ append: true, cursor: nextCursor }) : Promise.resolve(false),
    adjustStock,
    updatePrice,
    startSale
  };
}
