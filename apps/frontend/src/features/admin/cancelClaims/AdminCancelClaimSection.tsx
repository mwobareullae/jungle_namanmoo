import { useCallback, useEffect, useRef, useState } from "react";

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

// 관리자 취소·클레임 관리 화면 (M1.5-B, 1단계: 조회만).
// 취소 요청/클레임 탭으로 나뉘고, Order.status 와 무관하게 각자 독립적으로 조회한다
// (클레임 진행 상황은 Order.status 에 동기화되지 않기로 확정했으므로 주문 화면과는 분리된 화면).
// 승인·거절·처리시작·완료 액션은 2·3단계에서 추가한다 — 이번엔 available_actions 표시까지만.

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
  const { items, hasMore, loading, loadingMore, error, statusFilter, setStatusFilter, resetFilters, refresh, loadMore } =
    useAdminCancelRequests({ enabled: active });
  const [selectedRequestCode, setSelectedRequestCode] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminCancelRequestDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const detailRequestIdRef = useRef(0);

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
    void loadDetail(requestCode);
  };

  // 필터·페이지 변경 등으로 선택했던 행이 목록에서 사라지면, 화면 헤더(새 목록의 첫 행)와
  // 상세 패널(이전에 선택했던 행)이 서로 다른 데이터를 보여주는 불일치를 막기 위해
  // 새 목록의 첫 행으로 선택·상세 조회를 다시 맞춘다.
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
      if (!stillPresent) {
        const fallbackCode = items[0].requestCode;
        setSelectedRequestCode(fallbackCode);
        void loadDetail(fallbackCode);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  const handleRefresh = async () => {
    const succeeded = await refresh();
    onOperationLog(
      "취소 요청",
      succeeded ? "목록 새로고침" : "새로고침 실패",
      succeeded ? "취소 요청 목록을 다시 불러왔습니다." : "잠시 후 다시 시도해 주세요.",
      succeeded ? "success" : "danger"
    );
  };

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
            <button className="admin-secondary-button" onClick={resetFilters} type="button">
              초기화
            </button>
            <button className="admin-primary-button" disabled={loading} onClick={handleRefresh} type="button">
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
          <button className="admin-secondary-button" disabled={loadingMore} onClick={loadMore} type="button">
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
      </aside>
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
    goToPage
  } = useAdminClaims({ enabled: active });
  const [selectedClaimCode, setSelectedClaimCode] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminClaimDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const detailRequestIdRef = useRef(0);

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
    void loadDetail(claimCode);
  };

  // 필터·페이지 변경으로 선택했던 클레임이 목록에서 사라지면 새 목록의 첫 행으로
  // 선택·상세 조회를 다시 맞춰, 헤더와 상세 패널이 서로 다른 데이터를 보여주지 않게 한다.
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
      if (!stillPresent) {
        const fallbackCode = items[0].claimCode;
        setSelectedClaimCode(fallbackCode);
        void loadDetail(fallbackCode);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  const handleRefresh = async () => {
    const succeeded = await refresh();
    onOperationLog(
      "클레임",
      succeeded ? "목록 새로고침" : "새로고침 실패",
      succeeded ? "클레임 목록을 다시 불러왔습니다." : "잠시 후 다시 시도해 주세요.",
      succeeded ? "success" : "danger"
    );
  };

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
            <button className="admin-secondary-button" onClick={resetFilters} type="button">
              초기화
            </button>
            <button className="admin-primary-button" disabled={loading} onClick={handleRefresh} type="button">
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
          <button className="admin-secondary-button" disabled={page <= 1} onClick={() => goToPage(page - 1)} type="button">
            이전
          </button>
          <span>
            {page} / {totalPages} 페이지
          </span>
          <button
            className="admin-secondary-button"
            disabled={page >= totalPages}
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
      </aside>
    </>
  );
}
