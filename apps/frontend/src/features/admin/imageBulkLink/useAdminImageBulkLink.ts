import { useCallback, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  linkAdminProductImages,
  type AdminImageBulkLinkResult,
  type AdminImageBulkLinkRowInput
} from "../api/adminImageBulkLinkApi";

const describeApiError = (caughtError: unknown): string => {
  const apiError = caughtError as Partial<ApiError> | undefined;
  if (apiError?.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
  if (apiError?.status === 403) return "관리자 권한이 필요합니다.";
  if (apiError?.status === 408)
    return "이미지 연결 요청이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.";
  return (
    apiError?.message ??
    "이미지 대량 연결 결과를 확인하지 못했습니다. 등록 여부를 먼저 확인해 주세요."
  );
};

export function useAdminImageBulkLink() {
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<AdminImageBulkLinkResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlightRef = useRef(false);
  const requestIdRef = useRef(0);

  const reset = useCallback(() => {
    requestIdRef.current += 1;
    setResult(null);
    setError(null);
  }, []);

  const submit = useCallback(async (rows: AdminImageBulkLinkRowInput[]) => {
    if (inFlightRef.current) return null;

    const requestId = ++requestIdRef.current;
    inFlightRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const nextResult = await linkAdminProductImages(rows);
      if (requestId !== requestIdRef.current) return null;
      setResult(nextResult);
      return nextResult;
    } catch (caughtError: unknown) {
      if (requestId !== requestIdRef.current) return null;
      setError(describeApiError(caughtError));
      return null;
    } finally {
      inFlightRef.current = false;
      if (requestId === requestIdRef.current) setSubmitting(false);
    }
  }, []);

  return { submitting, result, error, reset, submit };
}
