import { useCallback, useEffect, useRef, useState } from "react";

import ConfirmModal from "../../../components/ui/ConfirmModal";
import type { ApiError } from "../../../types/recommendation";
import {
  AdminCancelRequestAction,
  AdminCancelRequestStatus,
  CANCEL_REQUEST_STATUS_LABELS,
  getAdminCancelRequestDetail,
  AdminCancelRequestDetail
} from "../api/adminOrderCancelRequestApi";
import {
  AdminClaimAction,
  AdminClaimStatus,
  AdminClaimType,
  CLAIM_STATUS_LABELS,
  CLAIM_TYPE_LABELS,
  getAdminClaimDetail,
  AdminClaimDetail
} from "../api/adminOrderClaimApi";
import { useAdminCancelRequests } from "./useAdminCancelRequests";
import { useAdminClaims } from "./useAdminClaims";

// 401/403 은 최초 진입 게이트(useAdminAccess)뿐 아니라 진입 후 세션 만료·권한 변경으로도
// 발생할 수 있으므로, 목록·상세 요청 각각의 오류 메시지에서도 구분해 안내한다.
const describeApiError = (caughtError: unknown, fallbackMessage: string): string => {
  const apiError = caughtError as Partial<ApiError> | undefined;
  if (apiError?.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
  if (apiError?.status === 403) return "관리자 권한이 필요합니다.";
  return apiError?.message ?? fallbackMessage;
};

// 관리자 취소·클레임 관리 화면 (M1.5-B).
// 취소 요청/클레임 탭으로 나뉘고, Order.status 와 무관하게 각자 독립적으로 조회한다
// (클레임 진행 상황은 Order.status 에 동기화되지 않기로 확정했으므로 주문 화면과는 분리된 화면).
// 승인·거절·처리시작·완료 버튼은 서버가 계산한 available_actions 기준으로만 표시한다.

type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";
type CancelClaimTab = "cancelRequests" | "claims";

type AdminCancelClaimSectionProps = {
  active: boolean;
  onOperationLog: (area: string, title: string, detail: string, tone?: BadgeTone) => void;
};

const CANCEL_REQUEST_STATUS_TONE: Record<AdminCancelRequestStatus, BadgeTone> = {
  REQUESTED: "review",
  APPROVED: "success",
  REJECTED: "danger"
};

const CLAIM_STATUS_TONE: Record<AdminClaimStatus, BadgeTone> = {
  REQUESTED: "review",
  APPROVED: "success",
  REJECTED: "danger",
  IN_PROGRESS: "warning",
  COMPLETED: "success",
  WITHDRAWN: "neutral"
};

const CANCEL_ACTION_LABELS: Record<AdminCancelRequestAction, string> = {
  APPROVE: "승인",
  REJECT: "거절"
};

const CLAIM_ACTION_LABELS: Record<AdminClaimAction, string> = {
  APPROVE: "승인",
  REJECT: "거절",
  START: "처리 시작",
  COMPLETE: "완료 처리"
};

function formatCurrency(value: number) {
  return `${value.toLocaleString("ko-KR")}원`;
}

export function AdminCancelClaimSection({ active, onOperationLog }: AdminCancelClaimSectionProps) {
  const [tab, setTab] = useState<CancelClaimTab>("cancelRequests");

  return (
    <section className="admin-order-layout" hidden={!active}>
      <section className="admin-panel admin-order-hero">
        <div className="admin-panel-header admin-product-header">
          <div>
            <p>취소·클레임 관리</p>
            <h2>취소 요청과 반품·교환·환불 클레임을 조회하고 처리</h2>
          </div>
          <div className="admin-filter-row">
            <button
              className={tab === "cancelRequests" ? "admin-primary-button" : "admin-secondary-button"}
              onClick={() => setTab("cancelRequests")}
              type="button"
            >
              취소 요청
            </button>
            <button
              className={tab === "claims" ? "admin-primary-button" : "admin-secondary-button"}
              onClick={() => setTab("claims")}
              type="button"
            >
              반품·교환·환불
            </button>
          </div>
        </div>
      </section>
      {tab === "cancelRequests" ? (
        <CancelRequestsTab active={active} onOperationLog={onOperationLog} />
      ) : (
        <ClaimsTab active={active} onOperationLog={onOperationLog} />
      )}
    </section>
  );
}

function CancelRequestsTab({
  active,
  onOperationLog
}: {
  active: boolean;
  onOperationLog: AdminCancelClaimSectionProps["onOperationLog"];
}) {
  const {
    items,
    hasMore,
    loading,
    loadingMore,
    error,
    statusFilter,
    setStatusFilter,
    resetFilters,
    refresh,
    loadMore,
    actionRequestCode,
    actionError,
    syncWarning,
    runCancelRequestAction,
    clearActionError
  } = useAdminCancelRequests({ enabled: active });
  const [selectedRequestCode, setSelectedRequestCode] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminCancelRequestDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const detailRequestIdRef = useRef(0);
  const [rejectReason, setRejectReason] = useState("");
  const [pendingAction, setPendingAction] = useState<{
    action: AdminCancelRequestAction;
    requestCode: string;
    orderCode: string;
    rejectionReason?: string;
  } | null>(null);

  const selectedRow = items.find((item) => item.requestCode === selectedRequestCode) ?? null;

  const loadDetail = useCallback(async (requestCode: string) => {
    const requestId = ++detailRequestIdRef.current;
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const result = await getAdminCancelRequestDetail(requestCode);
      if (requestId !== detailRequestIdRef.current) return; // 이후 다른 행 선택이 이미 진행 중 — 이 응답은 버림
      setDetail(result);
    } catch (caughtError: unknown) {
      if (requestId !== detailRequestIdRef.current) return;
      setDetailError(describeApiError(caughtError, "취소 요청 상세를 불러오지 못했습니다."));
    } finally {
      if (requestId === detailRequestIdRef.current) {
        setDetailLoading(false);
      }
    }
  }, []);

  const selectRow = (requestCode: string) => {
    setSelectedRequestCode(requestCode);
    setRejectReason("");
    clearActionError();
    void loadDetail(requestCode);
  };

  // 목록이 갱신될 때마다(최초 조회·필터 변경·새로고침) 현재 선택된 행의 상세도 함께 재조회한다.
  // 선택 코드가 새 목록에 없으면(필터링으로 사라짐 포함) 첫 행으로 다시 맞추고, 있으면 같은 코드로
  // 그대로 재조회한다 — 그렇지 않으면 새로고침으로 목록의 상태는 바뀌었는데 상세 패널은 이전 값을
  // 계속 보여주는 불일치가 생긴다.
  useEffect(() => {
    void Promise.resolve().then(() => {
      if (items.length === 0) {
        if (selectedRequestCode !== null) {
          detailRequestIdRef.current += 1;
          setSelectedRequestCode(null);
          setDetail(null);
          setDetailError(null);
        }
        return;
      }
      const stillPresent = items.some((item) => item.requestCode === selectedRequestCode);
      const targetCode = stillPresent ? (selectedRequestCode as string) : items[0].requestCode;
      if (!stillPresent) {
        setSelectedRequestCode(targetCode);
      }
      void loadDetail(targetCode);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  const handleRefresh = async () => {
    const succeeded = await refresh();
    if (succeeded) clearActionError();
    onOperationLog(
      "취소 요청",
      succeeded ? "목록 새로고침" : "새로고침 실패",
      succeeded ? "취소 요청 목록을 다시 불러왔습니다." : "잠시 후 다시 시도해 주세요.",
      succeeded ? "success" : "danger"
    );
  };

  // 승인·거절 버튼 클릭: 바로 실행하지 않고 ConfirmModal 로 먼저 확인받는다.
  // 클릭 시점의 요청번호를 그대로 캡처해두므로, 확인 대기 중 다른 행을 선택해도
  // 실제 실행은 항상 처음 누른 그 요청에만 적용된다.
  const handleActionButtonClick = (action: AdminCancelRequestAction, requestCode: string, orderCode: string) => {
    if (actionRequestCode !== null) return;
    clearActionError();
    setPendingAction({
      action,
      requestCode,
      orderCode,
      rejectionReason: action === "REJECT" ? rejectReason.trim() : undefined
    });
  };

  const executeAction = async () => {
    if (!pendingAction || actionRequestCode !== null) return;
    const { action, requestCode, orderCode, rejectionReason } = pendingAction;
    const succeeded = await runCancelRequestAction(requestCode, action, rejectionReason);
    setPendingAction(null);
    if (!succeeded) {
      onOperationLog(
        "취소 요청",
        action === "APPROVE" ? "승인 실패" : "거절 실패",
        "잠시 후 다시 시도해 주세요.",
        "danger"
      );
      return;
    }
    if (action === "REJECT") setRejectReason("");
    if (selectedRequestCode === requestCode) void loadDetail(requestCode);
    onOperationLog(
      "취소 요청",
      action === "APPROVE" ? "취소 승인" : "취소 거절",
      orderCode,
      action === "APPROVE" ? "success" : "danger"
    );
  };

  const actionInProgress = actionRequestCode !== null;

  return (
    <>
      <section className="admin-panel admin-order-table-panel">
        <div className="admin-panel-header compact">
          <div>
            <p>취소 요청 목록</p>
            <h2>결제완료 주문의 취소 신청 현황</h2>
          </div>
          <div className="admin-filter-row">
            <select
              aria-label="취소 요청 상태 필터"
              disabled={actionInProgress}
              onChange={(event) =>
                setStatusFilter(event.target.value === "" ? null : (event.target.value as AdminCancelRequestStatus))
              }
              value={statusFilter ?? ""}
            >
              <option value="">전체</option>
              {(Object.keys(CANCEL_REQUEST_STATUS_LABELS) as AdminCancelRequestStatus[]).map((status) => (
                <option key={status} value={status}>
                  {CANCEL_REQUEST_STATUS_LABELS[status]}
                </option>
              ))}
            </select>
            <button className="admin-secondary-button" disabled={actionInProgress} onClick={resetFilters} type="button">
              초기화
            </button>
            <button
              className="admin-primary-button"
              disabled={loading || actionInProgress}
              onClick={handleRefresh}
              type="button"
            >
              새로고침
            </button>
          </div>
        </div>
        {error && (
          <div className="admin-state-banner danger">
            <strong>취소 요청 목록을 불러오지 못했습니다</strong>
            <span>{error}</span>
          </div>
        )}
        <div className="admin-table-wrap">
          <table className="admin-table admin-order-table">
            <thead>
              <tr>
                <th scope="col">요청번호</th>
                <th scope="col">주문</th>
                <th scope="col">고객</th>
                <th scope="col">상태</th>
                <th scope="col">신청일시</th>
                <th scope="col">가능 액션</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr
                  className={selectedRow && row.requestCode === selectedRow.requestCode ? "selected" : undefined}
                  key={row.requestCode}
                  onClick={() => selectRow(row.requestCode)}
                >
                  <td className="admin-file-name">{row.requestCode}</td>
                  <td>{row.orderCode}</td>
                  <td>{row.customerDisplay}</td>
                  <td>
                    <span className={`admin-badge ${CANCEL_REQUEST_STATUS_TONE[row.status]}`}>{row.statusLabel}</span>
                  </td>
                  <td>{row.requestedAt}</td>
                  <td>
                    {row.availableActions.length === 0
                      ? "-"
                      : row.availableActions.map((action) => CANCEL_ACTION_LABELS[action]).join(", ")}
                  </td>
                </tr>
              ))}
              {loading && items.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={6}>
                    취소 요청을 불러오는 중입니다...
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={6}>
                    {error ? "취소 요청 목록을 불러오지 못했습니다." : "조건에 맞는 취소 요청이 없습니다."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {hasMore && (
          <button
            className="admin-secondary-button"
            disabled={loadingMore || actionInProgress}
            onClick={loadMore}
            type="button"
          >
            {loadingMore ? "불러오는 중..." : "더 보기"}
          </button>
        )}
      </section>

      <aside className="admin-panel admin-order-detail">
        <div className="admin-panel-header compact">
          <div>
            <p>선택 취소 요청</p>
            <h2>{selectedRow ? selectedRow.requestCode : "선택된 요청 없음"}</h2>
          </div>
          {selectedRow && (
            <span className={`admin-badge ${CANCEL_REQUEST_STATUS_TONE[selectedRow.status]}`}>
              {selectedRow.statusLabel}
            </span>
          )}
        </div>
        {!selectedRow ? (
          <div className="admin-state-banner neutral">
            <strong>선택된 요청 없음</strong>
            <span>표에서 취소 요청을 선택하면 상세 정보가 표시됩니다.</span>
          </div>
        ) : detailLoading ? (
          <div className="admin-state-banner neutral">
            <strong>상세 정보를 불러오는 중입니다</strong>
          </div>
        ) : detailError ? (
          <div className="admin-state-banner danger">
            <strong>상세 정보를 불러오지 못했습니다</strong>
            <span>{detailError}</span>
          </div>
        ) : detail ? (
          <dl className="admin-metric-list">
            <div>
              <dt>주문번호</dt>
              <dd>{detail.orderCode}</dd>
            </div>
            <div>
              <dt>고객</dt>
              <dd>{detail.customerDisplay}</dd>
            </div>
            <div>
              <dt>주문 상태</dt>
              <dd>{detail.orderStatus}</dd>
            </div>
            <div>
              <dt>결제 상태</dt>
              <dd>{detail.paymentStatus ?? "결제정보 없음"}</dd>
            </div>
            <div>
              <dt>결제 수단</dt>
              <dd>{detail.paymentProvider ?? "-"}</dd>
            </div>
            <div>
              <dt>상품</dt>
              <dd>{detail.productSummary}</dd>
            </div>
            <div>
              <dt>금액</dt>
              <dd>{formatCurrency(detail.totalAmount)}</dd>
            </div>
            <div>
              <dt>취소 사유</dt>
              <dd>{detail.reasonCode ?? "-"}</dd>
            </div>
            <div>
              <dt>고객 상세 사유</dt>
              <dd>{detail.reasonDetail ?? "-"}</dd>
            </div>
            <div>
              <dt>관리자 처리 사유</dt>
              <dd>{detail.decisionReason ?? "-"}</dd>
            </div>
            <div>
              <dt>신청일시</dt>
              <dd>{detail.requestedAt}</dd>
            </div>
            <div>
              <dt>처리일시</dt>
              <dd>{detail.processedAt ?? "미처리"}</dd>
            </div>
            <div>
              <dt>가능한 액션</dt>
              <dd>
                {detail.availableActions.length === 0
                  ? "없음"
                  : detail.availableActions.map((action) => CANCEL_ACTION_LABELS[action]).join(", ")}
              </dd>
            </div>
          </dl>
        ) : null}
        {actionError && (
          <div className="admin-state-banner danger">
            <strong>처리 실패</strong>
            <span>{actionError}</span>
          </div>
        )}
        {syncWarning && (
          <div className="admin-state-banner warning">
            <strong>목록 동기화 필요</strong>
            <span>{syncWarning}</span>
          </div>
        )}
        {/* 승인·거절 버튼은 서버가 계산한 available_actions 기준으로만 표시한다 — 프론트는 직접 계산하지 않는다 */}
        {detail && detail.availableActions.length > 0 && (
          <div className="admin-order-action-grid" aria-label="취소 요청 운영 액션">
            {detail.availableActions.includes("REJECT") && (
              <textarea
                aria-label="거절 사유"
                className="admin-cancel-rejection-reason"
                disabled={actionInProgress}
                onChange={(event) => setRejectReason(event.target.value)}
                placeholder="거절 사유를 입력하세요 (필수)"
                rows={2}
                value={rejectReason}
              />
            )}
            {detail.availableActions.includes("APPROVE") && (
              <button
                className="admin-primary-button"
                disabled={actionInProgress}
                onClick={() => handleActionButtonClick("APPROVE", detail.requestCode, detail.orderCode)}
                type="button"
              >
                {actionInProgress && actionRequestCode === detail.requestCode ? "처리 중..." : "승인"}
              </button>
            )}
            {detail.availableActions.includes("REJECT") && (
              <button
                className="admin-secondary-button"
                disabled={actionInProgress || rejectReason.trim().length === 0}
                onClick={() => handleActionButtonClick("REJECT", detail.requestCode, detail.orderCode)}
                type="button"
              >
                {actionInProgress && actionRequestCode === detail.requestCode ? "처리 중..." : "거절"}
              </button>
            )}
          </div>
        )}
      </aside>
      <ConfirmModal
        cancelLabel="취소"
        confirmLabel={actionInProgress ? "처리 중..." : "확인"}
        message={
          pendingAction
            ? pendingAction.action === "APPROVE"
              ? `${pendingAction.orderCode} 취소 요청을 승인할까요? 승인하면 주문이 취소되고 결제가 취소 처리되며, 되돌릴 수 없습니다.`
              : `${pendingAction.orderCode} 취소 요청을 거절할까요? 주문은 결제완료 상태로 복구되며, 되돌릴 수 없습니다.`
            : ""
        }
        onCancel={() => {
          if (actionInProgress) return;
          setPendingAction(null);
        }}
        onConfirm={() => void executeAction()}
        open={pendingAction !== null}
        title="취소 요청 처리 확인"
      />
    </>
  );
}

function ClaimsTab({
  active,
  onOperationLog
}: {
  active: boolean;
  onOperationLog: AdminCancelClaimSectionProps["onOperationLog"];
}) {
  const {
    items,
    page,
    totalPages,
    totalCount,
    loading,
    error,
    statusFilter,
    claimTypeFilter,
    setStatusFilter,
    setClaimTypeFilter,
    resetFilters,
    refresh,
    goToPage,
    actionClaimCode,
    actionError,
    syncWarning,
    runClaimAction,
    clearActionError
  } = useAdminClaims({ enabled: active });
  const [selectedClaimCode, setSelectedClaimCode] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminClaimDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const detailRequestIdRef = useRef(0);
  const [rejectReason, setRejectReason] = useState("");
  const [restockOnComplete, setRestockOnComplete] = useState(false);
  const [pendingAction, setPendingAction] = useState<{
    action: AdminClaimAction;
    claimCode: string;
    orderCode: string;
    claimType: AdminClaimType;
    rejectionReason?: string;
    restock?: boolean;
  } | null>(null);

  const selectedRow = items.find((item) => item.claimCode === selectedClaimCode) ?? null;

  const loadDetail = useCallback(async (claimCode: string) => {
    const requestId = ++detailRequestIdRef.current;
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const result = await getAdminClaimDetail(claimCode);
      if (requestId !== detailRequestIdRef.current) return; // 이후 다른 행 선택이 이미 진행 중 — 이 응답은 버림
      setDetail(result);
    } catch (caughtError: unknown) {
      if (requestId !== detailRequestIdRef.current) return;
      setDetailError(describeApiError(caughtError, "클레임 상세를 불러오지 못했습니다."));
    } finally {
      if (requestId === detailRequestIdRef.current) {
        setDetailLoading(false);
      }
    }
  }, []);

  const selectRow = (claimCode: string) => {
    setSelectedClaimCode(claimCode);
    setRejectReason("");
    setRestockOnComplete(false);
    clearActionError();
    void loadDetail(claimCode);
  };

  // 목록이 갱신될 때마다(최초 조회·필터 변경·새로고침) 현재 선택된 클레임의 상세도 함께 재조회한다.
  // 선택 코드가 새 목록에 없으면 첫 행으로 다시 맞추고, 있으면 같은 코드로 그대로 재조회한다 —
  // 그렇지 않으면 새로고침으로 목록의 상태는 바뀌었는데 상세 패널은 이전 값을 계속 보여주게 된다.
  useEffect(() => {
    void Promise.resolve().then(() => {
      if (items.length === 0) {
        if (selectedClaimCode !== null) {
          detailRequestIdRef.current += 1;
          setSelectedClaimCode(null);
          setDetail(null);
          setDetailError(null);
        }
        return;
      }
      const stillPresent = items.some((item) => item.claimCode === selectedClaimCode);
      const targetCode = stillPresent ? (selectedClaimCode as string) : items[0].claimCode;
      if (!stillPresent) {
        setSelectedClaimCode(targetCode);
      }
      void loadDetail(targetCode);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  const handleRefresh = async () => {
    const succeeded = await refresh();
    if (succeeded) clearActionError();
    onOperationLog(
      "클레임",
      succeeded ? "목록 새로고침" : "새로고침 실패",
      succeeded ? "클레임 목록을 다시 불러왔습니다." : "잠시 후 다시 시도해 주세요.",
      succeeded ? "success" : "danger"
    );
  };

  // 승인·거절·처리시작·완료 버튼 클릭: 바로 실행하지 않고 ConfirmModal 로 먼저 확인받는다.
  // 클릭 시점의 클레임번호를 그대로 캡처해두므로, 확인 대기 중 다른 행을 선택해도
  // 실제 실행은 항상 처음 누른 그 클레임에만 적용된다.
  const handleActionButtonClick = (
    action: AdminClaimAction,
    claimCode: string,
    orderCode: string,
    claimType: AdminClaimType
  ) => {
    if (actionClaimCode !== null) return;
    clearActionError();
    setPendingAction({
      action,
      claimCode,
      orderCode,
      claimType,
      rejectionReason: action === "REJECT" ? rejectReason.trim() : undefined,
      restock: action === "COMPLETE" ? (claimType === "RETURN" ? restockOnComplete : false) : undefined
    });
  };

  const executeAction = async () => {
    if (!pendingAction || actionClaimCode !== null) return;
    const { action, claimCode, orderCode, rejectionReason, restock } = pendingAction;
    const succeeded = await runClaimAction(claimCode, action, { rejectionReason, restock: restock ?? false });
    setPendingAction(null);
    if (!succeeded) {
      onOperationLog("클레임", `${CLAIM_ACTION_LABELS[action]} 실패`, "잠시 후 다시 시도해 주세요.", "danger");
      return;
    }
    if (action === "REJECT") setRejectReason("");
    if (action === "COMPLETE") setRestockOnComplete(false);
    if (selectedClaimCode === claimCode) void loadDetail(claimCode);
    onOperationLog(
      "클레임",
      CLAIM_ACTION_LABELS[action],
      orderCode,
      action === "REJECT" ? "danger" : "success"
    );
  };

  const actionInProgress = actionClaimCode !== null;

  return (
    <>
      <section className="admin-panel admin-order-table-panel">
        <div className="admin-panel-header compact">
          <div>
            <p>클레임 목록</p>
            <h2>반품·교환·환불 신청 현황 ({totalCount.toLocaleString("ko-KR")}건)</h2>
          </div>
          <div className="admin-filter-row">
            <select
              aria-label="클레임 상태 필터"
              disabled={actionInProgress}
              onChange={(event) =>
                setStatusFilter(event.target.value === "" ? null : (event.target.value as AdminClaimStatus))
              }
              value={statusFilter ?? ""}
            >
              <option value="">상태 전체</option>
              {(Object.keys(CLAIM_STATUS_LABELS) as AdminClaimStatus[]).map((status) => (
                <option key={status} value={status}>
                  {CLAIM_STATUS_LABELS[status]}
                </option>
              ))}
            </select>
            <select
              aria-label="클레임 유형 필터"
              disabled={actionInProgress}
              onChange={(event) =>
                setClaimTypeFilter(event.target.value === "" ? null : (event.target.value as AdminClaimType))
              }
              value={claimTypeFilter ?? ""}
            >
              <option value="">유형 전체</option>
              {(Object.keys(CLAIM_TYPE_LABELS) as AdminClaimType[]).map((type) => (
                <option key={type} value={type}>
                  {CLAIM_TYPE_LABELS[type]}
                </option>
              ))}
            </select>
            <button className="admin-secondary-button" disabled={actionInProgress} onClick={resetFilters} type="button">
              초기화
            </button>
            <button
              className="admin-primary-button"
              disabled={loading || actionInProgress}
              onClick={handleRefresh}
              type="button"
            >
              새로고침
            </button>
          </div>
        </div>
        {error && (
          <div className="admin-state-banner danger">
            <strong>클레임 목록을 불러오지 못했습니다</strong>
            <span>{error}</span>
          </div>
        )}
        <div className="admin-table-wrap">
          <table className="admin-table admin-order-table">
            <thead>
              <tr>
                <th scope="col">클레임번호</th>
                <th scope="col">주문</th>
                <th scope="col">고객</th>
                <th scope="col">유형</th>
                <th scope="col">상태</th>
                <th scope="col">신청일시</th>
                <th scope="col">가능 액션</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr
                  className={selectedRow && row.claimCode === selectedRow.claimCode ? "selected" : undefined}
                  key={row.claimCode}
                  onClick={() => selectRow(row.claimCode)}
                >
                  <td className="admin-file-name">{row.claimCode}</td>
                  <td>{row.orderCode}</td>
                  <td>{row.customerDisplay}</td>
                  <td>{row.claimTypeLabel}</td>
                  <td>
                    <span className={`admin-badge ${CLAIM_STATUS_TONE[row.status]}`}>{row.statusLabel}</span>
                  </td>
                  <td>{row.requestedAt}</td>
                  <td>
                    {row.availableActions.length === 0
                      ? "-"
                      : row.availableActions.map((action) => CLAIM_ACTION_LABELS[action]).join(", ")}
                  </td>
                </tr>
              ))}
              {loading && items.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={7}>
                    클레임을 불러오는 중입니다...
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={7}>
                    {error ? "클레임 목록을 불러오지 못했습니다." : "조건에 맞는 클레임이 없습니다."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="admin-filter-row">
          <button
            className="admin-secondary-button"
            disabled={page <= 1 || actionInProgress}
            onClick={() => goToPage(page - 1)}
            type="button"
          >
            이전
          </button>
          <span>
            {page} / {totalPages} 페이지
          </span>
          <button
            className="admin-secondary-button"
            disabled={page >= totalPages || actionInProgress}
            onClick={() => goToPage(page + 1)}
            type="button"
          >
            다음
          </button>
        </div>
      </section>

      <aside className="admin-panel admin-order-detail">
        <div className="admin-panel-header compact">
          <div>
            <p>선택 클레임</p>
            <h2>{selectedRow ? selectedRow.claimCode : "선택된 클레임 없음"}</h2>
          </div>
          {selectedRow && (
            <span className={`admin-badge ${CLAIM_STATUS_TONE[selectedRow.status]}`}>{selectedRow.statusLabel}</span>
          )}
        </div>
        {!selectedRow ? (
          <div className="admin-state-banner neutral">
            <strong>선택된 클레임 없음</strong>
            <span>표에서 클레임을 선택하면 상세 정보가 표시됩니다.</span>
          </div>
        ) : detailLoading ? (
          <div className="admin-state-banner neutral">
            <strong>상세 정보를 불러오는 중입니다</strong>
          </div>
        ) : detailError ? (
          <div className="admin-state-banner danger">
            <strong>상세 정보를 불러오지 못했습니다</strong>
            <span>{detailError}</span>
          </div>
        ) : detail ? (
          <>
            <dl className="admin-metric-list">
              <div>
                <dt>주문번호</dt>
                <dd>{detail.orderCode}</dd>
              </div>
              <div>
                <dt>고객</dt>
                <dd>{detail.customerDisplay}</dd>
              </div>
              <div>
                <dt>주문 상태</dt>
                <dd>{detail.orderStatus}</dd>
              </div>
              <div>
                <dt>유형</dt>
                <dd>{detail.claimTypeLabel}</dd>
              </div>
              <div>
                <dt>상품</dt>
                <dd>{detail.productSummary}</dd>
              </div>
              <div>
                <dt>환불 예정액</dt>
                <dd>{detail.refundAmount === null ? "해당 없음" : formatCurrency(detail.refundAmount)}</dd>
              </div>
              <div>
                <dt>신청 사유</dt>
                <dd>{detail.reasonCode}</dd>
              </div>
              <div>
                <dt>고객 상세 사유</dt>
                <dd>{detail.reasonDetail ?? "-"}</dd>
              </div>
              <div>
                <dt>신청일시</dt>
                <dd>{detail.requestedAt}</dd>
              </div>
              <div>
                <dt>처리일시</dt>
                <dd>{detail.processedAt ?? "미처리"}</dd>
              </div>
              <div>
                <dt>완료일시</dt>
                <dd>{detail.completedAt ?? "미완료"}</dd>
              </div>
              <div>
                <dt>가능한 액션</dt>
                <dd>
                  {detail.availableActions.length === 0
                    ? "없음"
                    : detail.availableActions.map((action) => CLAIM_ACTION_LABELS[action]).join(", ")}
                </dd>
              </div>
            </dl>
            <div className="admin-table-wrap">
              <table className="admin-table compact">
                <thead>
                  <tr>
                    <th scope="col">상품</th>
                    <th scope="col">수량</th>
                    <th scope="col">처리 방식</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.items.map((item) => (
                    <tr key={item.orderItemId}>
                      <td>{item.productNameSnapshot}</td>
                      <td>{item.quantity}개</td>
                      <td>{item.resolution === "REFUND" ? "환불" : "교환"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="admin-table-wrap">
              <table className="admin-table compact">
                <thead>
                  <tr>
                    <th scope="col">처리 이력</th>
                    <th scope="col">일시</th>
                    <th scope="col">사유</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.events.map((event, index) => (
                    <tr key={`${event.toStatus}-${index}`}>
                      <td>
                        {(event.fromStatus ? CLAIM_STATUS_LABELS[event.fromStatus] : "신청") +
                          " → " +
                          CLAIM_STATUS_LABELS[event.toStatus]}
                      </td>
                      <td>{event.createdAt}</td>
                      <td>{event.reason ?? "-"}</td>
                    </tr>
                  ))}
                  {detail.events.length === 0 && (
                    <tr>
                      <td className="admin-empty-row" colSpan={3}>
                        처리 이력이 없습니다.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
        {actionError && (
          <div className="admin-state-banner danger">
            <strong>처리 실패</strong>
            <span>{actionError}</span>
          </div>
        )}
        {syncWarning && (
          <div className="admin-state-banner warning">
            <strong>목록 동기화 필요</strong>
            <span>{syncWarning}</span>
          </div>
        )}
        {/* 승인·거절·처리시작·완료 버튼은 서버가 계산한 available_actions 기준으로만 표시한다 — 프론트는 직접 계산하지 않는다 */}
        {detail && detail.availableActions.length > 0 && (
          <div className="admin-order-action-grid" aria-label="클레임 운영 액션">
            {detail.availableActions.includes("APPROVE") && (
              <button
                className="admin-primary-button"
                disabled={actionInProgress}
                onClick={() => handleActionButtonClick("APPROVE", detail.claimCode, detail.orderCode, detail.claimType)}
                type="button"
              >
                {actionInProgress && actionClaimCode === detail.claimCode ? "처리 중..." : "승인"}
              </button>
            )}
            {detail.availableActions.includes("START") && (
              <button
                className="admin-primary-button"
                disabled={actionInProgress}
                onClick={() => handleActionButtonClick("START", detail.claimCode, detail.orderCode, detail.claimType)}
                type="button"
              >
                {actionInProgress && actionClaimCode === detail.claimCode ? "처리 중..." : "처리 시작"}
              </button>
            )}
            {detail.availableActions.includes("COMPLETE") && (
              <>
                {detail.claimType === "RETURN" && (
                  <label>
                    <input
                      checked={restockOnComplete}
                      disabled={actionInProgress}
                      onChange={(event) => setRestockOnComplete(event.target.checked)}
                      type="checkbox"
                    />
                    반품 수령 확인 — 재고 복구
                  </label>
                )}
                <button
                  className="admin-primary-button"
                  disabled={actionInProgress}
                  onClick={() => handleActionButtonClick("COMPLETE", detail.claimCode, detail.orderCode, detail.claimType)}
                  type="button"
                >
                  {actionInProgress && actionClaimCode === detail.claimCode ? "처리 중..." : "완료 처리"}
                </button>
              </>
            )}
            {detail.availableActions.includes("REJECT") && (
              <>
                <textarea
                  aria-label="거절 사유"
                  disabled={actionInProgress}
                  onChange={(event) => setRejectReason(event.target.value)}
                  placeholder="거절 사유를 입력하세요 (필수)"
                  rows={2}
                  value={rejectReason}
                />
                <button
                  className="admin-secondary-button"
                  disabled={actionInProgress || rejectReason.trim().length === 0}
                  onClick={() => handleActionButtonClick("REJECT", detail.claimCode, detail.orderCode, detail.claimType)}
                  type="button"
                >
                  {actionInProgress && actionClaimCode === detail.claimCode ? "처리 중..." : "거절"}
                </button>
              </>
            )}
          </div>
        )}
      </aside>
      <ConfirmModal
        cancelLabel="취소"
        confirmLabel={actionInProgress ? "처리 중..." : "확인"}
        message={
          pendingAction
            ? pendingAction.action === "APPROVE"
              ? `${pendingAction.orderCode} 클레임을 승인할까요? 되돌릴 수 없습니다.`
              : pendingAction.action === "REJECT"
                ? `${pendingAction.orderCode} 클레임을 거절할까요? 되돌릴 수 없습니다.`
                : pendingAction.action === "START"
                  ? `${pendingAction.orderCode} 클레임 처리를 시작할까요? 되돌릴 수 없습니다.`
                  : pendingAction.claimType === "EXCHANGE"
                    ? `${pendingAction.orderCode} 클레임을 완료 처리할까요? 교환 처리로 종료되며, 되돌릴 수 없습니다.`
                    : `${pendingAction.orderCode} 클레임을 완료 처리할까요? 환불이 실행되며${pendingAction.restock ? " (재고 복구 포함)" : ""}, 되돌릴 수 없습니다.`
            : ""
        }
        onCancel={() => {
          if (actionInProgress) return;
          setPendingAction(null);
        }}
        onConfirm={() => void executeAction()}
        open={pendingAction !== null}
        title="클레임 처리 확인"
      />
    </>
  );
}
