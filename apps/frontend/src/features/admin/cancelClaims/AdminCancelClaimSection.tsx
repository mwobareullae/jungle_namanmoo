import { useCallback, useRef, useState } from "react";

import ConfirmModal from "../../../components/ui/ConfirmModal";
import InfoModal from "../../../components/ui/InfoModal";
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

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

// 재고/가격 확인·주문 상태 확인과 같은 네이버식 블록 페이지네이션(10개씩 묶어서 이동).
const PAGE_BLOCK_SIZE = 10;

const getBlockPages = (current: number, total: number): number[] => {
  const blockIndex = Math.floor((current - 1) / PAGE_BLOCK_SIZE);
  const start = blockIndex * PAGE_BLOCK_SIZE + 1;
  const end = Math.min(start + PAGE_BLOCK_SIZE - 1, total);
  const pages: number[] = [];
  for (let page = start; page <= end; page += 1) pages.push(page);
  return pages;
};

function formatCurrency(value: number) {
  return `${value.toLocaleString("ko-KR")}원`;
}

function formatCurrentTime() {
  return new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date());
}

type ClaimCompletionFailureRow = {
  id: number;
  time: string;
  claimCode: string;
  orderCode: string;
  claimTypeLabel: string;
};

// 처음/이전/숫자/다음/맨끝 + 페이지당 개수 — 재고/가격 확인·주문 상태 확인과 같은 페이지네이션 UI.
function PaginationRow({
  page,
  totalPages,
  disabled,
  onGoToPage
}: {
  page: number;
  totalPages: number;
  disabled: boolean;
  onGoToPage: (page: number) => void;
}) {
  const blockPages = getBlockPages(page, totalPages);
  const blockStart = blockPages[0] ?? 1;
  const blockEnd = blockPages[blockPages.length - 1] ?? 1;
  const hasPrevBlock = blockStart > 1;
  const hasNextBlock = blockEnd < totalPages;

  return (
    <div className="admin-pagination-row">
      <div className="admin-pagination">
        <button className="admin-pagination-jump" disabled={page <= 1 || disabled} onClick={() => onGoToPage(1)} type="button">
          처음
        </button>
        <button
          className="admin-pagination-jump"
          disabled={!hasPrevBlock || disabled}
          onClick={() => onGoToPage(blockStart - 1)}
          type="button"
        >
          이전
        </button>
        {blockPages.map((entry) => (
          <button
            className={`admin-pagination-page${entry === page ? " active" : ""}`}
            disabled={disabled}
            key={entry}
            onClick={() => onGoToPage(entry)}
            type="button"
          >
            {entry}
          </button>
        ))}
        <button
          className="admin-pagination-jump"
          disabled={!hasNextBlock || disabled}
          onClick={() => onGoToPage(blockEnd + 1)}
          type="button"
        >
          다음
        </button>
        <button
          className="admin-pagination-jump"
          disabled={page >= totalPages || disabled}
          onClick={() => onGoToPage(totalPages)}
          type="button"
        >
          맨끝
        </button>
      </div>
    </div>
  );
}

function PageSizeSelect({
  id,
  value,
  onChange
}: {
  id: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="admin-list-toolbar">
      <div className="admin-page-size">
        <label htmlFor={id}>페이지당</label>
        <select id={id} onChange={(event) => onChange(Number(event.target.value))} value={value}>
          {PAGE_SIZE_OPTIONS.map((size) => (
            <option key={size} value={size}>
              {size}개
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

export function AdminCancelClaimSection({ active }: AdminCancelClaimSectionProps) {
  const [tab, setTab] = useState<CancelClaimTab>("cancelRequests");

  return (
    <section className="admin-order-layout" hidden={!active}>
      <section className="admin-panel admin-order-hero">
        <div className="admin-panel-header admin-product-header">
          <div>
            <p>취소·클레임 관리</p>
            <h2>취소·반품·교환·환불 처리 현황</h2>
          </div>
          <div className="admin-filter-row">
            <button
              className={tab === "cancelRequests" ? "admin-primary-button" : "admin-secondary-button admin-light-button"}
              onClick={() => setTab("cancelRequests")}
              type="button"
            >
              취소 요청
            </button>
            <button
              className={tab === "claims" ? "admin-primary-button" : "admin-secondary-button admin-light-button"}
              onClick={() => setTab("claims")}
              type="button"
            >
              반품·교환·환불
            </button>
          </div>
        </div>
      </section>
      {tab === "cancelRequests" ? <CancelRequestsTab active={active} /> : <ClaimsTab active={active} />}
    </section>
  );
}

function CancelRequestsTab({ active }: { active: boolean }) {
  const {
    items,
    pagination,
    loading,
    error,
    page,
    pageSize,
    statusFilter,
    setStatusFilter,
    setPageSize,
    resetFilters,
    refresh,
    goToPage,
    actionRequestCode,
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
  const totalPages = pagination?.totalPages ?? 1;

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

  // 직접 선택하기 전까지는 아무 요청도 자동으로 보여주지 않는다(재고/가격 확인·주문 상태
  // 확인과 동일한 원칙). 이미 선택한 요청이 있는데 새로고침·필터 변경으로 목록에서 사라지면,
  // 다른 행으로 조용히 바꿔치기하지 않고 "선택한 요청을 찾을 수 없음"으로 안내한다.
  const selectedRequestMissing = selectedRequestCode !== null && selectedRow === null && items.length > 0;

  const handleRefresh = async () => {
    const succeeded = await refresh();
    if (succeeded) clearActionError();
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
    const { action, requestCode, rejectionReason } = pendingAction;
    const succeeded = await runCancelRequestAction(requestCode, action, rejectionReason);
    setPendingAction(null);
    if (!succeeded) return;
    if (action === "REJECT") setRejectReason("");
    if (selectedRequestCode === requestCode) void loadDetail(requestCode);
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
            <button
              className="admin-secondary-button admin-light-button"
              disabled={actionInProgress}
              onClick={resetFilters}
              type="button"
            >
              초기화
            </button>
            <button
              className="admin-secondary-button admin-light-button"
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
        <PageSizeSelect id="admin-cancel-request-page-size" onChange={setPageSize} value={pageSize} />
        <div className="admin-table-wrap admin-order-table-scroll">
          <table className="admin-table admin-cancelrequest-table">
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
                  <td className="admin-file-name" title={row.requestCode}>
                    {row.requestCode}
                  </td>
                  <td className="admin-file-name" title={row.orderCode}>
                    {row.orderCode}
                  </td>
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
        <PaginationRow disabled={actionInProgress || loading} onGoToPage={goToPage} page={page} totalPages={totalPages} />
      </section>

      <aside className="admin-panel admin-order-detail">
        <div className="admin-panel-header compact">
          <div>
            <p>선택 취소 요청</p>
            <h2>{selectedRow ? selectedRow.requestCode : "상세 정보"}</h2>
          </div>
          {selectedRow && (
            <span className={`admin-badge ${CANCEL_REQUEST_STATUS_TONE[selectedRow.status]}`}>
              {selectedRow.statusLabel}
            </span>
          )}
        </div>
        <div className="admin-order-detail-scroll">
          {selectedRequestMissing && (
            <div className="admin-state-banner neutral">
              <strong>선택한 요청을 찾을 수 없음</strong>
              <span>목록이 갱신되며 선택했던 요청이 현재 페이지에 보이지 않습니다. 표에서 다시 선택해 주세요.</span>
            </div>
          )}
          {!selectedRow ? (
            <div className="admin-detail-body">
              <p className="admin-metric-group-title">기본 정보</p>
              <dl className="admin-metric-list">
                <div>
                  <dt>주문번호</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>고객</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>주문 상태</dt>
                  <dd>-</dd>
                </div>
              </dl>

              <p className="admin-metric-group-title">결제 정보</p>
              <dl className="admin-metric-list">
                <div>
                  <dt>결제 상태</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>결제 수단</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>금액</dt>
                  <dd>-</dd>
                </div>
              </dl>

              <p className="admin-metric-group-title">상품 정보</p>
              <dl className="admin-metric-list">
                <div>
                  <dt>상품</dt>
                  <dd>-</dd>
                </div>
              </dl>

              <p className="admin-metric-group-title">취소 정보</p>
              <dl className="admin-metric-list">
                <div>
                  <dt>취소 사유</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>고객 상세 사유</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>관리자 처리 사유</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>신청일시</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>처리일시</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>가능한 액션</dt>
                  <dd>-</dd>
                </div>
              </dl>
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
              <div className="admin-detail-body">
                <p className="admin-metric-group-title">기본 정보</p>
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
                </dl>

                <p className="admin-metric-group-title">결제 정보</p>
                <dl className="admin-metric-list">
                  <div>
                    <dt>결제 상태</dt>
                    <dd>{detail.paymentStatus ?? "결제정보 없음"}</dd>
                  </div>
                  <div>
                    <dt>결제 수단</dt>
                    <dd>{detail.paymentProvider ?? "-"}</dd>
                  </div>
                  <div>
                    <dt>금액</dt>
                    <dd>{formatCurrency(detail.totalAmount)}</dd>
                  </div>
                </dl>

                <p className="admin-metric-group-title">상품 정보</p>
                <dl className="admin-metric-list">
                  <div>
                    <dt>상품</dt>
                    <dd>{detail.productSummary}</dd>
                  </div>
                </dl>

                <p className="admin-metric-group-title">취소 정보</p>
                <dl className="admin-metric-list">
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
              </div>
              {/* 승인·거절 버튼은 서버가 계산한 available_actions 기준으로만 표시한다 — 프론트는 직접 계산하지 않는다 */}
              {detail.availableActions.length > 0 && (
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
            </>
          ) : null}
        </div>
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
      </aside>
    </>
  );
}

function ClaimsTab({ active }: { active: boolean }) {
  const {
    items,
    page,
    pageSize,
    totalPages,
    totalCount,
    loading,
    error,
    statusFilter,
    claimTypeFilter,
    setStatusFilter,
    setClaimTypeFilter,
    setPageSize,
    resetFilters,
    refresh,
    goToPage,
    actionClaimCode,
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
  } | null>(null);
  const [completionFailures, setCompletionFailures] = useState<ClaimCompletionFailureRow[]>([]);
  const nextCompletionFailureIdRef = useRef(0);
  const [historyModalOpen, setHistoryModalOpen] = useState(false);

  const selectedRow = items.find((item) => item.claimCode === selectedClaimCode) ?? null;
  const selectedClaimMissing = selectedClaimCode !== null && selectedRow === null && items.length > 0;
  // 관리자 처리 사유는 별도 필드로 저장되지 않고 거절(REJECTED) 전이 이벤트에만 실려 온다 —
  // 승인·처리시작·완료는 사유를 남기지 않으므로(reject_admin_claim 만 reason 필수) 여기서 찾는다.
  const decisionReason = detail?.events.find((event) => event.toStatus === "REJECTED")?.reason ?? null;

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
    setHistoryModalOpen(false);
    clearActionError();
    void loadDetail(claimCode);
  };

  const handleRefresh = async () => {
    const succeeded = await refresh();
    if (succeeded) clearActionError();
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
    // 재고 복구 여부는 체크박스를 버튼 밖에 미리 놓지 않고, 확인 모달 안에서 그때그때
    // 고르게 한다 — 그래서 클릭 시점엔 초기화만 하고, 실제 값은 executeAction 에서 읽는다.
    if (action === "COMPLETE") setRestockOnComplete(false);
    setPendingAction({
      action,
      claimCode,
      orderCode,
      claimType,
      rejectionReason: action === "REJECT" ? rejectReason.trim() : undefined
    });
  };

  const executeAction = async () => {
    if (!pendingAction || actionClaimCode !== null) return;
    const { action, claimCode, orderCode, claimType, rejectionReason } = pendingAction;
    const restock = action === "COMPLETE" && claimType !== "EXCHANGE" ? restockOnComplete : false;
    const succeeded = await runClaimAction(claimCode, action, { rejectionReason, restock });
    setPendingAction(null);
    if (!succeeded) {
      // 완료 처리(반품/교환/환불 확정) 실패는 환불 실행·재고 복구가 걸린 마지막 단계라 배너·토스트
      // 대신 재고 이력처럼 누적되는 별도 위젯에 남겨 나중에도 놓치지 않게 한다.
      if (action === "COMPLETE") {
        setCompletionFailures((current) => [
          {
            id: ++nextCompletionFailureIdRef.current,
            time: formatCurrentTime(),
            claimCode,
            orderCode,
            claimTypeLabel: CLAIM_TYPE_LABELS[claimType]
          },
          ...current
        ]);
      }
      return;
    }
    if (action === "REJECT") setRejectReason("");
    if (action === "COMPLETE") setRestockOnComplete(false);
    if (selectedClaimCode === claimCode) void loadDetail(claimCode);
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
            <button
              className="admin-secondary-button admin-light-button"
              disabled={actionInProgress}
              onClick={resetFilters}
              type="button"
            >
              초기화
            </button>
            <button
              className="admin-secondary-button admin-light-button"
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
        <PageSizeSelect id="admin-claim-page-size" onChange={setPageSize} value={pageSize} />
        <div className="admin-table-wrap admin-order-table-scroll">
          <table className="admin-table admin-claim-table">
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
                  <td className="admin-file-name" title={row.claimCode}>
                    {row.claimCode}
                  </td>
                  <td className="admin-file-name" title={row.orderCode}>
                    {row.orderCode}
                  </td>
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
        <PaginationRow disabled={actionInProgress || loading} onGoToPage={goToPage} page={page} totalPages={totalPages} />
      </section>

      <aside className="admin-panel admin-order-detail">
        <div className="admin-panel-header compact">
          <div>
            <p>선택 클레임</p>
            <h2>{selectedRow ? selectedRow.claimCode : "상세 정보"}</h2>
          </div>
          {selectedRow && (
            <span className={`admin-badge ${CLAIM_STATUS_TONE[selectedRow.status]}`}>{selectedRow.statusLabel}</span>
          )}
        </div>
        <div className="admin-order-detail-scroll">
          {selectedClaimMissing && (
            <div className="admin-state-banner neutral">
              <strong>선택한 클레임을 찾을 수 없음</strong>
              <span>목록이 갱신되며 선택했던 클레임이 현재 페이지에 보이지 않습니다. 표에서 다시 선택해 주세요.</span>
            </div>
          )}
          {!selectedRow ? (
            <div className="admin-detail-body">
              <p className="admin-metric-group-title">기본 정보</p>
              <dl className="admin-metric-list">
                <div>
                  <dt>주문번호</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>고객</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>주문 상태</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>유형</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>결제 수단</dt>
                  <dd>-</dd>
                </div>
              </dl>

              <p className="admin-metric-group-title">상품 정보</p>
              <dl className="admin-metric-list">
                <div>
                  <dt>상품</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>환불 예정액</dt>
                  <dd>-</dd>
                </div>
              </dl>

              <p className="admin-metric-group-title">클레임 정보</p>
              <dl className="admin-metric-list">
                <div>
                  <dt>신청 사유</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>고객 상세 사유</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>관리자 처리 사유</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>신청일시</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>처리일시</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>완료일시</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>가능한 액션</dt>
                  <dd>-</dd>
                </div>
              </dl>
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
              <div className="admin-detail-body">
                <p className="admin-metric-group-title">기본 정보</p>
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
                    <dt>결제 수단</dt>
                    <dd>{detail.paymentProvider ?? "-"}</dd>
                  </div>
                </dl>

                <p className="admin-metric-group-title">상품 정보</p>
                <dl className="admin-metric-list">
                  <div>
                    <dt>상품</dt>
                    <dd>{detail.productSummary}</dd>
                  </div>
                  <div>
                    <dt>환불 예정액</dt>
                    <dd>{detail.refundAmount === null ? "해당 없음" : formatCurrency(detail.refundAmount)}</dd>
                  </div>
                </dl>

                <p className="admin-metric-group-title">클레임 정보</p>
                <dl className="admin-metric-list">
                  <div>
                    <dt>신청 사유</dt>
                    <dd>{detail.reasonCode}</dd>
                  </div>
                  <div>
                    <dt>고객 상세 사유</dt>
                    <dd>{detail.reasonDetail ?? "-"}</dd>
                  </div>
                  <div>
                    <dt>관리자 처리 사유</dt>
                    <dd>
                      <button className="admin-text-button" onClick={() => setHistoryModalOpen(true)} type="button">
                        {decisionReason ?? "상품·이력 보기"}
                      </button>
                    </dd>
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
              </div>
              {/* 승인·거절·처리시작·완료 버튼은 서버가 계산한 available_actions 기준으로만 표시한다 — 프론트는 직접 계산하지 않는다 */}
              {detail.availableActions.length > 0 && (
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
                    <button
                      className="admin-primary-button"
                      disabled={actionInProgress}
                      onClick={() => handleActionButtonClick("COMPLETE", detail.claimCode, detail.orderCode, detail.claimType)}
                      type="button"
                    >
                      {actionInProgress && actionClaimCode === detail.claimCode ? "처리 중..." : "완료 처리"}
                    </button>
                  )}
                  {detail.availableActions.includes("REJECT") && (
                    <>
                      <textarea
                        aria-label="거절 사유"
                        className="admin-cancel-rejection-reason"
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
            </>
          ) : null}
        </div>
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
                      : `${pendingAction.orderCode} 클레임을 완료 처리할까요? 환불이 실행되며, 되돌릴 수 없습니다.`
              : ""
          }
          onCancel={() => {
            if (actionInProgress) return;
            setPendingAction(null);
          }}
          onConfirm={() => void executeAction()}
          open={pendingAction !== null}
          title="클레임 처리 확인"
        >
          {/* 반품·환불 완료 처리 시 재고 복구 여부는 체크박스를 따로 두지 않고 이 확인 모달
              안에서만 고르게 한다 — 실행 직전에 한 번 더 확인받는 화면에 함께 두는 게 더 명확하다. */}
          {pendingAction?.action === "COMPLETE" && pendingAction.claimType !== "EXCHANGE" && (
            <button
              aria-checked={restockOnComplete}
              className={`admin-modal-toggle-chip${restockOnComplete ? " active" : ""}`}
              disabled={actionInProgress}
              onClick={() => setRestockOnComplete((current) => !current)}
              role="checkbox"
              type="button"
            >
              {pendingAction.claimType === "RETURN" ? "반품 수령 확인 — 재고 복구" : "환불 수령 확인 — 재고 복구"}
            </button>
          )}
        </ConfirmModal>
        {detail && (
          <InfoModal
            onClose={() => setHistoryModalOpen(false)}
            open={historyModalOpen}
            title={`${detail.claimCode} 처리 내역`}
          >
            <div className="admin-detail-body">
            <p className="admin-metric-group-title">상품 목록</p>
            <div className="admin-table-wrap">
              <table className="admin-table compact admin-claim-item-table">
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
                      <td className="admin-file-name" title={item.productNameSnapshot}>
                        {item.productNameSnapshot}
                      </td>
                      <td>{item.quantity}개</td>
                      <td>{item.resolution === "REFUND" ? "환불" : "교환"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="admin-metric-group-title">처리 이력</p>
            <div className="admin-table-wrap">
              <table className="admin-table compact admin-claim-history-table">
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
                      <td title={event.reason ?? undefined}>{event.reason ?? "-"}</td>
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
            </div>
          </InfoModal>
        )}
      </aside>

      <section className="admin-panel admin-order-exception-panel">
        <div className="admin-panel-header compact">
          <div>
            <p>확인 필요</p>
            <h2>반품·교환·환불 처리 실패</h2>
          </div>
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table compact">
            <thead>
              <tr>
                <th scope="col">시간</th>
                <th scope="col">클레임</th>
                <th scope="col">주문</th>
                <th scope="col">유형</th>
              </tr>
            </thead>
            <tbody>
              {completionFailures.map((row) => (
                <tr key={row.id}>
                  <td>{row.time}</td>
                  <td className="admin-file-name" title={row.claimCode}>
                    {row.claimCode}
                  </td>
                  <td title={row.orderCode}>{row.orderCode}</td>
                  <td>{row.claimTypeLabel}</td>
                </tr>
              ))}
              {completionFailures.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={4}>
                    아직 기록된 완료 처리 실패가 없습니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
