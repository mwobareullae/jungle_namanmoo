import { useCallback, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  AdminBulkImportResult,
  AdminBulkImportRowInput,
  importAdminProducts,
} from "../api/adminBulkImportApi";

const describeApiError = (caughtError: unknown, fallbackMessage: string): string => {
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

  const submit = useCallback(async (rows: AdminBulkImportRowInput[]): Promise<AdminBulkImportResult | null> => {
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
      setError(describeApiError(caughtError, "상품 대량등록을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."));
      return null;
    } finally {
      inFlightRef.current = false;
      if (requestId === requestIdRef.current) setSubmitting(false);
    }
  }, []);

  return {
    submitting,
    result,
    error,
    reset,
    submit,
  };
}
