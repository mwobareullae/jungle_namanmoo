import { useCallback, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  AdminBulkImportResult,
  AdminBulkImportRowInput,
  importAdminProducts
} from "../api/adminBulkImportApi";

const BULK_IMPORT_NETWORK_ERROR_MESSAGE =
  "응답 확인 중 문제가 발생했습니다. 일부 상품은 이미 등록됐을 수 있으니 재고/가격 화면에서 import_sku 또는 상품명을 먼저 확인해 주세요.";

const isNetworkFetchError = (caughtError: unknown): boolean => {
  if (typeof caughtError !== "object" || caughtError === null || !("message" in caughtError))
    return false;

  const message = (caughtError as { message?: unknown }).message;
  return (
    typeof message === "string" &&
    (message === "Failed to fetch" || message.toLowerCase().includes("fetch"))
  );
};

const describeApiError = (caughtError: unknown, fallbackMessage: string): string => {
  if (isNetworkFetchError(caughtError)) return BULK_IMPORT_NETWORK_ERROR_MESSAGE;

  const apiError = caughtError as Partial<ApiError> | undefined;
  if (apiError?.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
  if (apiError?.status === 403) return "관리자 권한이 필요합니다.";
  return apiError?.message ?? fallbackMessage;
};

export function useAdminBulkImport() {
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<AdminBulkImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlightRef = useRef(false);
  const requestIdRef = useRef(0);

  const reset = useCallback(() => {
    requestIdRef.current += 1;
    setResult(null);
    setError(null);
  }, []);

  const submit = useCallback(
    async (rows: AdminBulkImportRowInput[]): Promise<AdminBulkImportResult | null> => {
      if (inFlightRef.current) return null;

      const requestId = ++requestIdRef.current;
      inFlightRef.current = true;
      setSubmitting(true);
      setError(null);
      try {
        const nextResult = await importAdminProducts(rows);
        if (requestId !== requestIdRef.current) return null;
        setResult(nextResult);
        return nextResult;
      } catch (caughtError: unknown) {
        if (requestId !== requestIdRef.current) return null;
        setError(
          describeApiError(
            caughtError,
            "상품 대량등록 결과를 확인하지 못했습니다. 재고/가격 화면에서 등록 여부를 먼저 확인해 주세요."
          )
        );
        return null;
      } finally {
        inFlightRef.current = false;
        if (requestId === requestIdRef.current) setSubmitting(false);
      }
    },
    []
  );

  return {
    submitting,
    result,
    error,
    reset,
    submit
  };
}
