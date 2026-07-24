import { useCallback, useEffect, useRef, useState } from "react";

export function useActivityToast(duration = 2500) {
  const [message, setMessage] = useState("");
  const timerRef = useRef<number | null>(null);

  const showToast = useCallback((nextMessage: string) => {
    setMessage(nextMessage);
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      setMessage("");
      timerRef.current = null;
    }, duration);
  }, [duration]);

  const clearToast = useCallback(() => {
    setMessage("");
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
  }, []);

  return { message, showToast, clearToast };
}

export const wishlistToastMessage = {
  added: "찜한 상품에 추가했습니다.",
  removed: "찜한 상품에서 해제했습니다.",
  failed: "찜 처리에 실패했습니다. 잠시 후 다시 시도해 주세요."
} as const;
