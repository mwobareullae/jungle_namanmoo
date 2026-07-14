import { useCallback, useRef, useState } from "react";

// 관리자 목록 화면(주문/취소 요청/클레임)이 공통으로 쓰는 "행 액션 실행" 상태 묶음.
// 액션 호출 → 응답으로 해당 행 낙관적 교체 → 백그라운드 재조회(resync) → 실패 시 syncWarning,
// 액션 자체 실패 시 actionError 패턴이 세 화면에 개별 구현돼 있다가 그 중 한 곳(useAdminOrders)
// 에만 있던 "액션 진행 중엔 일반 조회를 막는" 가드가 나머지 두 곳에 복사되지 않아 새로고침과
// 액션이 경합하는 문제로 이어진 적이 있어(2026-07-14) 공통 훅으로 뽑았다.
export type UseAdminRowActionOptions<TRow, TResult> = {
  setItems: (updater: (current: TRow[]) => TRow[]) => void;
  getKey: (row: TRow) => string;
  applyResult: (row: TRow, result: TResult) => TRow;
  // 액션 성공 직후 현재 필터 기준으로 목록을 조용히(silent) 다시 조회한다.
  resync: () => Promise<boolean>;
  resyncFailureMessage: string;
  describeError: (caughtError: unknown, fallbackMessage: string) => string;
};

export function useAdminRowAction<TRow, TResult>(options: UseAdminRowActionOptions<TRow, TResult>) {
  const actionInFlightRef = useRef(false);
  const [actionTargetKey, setActionTargetKey] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [syncWarning, setSyncWarning] = useState<string | null>(null);

  const applyActionResult = useCallback(
    (targetKey: string, result: TResult) => {
      options.setItems((current) =>
        current.map((item) => (options.getKey(item) === targetKey ? options.applyResult(item, result) : item))
      );
    },
    [options]
  );

  const resyncAfterAction = useCallback(async () => {
    const succeeded = await options.resync();
    setSyncWarning(succeeded ? null : options.resyncFailureMessage);
  }, [options]);

  const runAction = useCallback(
    async (targetKey: string, call: () => Promise<TResult>, fallbackMessage: string): Promise<boolean> => {
      if (actionInFlightRef.current) return false;
      actionInFlightRef.current = true;
      setActionTargetKey(targetKey);
      setActionError(null);
      try {
        const result = await call();
        applyActionResult(targetKey, result);
        await resyncAfterAction();
        return true;
      } catch (caughtError: unknown) {
        setActionError(options.describeError(caughtError, fallbackMessage));
        return false;
      } finally {
        actionInFlightRef.current = false;
        setActionTargetKey(null);
      }
    },
    [applyActionResult, resyncAfterAction, options]
  );

  const clearActionError = useCallback(() => setActionError(null), []);
  const clearSyncWarning = useCallback(() => setSyncWarning(null), []);
  const clearFeedback = useCallback(() => {
    setActionError(null);
    setSyncWarning(null);
  }, []);

  return {
    actionInFlightRef,
    actionTargetKey,
    actionError,
    syncWarning,
    runAction,
    clearActionError,
    clearSyncWarning,
    clearFeedback
  };
}
